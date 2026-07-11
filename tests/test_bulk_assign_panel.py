# tests/test_bulk_assign_panel.py
"""BulkAssignPanel staging: assign-in-order, auto-map, drag pairs, unassign
staging, episode filter, and apply payload."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _bulk_state(slots: int = 5, names: tuple[str, ...] = ("b.mkv", "a.mkv", "c.mkv")):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL, EpisodeAssignmentTable, EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    table.add_slot(EpisodeSlot(season=2, episode=1, title="Pilot"))
    for name in names:
        entry = table.add_file(Path(f"C:/lib/Show/{name}"))
        table.mark_unassigned(entry.file_id, "no episode parsed")
    claimed = table.add_file(Path("C:/lib/Show/claimed.mkv"))
    table.assign(claimed.file_id, 1, [2], origin=ORIGIN_MANUAL)   # E02 pre-claimed
    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"})
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


def _number_of_claimed_slots(state) -> int:
    return len(state.assignments.assignments())


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

    def _first_free_file_id(self, panel) -> int:
        model = panel._files_model
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if index.flags() & __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemFlag.ItemIsUserCheckable:
                return model.file_id_at(row)
        raise AssertionError("no free/checkable file in fixture")

    def test_files_sorted_and_searchable(self):
        panel = self._panel()
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
        names = [
            panel._files_model.data(panel._files_model.index(r, 0))
            for r in range(panel._files_model.rowCount())
        ]
        assert any("S01E02" in n for n in names)          # assigned file visible with mapping
        assert any("(assigned)" in n for n in names)

    def test_assigned_file_is_check_disabled_until_unassign_staged(self):
        from PySide6.QtCore import Qt

        panel = self._panel()
        model = panel._files_model
        row = next(
            r for r in range(model.rowCount())
            if model.file_id_at(r) == panel._claimed_file_by_key[(1, 2)]
        )
        index = model.index(row, 0)
        self.assertFalse(bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable))
        # stage the unassign via the slot click path, then it becomes checkable
        row_slot = panel._slots_model.row_for_key((1, 2))
        panel._on_slot_clicked(panel._slots_model.index(row_slot, 0))
        self.assertTrue(bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable))

    def test_click_claimed_slot_stages_unassign_and_frees_file(self):
        from PySide6.QtCore import Qt

        panel = self._panel()
        row = next(
            r for r in range(panel._slots_model.rowCount())
            if panel._slots_model.is_claimed(panel._slots_model.slot_key_at(r) or (-1, -1))
        )
        panel._on_slot_clicked(panel._slots_model.index(row, 0))
        self.assertTrue(panel.staged_unassigns())
        fid = panel.staged_unassigns()[0]
        checkable_ids = [
            panel._files_model.file_id_at(r) for r in range(panel._files_model.rowCount())
            if panel._files_model.flags(panel._files_model.index(r, 0)) & Qt.ItemFlag.ItemIsUserCheckable
        ]
        self.assertIn(fid, checkable_ids)

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
        claimed_fid = panel._claimed_file_by_key[(1, 2)]
        row = panel._slots_model.row_for_key((1, 2))
        index = panel._slots_model.index(row, 0)
        panel._on_slot_clicked(index)                      # stage unassign of E02
        other_fid = self._first_free_file_id(panel)
        panel._handle_drop(other_fid, (1, 2))               # restage E02 to a different file
        self.assertIn((other_fid, 1, 2), panel.staged_pairs())
        panel._on_slot_clicked(index)                       # toggle unassign back off
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
        panel._on_slot_clicked(index)                      # stage unassign of X
        panel._handle_drop(claimed_fid, (1, 5))             # restage X elsewhere
        self.assertIn((claimed_fid, 1, 5), panel.staged_pairs())
        panel._on_slot_clicked(index)                       # cancel the unassign
        self.assertEqual(panel.staged_unassigns(), [])
        self.assertEqual(
            [p for p in panel.staged_pairs() if p[0] == claimed_fid], [],
        )
        # nothing else staged → staging is empty and Apply reflects that
        self.assertEqual(panel.staged_pairs(), [])
        self.assertFalse(panel._apply_button.isEnabled())

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

    def test_assign_in_order_fills_free_slots_top_down(self):
        from PySide6.QtCore import Qt

        panel = self._panel()
        model = panel._files_model
        # check the three never-assigned files (a.mkv, b.mkv, c.mkv)
        checked = 0
        for row in range(model.rowCount()):
            name = model.index(row, 0).data()
            if name.startswith(("a.mkv", "b.mkv", "c.mkv")):
                model.setData(model.index(row, 0), Qt.CheckState.Checked.value,
                              Qt.ItemDataRole.CheckStateRole)
                checked += 1
        self.assertEqual(checked, 3)
        panel.assign_in_order()
        pairs = {(season, episode) for _fid, season, episode in panel.staged_pairs()}
        self.assertEqual(pairs, {(1, 1), (1, 3), (1, 4)})   # E02 claimed → skipped, top-down fill
        self.assertEqual(model.checked_file_ids(), [])

    def test_auto_map_remaining_fills_unclaimed_in_order(self):
        panel = self._panel()
        panel.auto_map_remaining()
        episodes = sorted(episode for _fid, _s, episode in panel.staged_pairs())
        self.assertEqual(episodes, [1, 3, 4])       # 3 files onto E01/E03/E04 (E02 claimed)
        self.assertEqual(len(panel.staged_pairs()), 3)

    def test_drop_stages_single_pair_and_rejects_claimed(self):
        panel = self._panel()
        file_id = panel._files_model.file_id_at(0)
        panel._handle_drop(file_id, (1, 4))
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        panel._handle_drop(file_id, (1, 2))          # claimed → ignored
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        self.assertEqual(len(panel.staged_pairs()), 1)

    def test_drop_onto_claimed_slot_sets_status_message(self):
        # Final-review fix: a drop rejected by _key_is_free used to no-op
        # silently, including on the unassign-first discovery path, leaving
        # the user with no feedback about why the drop did nothing.
        panel = self._panel()
        file_id = panel._files_model.file_id_at(0)
        panel._status_label.setText("")
        panel._handle_drop(file_id, (1, 2))          # (1, 2) is pre-claimed
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
        panel._handle_drop(fid, (1, 6))              # not contiguous with the staged run
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
        model = panel._files_model
        row = next(r for r in range(model.rowCount()) if model.file_id_at(r) == fid)
        text = model.index(row, 0).data()
        self.assertIn("S01E03", text)
        self.assertIn("S01E04", text)
        self.assertIn("→", text)

    def test_episode_filter_narrows_slots(self):
        panel = self._panel()
        panel._slot_search_box.setText("Pilot")
        keys = [
            panel._slots_model.slot_key_at(r)
            for r in range(panel._slots_model.rowCount())
        ]
        non_header_keys = [k for k in keys if k is not None]
        self.assertEqual(non_header_keys, [(2, 1)])   # only the season-2 Pilot slot matches
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
        self.assertEqual(len(pairs), 3)
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
