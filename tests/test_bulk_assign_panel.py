# tests/test_bulk_assign_panel.py
"""BulkAssignPanel staging: auto-map, drag pairs, unassign staging, episode
filter, and apply payload."""

from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _bulk_state(slots: int = 5, names: tuple[str, ...] = ("b.mkv", "a.mkv", "c.mkv")):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    table.add_slot(EpisodeSlot(season=2, episode=1, title="Pilot"))
    for name in names:
        # b.mkv carries real scan-time parse evidence (S01E01); a.mkv/c.mkv
        # don't, so auto-map tests can tell evidence-driven staging apart
        # from a positional fill. E01 is free (only E02 is pre-claimed).
        evidence = {"parsed_episodes": (1,), "season_hint": 1} if name == "b.mkv" else {}
        entry = table.add_file(Path(f"C:/lib/Show/{name}"), **evidence)
        table.mark_unassigned(entry.file_id, "no episode parsed")
    claimed = table.add_file(Path("C:/lib/Show/claimed.mkv"))
    table.assign(claimed.file_id, 1, [2], origin=ORIGIN_MANUAL)  # E02 pre-claimed
    state = ScanState(
        folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"}
    )
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


def _fid_by_name(panel, name: str) -> int:
    return next(p.file_id for p in panel._previews if p.original.name == name)


def _bulk_state_with_parsed_files():
    """b.mkv parses to S01E03; a.mkv has no parse evidence at all — used to
    prove auto-map follows evidence rather than filling the first free slot
    it finds (the old positional-zip bug)."""
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot

    table = EpisodeAssignmentTable()
    for episode in range(1, 5):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    parsed = table.add_file(
        Path("C:/lib/Show/b - S01E03.mkv"),
        parsed_episodes=(3,),
        season_hint=1,
    )
    table.mark_unassigned(parsed.file_id, "could not parse episode number")
    unparsed = table.add_file(Path("C:/lib/Show/a.mkv"))
    table.mark_unassigned(unparsed.file_id, "could not parse episode number")
    state = ScanState(
        folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"}
    )
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


def _bulk_state_assigned_with_evidence():
    """One file, already assigned, whose OWN parse evidence points at the
    exact slot it's assigned to — for the Unassign-all -> Auto-map-remaining
    round trip (the file must be able to re-stage onto the slot it just
    vacated, even though the underlying table still shows it claimed until
    Apply actually runs)."""
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_AUTO,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, 5):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    entry = table.add_file(
        Path("C:/lib/Show/Show - S01E01.mkv"),
        parsed_episodes=(1,),
        season_hint=1,
    )
    table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
    state = ScanState(
        folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"}
    )
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


def _number_of_claimed_slots(state) -> int:
    return len(state.assignments.assignments())


def _bulk_state_with_conflict(slots: int = 5, names: tuple[str, ...] = ("b.mkv", "a.mkv", "c.mkv")):
    """Like _bulk_state, but (1, 2) is contested by two files instead of
    cleanly claimed by one."""
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_AUTO,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    table.add_slot(EpisodeSlot(season=2, episode=1, title="Pilot"))
    for name in names:
        entry = table.add_file(Path(f"C:/lib/Show/{name}"))
        table.mark_unassigned(entry.file_id, "no episode parsed")
    claimant_a = table.add_file(Path("C:/lib/Show/conflict_a.mkv"))
    claimant_b = table.add_file(Path("C:/lib/Show/conflict_b.mkv"))
    table.assign(claimant_a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
    table.assign(claimant_b.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
    state = ScanState(
        folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"}
    )
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


class BulkAssignPanelTests(QtSmokeBase):
    def _panel(self):
        from plex_renamer.gui_qt.widgets._bulk_assign_panel import BulkAssignPanel

        state, service = _bulk_state()
        panel = BulkAssignPanel()
        panel.resize(900, 600)
        panel.show_state(state, service)

        # Destroy each panel right after its own test (deleteLater + a
        # flush + an explicit collect) instead of leaving 20+ live panels
        # for QtSmokeBase.tearDownClass's single end-of-class gc.collect()
        # to untangle at once. See docs/superpowers/sdd/p3-task-2-report.md
        # for the (separate, not-fully-root-caused) smoke-suite crash this
        # module's investigation surfaced in test_qt_media_workspace.py.
        def _cleanup() -> None:
            import gc

            panel.deleteLater()
            self._app.processEvents()
            gc.collect()

        self.addCleanup(_cleanup)
        return panel

    def _panel_with_conflict(self):
        from plex_renamer.gui_qt.widgets._bulk_assign_panel import BulkAssignPanel

        state, service = _bulk_state_with_conflict()
        panel = BulkAssignPanel()
        panel.resize(900, 600)
        panel.show_state(state, service)

        def _cleanup() -> None:
            import gc

            panel.deleteLater()
            self._app.processEvents()
            gc.collect()

        self.addCleanup(_cleanup)
        return panel

    def _panel_with_parsed_files(self):
        from plex_renamer.gui_qt.widgets._bulk_assign_panel import BulkAssignPanel

        state, service = _bulk_state_with_parsed_files()
        panel = BulkAssignPanel()
        panel.resize(900, 600)
        panel.show_state(state, service)

        def _cleanup() -> None:
            import gc

            panel.deleteLater()
            self._app.processEvents()
            gc.collect()

        self.addCleanup(_cleanup)
        return panel

    def _panel_assigned_with_evidence(self):
        from plex_renamer.gui_qt.widgets._bulk_assign_panel import BulkAssignPanel

        state, service = _bulk_state_assigned_with_evidence()
        panel = BulkAssignPanel()
        panel.resize(900, 600)
        panel.show_state(state, service)

        def _cleanup() -> None:
            import gc

            panel.deleteLater()
            self._app.processEvents()
            gc.collect()

        self.addCleanup(_cleanup)
        return panel

    def _conflict_claimants(self, panel) -> list[tuple[int, str]]:
        return list(panel._claims_by_key.get((1, 2), []))

    def _first_free_file_id(self, panel) -> int:
        model = panel._files_model
        unstaged = model.stageable_file_ids()
        if not unstaged:
            raise AssertionError("no free/stageable file in fixture")
        return unstaged[0]

    def test_files_sorted_and_searchable(self):
        panel = self._panel()
        panel._files_filter.setCurrentText("All")  # all 4 previews, including the assigned one
        model = panel._files_model
        names = [model.index(r, 0).data() for r in range(model.rowCount())]
        # all primary files, including the pre-claimed one, sorted by name
        self.assertEqual(len(names), 4)
        self.assertTrue(any(n.startswith("a.mkv") for n in names))
        self.assertTrue(any(n.startswith("b.mkv") for n in names))
        self.assertTrue(any(n.startswith("c.mkv") for n in names))
        self.assertTrue(any(n.startswith("claimed.mkv") for n in names))
        panel._search_box.setText("b.m")
        self.assertEqual(panel._files_model.rowCount(), 1)
        panel._search_box.setText("")
        self.assertEqual(panel._files_model.rowCount(), 4)

    def test_files_pane_lists_assigned_files(self):
        panel = self._panel()
        panel._files_filter.setCurrentText("All")  # assigned files only show under All
        names = [
            panel._files_model.data(panel._files_model.index(r, 0))
            for r in range(panel._files_model.rowCount())
        ]
        assert any("S01E02" in n for n in names)  # assigned file visible with mapping
        assert any("(assigned)" in n for n in names)

    def test_assigned_file_is_not_stageable_until_unassign_staged(self):
        panel = self._panel()
        model = panel._files_model
        claimed_fid = panel._claimed_file_by_key[(1, 2)]
        self.assertNotIn(claimed_fid, model.stageable_file_ids())
        # stage the unassign via the slot click path, then it becomes stageable
        row_slot = panel._slots_model.row_for_key((1, 2))
        panel._on_slot_clicked(panel._slots_model.index(row_slot, 0))
        self.assertIn(claimed_fid, model.stageable_file_ids())

    def test_click_claimed_slot_stages_unassign_and_frees_file(self):
        panel = self._panel()
        row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.is_claimed(panel._slots_model.slot_key_at(r) or (-1, -1))
        )
        panel._on_slot_clicked(panel._slots_model.index(row, 0))
        self.assertTrue(panel.staged_unassigns())
        fid = panel.staged_unassigns()[0]
        self.assertIn(fid, panel._files_model.stageable_file_ids())

    def test_click_claimed_slot_toggles_unassign_off(self):
        panel = self._panel()
        row = panel._slots_model.row_for_key((1, 2))
        index = panel._slots_model.index(row, 0)
        panel._on_slot_clicked(index)
        self.assertEqual(panel.staged_unassigns(), [panel._claimed_file_by_key[(1, 2)]])
        panel._on_slot_clicked(index)
        self.assertEqual(panel.staged_unassigns(), [])

    def test_toggling_unassign_off_drops_dependent_stage(self):
        panel = self._panel()
        row = panel._slots_model.row_for_key((1, 2))
        index = panel._slots_model.index(row, 0)
        panel._on_slot_clicked(index)  # stage unassign of E02
        other_fid = self._first_free_file_id(panel)
        panel._handle_drop(other_fid, (1, 2))  # restage E02 to a different file
        self.assertIn((other_fid, 1, 2), panel.staged_pairs())
        panel._on_slot_clicked(index)  # toggle unassign back off
        self.assertEqual(panel.staged_unassigns(), [])
        self.assertNotIn((other_fid, 1, 2), panel.staged_pairs())

    def test_toggling_unassign_off_drops_own_restage_elsewhere(self):
        # Regression: X claimed at (1,2) → stage unassign → drag X onto a
        # free slot (allowed while unassign-staged) → cancel the unassign.
        # X's own staged pair must be dropped too, or Apply would silently
        # move X even though the UI shows no pending change.
        panel = self._panel()
        claimed_fid = panel._claimed_file_by_key[(1, 2)]
        row = panel._slots_model.row_for_key((1, 2))
        index = panel._slots_model.index(row, 0)
        panel._on_slot_clicked(index)  # stage unassign of X
        panel._handle_drop(claimed_fid, (1, 5))  # restage X elsewhere
        self.assertIn((claimed_fid, 1, 5), panel.staged_pairs())
        panel._on_slot_clicked(index)  # cancel the unassign
        self.assertEqual(panel.staged_unassigns(), [])
        self.assertEqual(
            [p for p in panel.staged_pairs() if p[0] == claimed_fid],
            [],
        )
        # nothing else staged → staging is empty and Apply reflects that
        self.assertEqual(panel.staged_pairs(), [])
        self.assertFalse(panel._apply_button.isEnabled())

    def test_unassign_all_clears_manual_staging(self):
        panel = self._panel()
        free_fid = self._first_free_file_id(panel)
        panel._handle_drop(free_fid, (1, 1))  # manual stage
        self.assertTrue(panel.staged_pairs())
        panel.unassign_all()
        self.assertEqual(panel.staged_pairs(), [])  # staging cleared
        self.assertEqual(
            set(panel.staged_unassigns()),
            set(panel._assigned_key_by_file),  # all pre-assigned files staged for unassign
        )
        self.assertTrue(panel._apply_button.isEnabled())

    def test_unassign_all_stages_every_claimed_slot(self):
        panel = self._panel()
        panel.unassign_all()
        self.assertEqual(len(panel.staged_unassigns()), _number_of_claimed_slots(panel._state))

    def test_reset_clears_both_stagings(self):
        panel = self._panel()
        panel.unassign_all()
        panel.auto_map_remaining()
        self.assertTrue(panel.staged_pairs())
        self.assertTrue(panel.staged_unassigns())
        panel.reset_staging()
        self.assertEqual(panel.staged_pairs(), [])
        self.assertEqual(panel.staged_unassigns(), [])
        self.assertFalse(panel._apply_button.isEnabled())

    def test_no_assign_in_order_button_or_checkboxes(self):
        from PySide6.QtCore import Qt

        panel = self._panel()
        self.assertFalse(hasattr(panel, "_assign_button"))
        model = panel._files_model
        for row in range(model.rowCount()):
            self.assertFalse(
                bool(model.flags(model.index(row, 0)) & Qt.ItemFlag.ItemIsUserCheckable)
            )

    def test_auto_map_remaining_uses_evidence_not_positional_fill(self):
        # Task 14 regression: only b.mkv carries scan-time parse evidence
        # (S01E01). a.mkv/c.mkv have none and must stay unstaged rather than
        # being zipped onto the remaining free slots (E03/E04/E05) the old
        # positional fill would have used.
        panel = self._panel()
        panel.auto_map_remaining()
        self.assertEqual(panel.staged_pairs(), [(_fid_by_name(panel, "b.mkv"), 1, 1)])
        self.assertIn("2 file(s) left unstaged", panel._status_label.text())

    def test_auto_map_uses_evidence_not_position(self):
        panel = self._panel_with_parsed_files()  # b.mkv parses to S01E03, a.mkv unparsable
        panel.auto_map_remaining()
        staged = dict(panel._staged_pairs)
        parsed_fid = _fid_by_name(panel, "b - S01E03.mkv")
        unparsed_fid = _fid_by_name(panel, "a.mkv")
        self.assertEqual(staged[parsed_fid], (1, 3))  # NOT the first free slot
        self.assertNotIn(unparsed_fid, staged)

    def test_auto_map_considers_full_pool_not_just_problems_filter(self):
        # auto_map_remaining must not be limited by the files pane's current
        # mode/search filter — the Problems default view still shows b.mkv
        # (it's unassigned), but this proves the "All" filter or a search
        # box narrowing the visible rows wouldn't silently shrink the pool.
        panel = self._panel()
        panel._search_box.setText("nonexistent-needle")  # visible rows -> 0
        self.assertEqual(panel._files_model.rowCount(), 0)
        panel.auto_map_remaining()
        self.assertEqual(panel.staged_pairs(), [(_fid_by_name(panel, "b.mkv"), 1, 1)])

    def test_unassign_all_then_auto_map_restages_evidence_file(self):
        # The taken/claimed_slots round trip this task's brief called out:
        # a file already assigned to a slot that also matches its own parse
        # evidence must be able to re-stage onto that same slot after
        # Unassign-all, even though the underlying table still reports the
        # slot as claimed until Apply actually runs.
        panel = self._panel_assigned_with_evidence()
        file_id = panel._claimed_file_by_key[(1, 1)]
        panel.unassign_all()
        self.assertEqual(panel.staged_pairs(), [])
        self.assertIn(file_id, panel.staged_unassigns())
        panel.auto_map_remaining()
        self.assertIn((file_id, 1, 1), panel.staged_pairs())

    def test_drop_stages_single_pair_and_rejects_claimed(self):
        panel = self._panel()
        file_id = panel._files_model.file_id_at(0)
        panel._handle_drop(file_id, (1, 4))
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        panel._handle_drop(file_id, (1, 2))  # claimed → ignored
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        self.assertEqual(len(panel.staged_pairs()), 1)

    def test_drop_onto_claimed_slot_sets_status_message(self):
        # Final-review fix: a drop rejected by _key_is_free used to no-op
        # silently, including on the unassign-first discovery path, leaving
        # the user with no feedback about why the drop did nothing.
        panel = self._panel()
        file_id = panel._files_model.file_id_at(0)
        panel._status_label.setText("")
        panel._handle_drop(file_id, (1, 2))  # (1, 2) is pre-claimed
        self.assertNotIn((file_id, 1, 2), panel.staged_pairs())
        self.assertEqual(panel.staged_pairs(), [])
        self.assertTrue(panel._status_label.text())

    def test_same_file_can_stage_multiple_slots_same_season(self):
        panel = self._panel()
        fid = self._first_free_file_id(panel)
        panel._handle_drop(fid, (1, 3))
        panel._handle_drop(fid, (1, 4))
        self.assertEqual(
            [(f, s, e) for f, s, e in panel.staged_pairs() if f == fid],
            [(fid, 1, 3), (fid, 1, 4)],
        )

    def test_multi_episode_stage_rejects_non_adjacent(self):
        panel = self._panel()
        fid = self._first_free_file_id(panel)
        panel._handle_drop(fid, (1, 3))
        panel._handle_drop(fid, (1, 6))  # not contiguous with the staged run
        self.assertEqual(
            [(f, s, e) for f, s, e in panel.staged_pairs() if f == fid],
            [(fid, 1, 3)],
        )
        self.assertTrue(panel._status_label.text())

    def test_cross_season_second_stage_rejected(self):
        panel = self._panel()
        fid = self._first_free_file_id(panel)
        panel._handle_drop(fid, (1, 3))
        panel._handle_drop(fid, (2, 1))
        self.assertTrue(all(s == 1 for f, s, e in panel.staged_pairs() if f == fid))
        self.assertEqual(len(panel.staged_pairs()), 1)

    def test_files_model_renders_multi_episode_stage(self):
        panel = self._panel()
        fid = self._first_free_file_id(panel)
        panel._handle_drop(fid, (1, 3))
        panel._handle_drop(fid, (1, 4))
        # staged-to-a-slot files drop out of the default Problems view
        panel._files_filter.setCurrentText("All")
        model = panel._files_model
        row = next(r for r in range(model.rowCount()) if model.file_id_at(r) == fid)
        text = model.index(row, 0).data()
        self.assertIn("S01E03", text)
        self.assertIn("S01E04", text)
        self.assertIn("→", text)

    def test_episode_filter_narrows_slots(self):
        panel = self._panel()
        panel._slot_search_box.setText("Pilot")
        keys = [panel._slots_model.slot_key_at(r) for r in range(panel._slots_model.rowCount())]
        non_header_keys = [k for k in keys if k is not None]
        self.assertEqual(non_header_keys, [(2, 1)])  # only the season-2 Pilot slot matches
        panel._slot_search_box.setText("")
        self.assertGreater(panel._slots_model.rowCount(), len(non_header_keys) + 1)

    def test_anchor_feature_removed(self):
        panel = self._panel()
        self.assertFalse(hasattr(panel, "_anchor_key"))

    def test_apply_enabled_when_only_unassign_staged(self):
        panel = self._panel()
        self.assertFalse(panel._apply_button.isEnabled())
        panel.unassign_all()
        self.assertTrue(panel._apply_button.isEnabled())

    def test_apply_emits_payload_and_reset_clears(self):
        panel = self._panel()
        panel.auto_map_remaining()
        panel.unassign_all()
        fired: list[tuple[list, list]] = []
        panel.apply_requested.connect(lambda pairs, unassigns: fired.append((pairs, unassigns)))
        self.assertTrue(panel._apply_button.isEnabled())
        panel._apply_button.click()
        self.assertEqual(len(fired), 1)
        pairs, unassigns = fired[0]
        self.assertEqual(len(pairs), 0)  # unassign_all clears manually staged pairs
        self.assertEqual(unassigns, [panel._claimed_file_by_key[(1, 2)]])
        panel.reset_staging()
        self.assertEqual(panel.staged_pairs(), [])
        self.assertEqual(panel.staged_unassigns(), [])
        self.assertFalse(panel._apply_button.isEnabled())

    def test_slot_rows_show_claim_and_staged_markers(self):
        panel = self._panel()
        model = panel._slots_model
        claimed_row = model.row_for_key((1, 2))
        self.assertIn("claimed.mkv", model.index(claimed_row, 0).data())
        panel._handle_drop(panel._files_model.file_id_at(0), (1, 1))
        staged_row = panel._slots_model.row_for_key((1, 1))
        self.assertIn("→", panel._slots_model.index(staged_row, 0).data())

    def test_slot_row_shows_will_unassign_marker(self):
        panel = self._panel()
        row = panel._slots_model.row_for_key((1, 2))
        panel._on_slot_clicked(panel._slots_model.index(row, 0))
        text = panel._slots_model.index(row, 0).data()
        self.assertIn("will unassign", text)

    def test_conflicted_slot_renders_as_conflict_not_missing(self):
        panel = self._panel_with_conflict()
        row = panel._slots_model.row_for_key((1, 2))
        text = panel._slots_model.index(row, 0).data()
        self.assertIn("CONFLICT", text.upper())
        self.assertNotIn("missing", text)

    def test_conflicted_files_are_not_stageable(self):
        panel = self._panel_with_conflict()
        for fid, _name in self._conflict_claimants(panel):
            panel._handle_drop(fid, (1, 3))
            self.assertNotIn(fid, [f for f, _k in panel._staged_pairs])

    def test_selecting_file_highlights_its_slots(self):
        panel = self._panel()  # has claimed.mkv on S01E02
        panel._files_filter.setCurrentText("All")  # assigned file only visible under All
        fid = panel._claimed_file_by_key[(1, 2)]
        panel._select_file(fid)
        selected_keys = [
            panel._slots_model.slot_key_at(i.row())
            for i in panel._slots_view.selectionModel().selectedIndexes()
        ]
        self.assertIn((1, 2), selected_keys)

    def test_third_file_cannot_drop_onto_an_unresolved_conflicted_slot(self):
        panel = self._panel_with_conflict()
        free_fid = self._first_free_file_id(panel)
        panel._handle_drop(free_fid, (1, 2))  # (1, 2) is still contested
        self.assertNotIn((free_fid, (1, 2)), panel._staged_pairs)
        self.assertTrue(panel._status_label.text())

    def test_third_file_can_drop_onto_conflicted_slot_once_fully_unassign_staged(self):
        panel = self._panel_with_conflict()
        row = panel._slots_model.row_for_key((1, 2))
        panel._on_slot_clicked(
            panel._slots_model.index(row, 0)
        )  # stage unassign for both claimants
        free_fid = self._first_free_file_id(panel)
        panel._handle_drop(free_fid, (1, 2))
        self.assertIn((free_fid, (1, 2)), panel._staged_pairs)

    def test_conflicted_slot_with_all_claimants_unassign_staged_reads_as_will_unassign(self):
        panel = self._panel_with_conflict()
        row = panel._slots_model.row_for_key((1, 2))
        panel._on_slot_clicked(panel._slots_model.index(row, 0))
        text = panel._slots_model.index(row, 0).data()
        self.assertIn("will unassign", text)
        self.assertNotIn("CONFLICT:", text)
        for fid, _name in self._conflict_claimants(panel):
            self.assertIn(fid, panel.staged_unassigns())

    # -- Task 12: problems filters + collapsible season headers -----------

    def test_files_pane_defaults_to_problems(self):
        panel = self._panel()
        self.assertEqual(panel._files_filter.currentText(), "Problems")
        names = [
            panel._files_model.index(r, 0).data() for r in range(panel._files_model.rowCount())
        ]
        self.assertFalse(any("(assigned)" in n for n in names))
        panel._files_filter.setCurrentText("All")
        names = [
            panel._files_model.index(r, 0).data() for r in range(panel._files_model.rowCount())
        ]
        self.assertTrue(any("(assigned)" in n for n in names))

    def test_files_pane_problems_includes_conflicted_and_drops_staged(self):
        panel = self._panel_with_conflict()
        # both conflict claimants show up under the default Problems filter
        conflict_ids = {fid for fid, _name in self._conflict_claimants(panel)}
        visible_ids = {
            panel._files_model.file_id_at(r) for r in range(panel._files_model.rowCount())
        }
        self.assertTrue(conflict_ids.issubset(visible_ids))
        # staging a free file onto a slot drops it out of the Problems view
        free_fid = self._first_free_file_id(panel)
        self.assertIn(free_fid, visible_ids)
        panel._handle_drop(free_fid, (1, 3))
        visible_ids = {
            panel._files_model.file_id_at(r) for r in range(panel._files_model.rowCount())
        }
        self.assertNotIn(free_fid, visible_ids)

    def test_slots_pane_defaults_to_all(self):
        panel = self._panel()
        self.assertEqual(panel._slots_filter.currentText(), "All")

    def test_slots_problems_filter_shows_only_problem_slots(self):
        panel = self._panel()
        panel._slots_filter.setCurrentText("Problems")
        rows = [
            panel._slots_model.index(r, 0).data()
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is not None
        ]
        self.assertTrue(rows)
        self.assertTrue(all("missing" in t or "CONFLICT" in t or "unassign" in t for t in rows))

    def test_slots_problems_filter_hides_ordinary_assigned_rows(self):
        panel = self._panel()
        panel._slots_filter.setCurrentText("Problems")
        row = panel._slots_model.row_for_key((1, 2))  # cleanly claimed by claimed.mkv
        self.assertEqual(row, -1)

    def test_season_headers_show_counts_and_collapse(self):
        panel = self._panel()
        header_row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is None
        )
        text = panel._slots_model.index(header_row, 0).data()
        self.assertRegex(text, r"Season 01 — \d+/\d+ assigned")
        # exact math: 5 season-1 slots, exactly one (E02) single-claimed
        self.assertEqual(text, "▾ Season 01 — 1/5 assigned")
        before = panel._slots_model.rowCount()
        panel._on_slot_clicked(panel._slots_model.index(header_row, 0))
        self.assertLess(panel._slots_model.rowCount(), before)
        self.assertEqual(
            panel._slots_model.index(header_row, 0).data(),
            "▸ Season 01 — 1/5 assigned",
        )

    def test_unassign_staged_claimant_drops_out_of_header_count(self):
        panel = self._panel()
        row = panel._slots_model.row_for_key((1, 2))
        panel._on_slot_clicked(panel._slots_model.index(row, 0))  # stage unassign of E02
        header_row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is None
        )
        self.assertEqual(
            panel._slots_model.index(header_row, 0).data(),
            "▾ Season 01 — 0/5 assigned",
        )

    def test_conflicted_slot_does_not_count_as_assigned_in_header(self):
        panel = self._panel_with_conflict()
        header_row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is None
        )
        # (1, 2) is contested by two claimants — a conflicted slot is not
        # "assigned", so season 1's count stays at 0/5.
        self.assertEqual(
            panel._slots_model.index(header_row, 0).data(),
            "▾ Season 01 — 0/5 assigned",
        )

    def test_season_header_toggle_expands_again(self):
        panel = self._panel()
        header_row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is None
        )
        before = panel._slots_model.rowCount()
        panel._on_slot_clicked(panel._slots_model.index(header_row, 0))
        panel._on_slot_clicked(panel._slots_model.index(header_row, 0))
        self.assertEqual(panel._slots_model.rowCount(), before)

    def test_season_02_header_shows_counts(self):
        panel = self._panel()
        header_row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is None
            and panel._slots_model.season_for_header_row(r) == 2
        )
        text = panel._slots_model.index(header_row, 0).data()
        # exact math: season 2 has one slot (Pilot), unclaimed
        self.assertEqual(text, "▾ Season 02 — 0/1 assigned")

    def test_season_for_header_row_returns_none_for_child_rows(self):
        panel = self._panel()
        row = panel._slots_model.row_for_key((1, 2))
        self.assertIsNone(panel._slots_model.season_for_header_row(row))

    def test_collapsed_seasons_reset_on_show_state(self):
        panel = self._panel()
        header_row = next(
            r
            for r in range(panel._slots_model.rowCount())
            if panel._slots_model.slot_key_at(r) is None
        )
        panel._on_slot_clicked(panel._slots_model.index(header_row, 0))
        self.assertTrue(panel._collapsed_seasons)
        state, service = _bulk_state()
        panel.show_state(state, service)
        self.assertEqual(panel._collapsed_seasons, set())
