from __future__ import annotations

import unittest
from pathlib import Path

from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine import (
    CompanionFile,
    CompletenessReport,
    PreviewItem,
    ScanState,
    SeasonCompleteness,
)


def _preview(
    name: str,
    *,
    new_name: str | None = None,
    season: int | None = 1,
    episodes: list[int] | None = None,
    status: str = "OK",
    companions: list[CompanionFile] | None = None,
) -> PreviewItem:
    return PreviewItem(
        original=Path(f"C:/library/tv/Show/Season 01/{name}"),
        new_name=new_name or f"Show (2024) - S01E01 - Pilot{name[-4:]}",
        target_dir=Path("C:/library/tv/Show (2024)/Season 01"),
        season=season,
        episodes=episodes if episodes is not None else [1],
        status=status,
        companions=companions or [],
    )


class EpisodeMappingProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = EpisodeMappingService()

    def test_episode_guide_groups_companions_under_mapped_episode(self):
        subtitle = CompanionFile(
            original=Path("C:/library/tv/Show/Season 01/Show.S01E01.en.srt"),
            new_name="Show (2024) - S01E01 - Pilot.en.srt",
            file_type="subtitle",
        )
        item = _preview("Show.S01E01.mkv", companions=[subtitle])
        completeness = CompletenessReport(
            seasons={
                1: SeasonCompleteness(
                    season=1,
                    expected=2,
                    matched=1,
                    missing=[(2, "Second")],
                    matched_episodes=[(1, "Pilot")],
                )
            },
            specials=None,
            total_expected=2,
            total_matched=1,
            total_missing=[(1, 2, "Second")],
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[item],
            completeness=completeness,
            scanned=True,
        )

        guide = self.service.build_episode_guide(state)

        self.assertEqual(guide.source_label, "TMDB")
        self.assertEqual(guide.summary.mapped_episodes, 1)
        self.assertEqual(guide.summary.companion_files, 1)
        self.assertEqual(guide.summary.missing_episodes, 1)
        self.assertEqual(len(guide.rows), 2)
        mapped = guide.rows[0]
        self.assertEqual(mapped.status, "Mapped")
        self.assertEqual(mapped.episode_key, (1, 1))
        self.assertEqual(mapped.companions, [subtitle])
        self.assertEqual(mapped.target_rename, "Show (2024) - S01E01 - Pilot.mkv")
        missing = guide.rows[1]
        self.assertEqual(missing.status, "Missing File")
        self.assertEqual(missing.episode_key, (1, 2))
        self.assertIsNone(missing.primary_file)

    def test_unmapped_primary_files_and_orphan_companions_are_separate(self):
        orphan = CompanionFile(
            original=Path("C:/library/tv/Show/Season 01/Show.S01E99.en.srt"),
            new_name="",
            file_type="subtitle",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[
                _preview(
                    "Show.Unknown.mkv",
                    new_name=None,
                    season=None,
                    episodes=[],
                    status="SKIP: no episode mapping",
                )
            ],
            orphan_companion_files=[orphan],
            scanned=True,
        )

        guide = self.service.build_episode_guide(state)

        self.assertEqual(guide.summary.unmapped_primary_files, 1)
        self.assertEqual(guide.summary.orphan_companion_files, 1)
        self.assertEqual(guide.unmapped_primary_files[0].reason, "SKIP: no episode mapping")
        self.assertEqual(guide.orphan_companion_files, [orphan])

    def test_missing_specials_render_alongside_missing_regular_episodes(self):
        completeness = CompletenessReport(
            seasons={
                1: SeasonCompleteness(
                    season=1,
                    expected=2,
                    matched=1,
                    missing=[(2, "Second")],
                    matched_episodes=[(1, "Pilot")],
                )
            },
            specials=SeasonCompleteness(
                season=0,
                expected=2,
                matched=1,
                missing=[(2, "Holiday Special")],
                matched_episodes=[(1, "Pilot Special")],
            ),
            total_expected=2,
            total_matched=1,
            total_missing=[(1, 2, "Second")],
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[_preview("Show.S01E01.mkv")],
            completeness=completeness,
            scanned=True,
        )

        guide = self.service.build_episode_guide(state)

        missing_keys = {
            (row.season, row.episode) for row in guide.rows if row.status == "Missing File"
        }
        self.assertIn((1, 2), missing_keys)
        self.assertIn((0, 2), missing_keys)
        self.assertEqual(guide.summary.missing_episodes, 2)


if __name__ == "__main__":
    unittest.main()


from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)

ROOT = Path("C:/lib/Demo Show (2020)")
SHOW = {"id": 9, "name": "Demo Show", "year": "2020"}


def table_state() -> ScanState:
    table = EpisodeAssignmentTable()
    for episode, title in [(1, "Pilot"), (2, "Heist"), (3, "Endgame"), (4, "Coda")]:
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
    ok = table.add_file(ROOT / "e1.mkv")
    table.assign(ok.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
    stray = table.add_file(ROOT / "stray.mkv")
    table.mark_unassigned(stray.file_id, "could not parse episode number")
    state = ScanState(folder=ROOT, media_info=SHOW)
    state.assignments = table
    state.preview_items = project_preview_items(
        table,
        show_info=SHOW,
        root=ROOT,
        media_fields={"media_id": 9, "media_name": "Demo Show"},
    )
    state.scanned = True
    return state


class TestTableBackedService:
    def test_assign_unassigned_file_to_missing_episodes(self):
        state = table_state()
        service = EpisodeMappingService()
        stray = next(p for p in state.preview_items if p.new_name is None)
        service.assign_file(state, stray, season=1, episodes=[2, 3])
        updated = next(p for p in state.preview_items if p.original.name == "stray.mkv")
        assert updated.episodes == [2, 3]
        assert updated.status == "OK"
        assert updated.episode_confidence == 1.0

    def test_assign_displaces_existing_claimant(self):
        state = table_state()
        service = EpisodeMappingService()
        stray = next(p for p in state.preview_items if p.new_name is None)
        service.assign_file(state, stray, season=1, episodes=[1])
        displaced = next(p for p in state.preview_items if p.original.name == "e1.mkv")
        assert displaced.new_name is None  # back to unassigned

    def test_assign_or_extend_extends_contiguous(self):
        state = table_state()  # e1.mkv auto-assigned to [1]; slots 1-4 exist
        service = EpisodeMappingService()
        e1 = next(p for p in state.preview_items if p.status == "OK")
        service.assign_or_extend_file(state, e1, season=1, episode=2)
        updated = next(p for p in state.preview_items if p.original.name == "e1.mkv")
        assert updated.episodes == [1, 2]
        assert updated.episode_confidence == 1.0

    def test_assign_or_extend_replaces_when_not_contiguous(self):
        state = table_state()
        service = EpisodeMappingService()
        e1 = next(p for p in state.preview_items if p.status == "OK")
        service.assign_or_extend_file(state, e1, season=1, episode=4)
        updated = next(p for p in state.preview_items if p.original.name == "e1.mkv")
        assert updated.episodes == [4]

    def test_unassign_file(self):
        state = table_state()
        service = EpisodeMappingService()
        mapped = next(p for p in state.preview_items if p.status == "OK")
        service.unassign_file(state, mapped)
        assert all(p.new_name is None for p in state.preview_items if p.original.name == "e1.mkv")

    def test_approve_file(self):
        state = table_state()
        table = state.assignments
        low = table.add_file(ROOT / "low.mkv")
        table.assign(low.file_id, 1, [4], origin=ORIGIN_AUTO, confidence=0.5)
        service = EpisodeMappingService()
        service.reproject(state)
        review = next(p for p in state.preview_items if p.is_episode_review)
        service.approve_file(state, review)
        approved = next(p for p in state.preview_items if p.original.name == "low.mkv")
        assert approved.status == "OK"

    def test_slot_choices_show_claim_state(self):
        state = table_state()
        service = EpisodeMappingService()
        choices = service.episode_slot_choices(state)
        claimed = next(c for c in choices if (c.season, c.episode) == (1, 1))
        free = next(c for c in choices if (c.season, c.episode) == (1, 2))
        assert claimed.claimed_by == "e1.mkv"
        assert free.claimed_by is None

    def _state_with_conflict_on(self, season: int, episode: int):
        """ScanState where two files both claim (season, episode)."""
        state = table_state()
        table = state.assignments
        first = table.add_file(ROOT / "conflict_a.mkv")
        second = table.add_file(ROOT / "conflict_b.mkv")
        table.assign(first.file_id, season, [episode], origin=ORIGIN_AUTO, confidence=0.8)
        table.assign(second.file_id, season, [episode], origin=ORIGIN_AUTO, confidence=0.8)
        service = EpisodeMappingService()
        service.reproject(state)
        return state, service

    def test_slot_choices_expose_all_claimants(self):
        state, service = self._state_with_conflict_on(season=1, episode=2)
        choice = next(
            c for c in service.episode_slot_choices(state) if (c.season, c.episode) == (1, 2)
        )
        assert len(choice.claimants) == 2
        assert choice.claimed_file_id is None  # single-claim contract preserved

    def test_guide_lists_unassigned_with_reason(self):
        state = table_state()
        service = EpisodeMappingService()
        guide = service.build_episode_guide(state)
        assert guide.summary.unmapped_primary_files == 1
        assert guide.unmapped_primary_files[0].reason == ("could not parse episode number")

    def test_shareable_file_choices_lists_adjacent_assigned(self):
        state = table_state()  # e1.mkv -> [1]; slots 1-4 exist
        service = EpisodeMappingService()
        choices = service.shareable_file_choices(state, season=1, episode=2)
        names = [name for _fid, name in choices]
        assert any("e1.mkv" in name for name in names)

    def test_shareable_file_choices_excludes_nonadjacent(self):
        state = table_state()
        service = EpisodeMappingService()
        choices = service.shareable_file_choices(state, season=1, episode=4)
        assert choices == []


from plex_renamer.engine.episode_assignments import (
    REASON_MANUAL_UNASSIGN,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _table_state(*, slots: int = 4, files: tuple[str, ...] = ("a.mkv", "b.mkv", "c.mkv")):
    """ScanState backed by a real assignment table; all files start unassigned."""
    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    file_ids: list[int] = []
    for name in files:
        entry = table.add_file(Path(f"C:/lib/Show/{name}"))
        table.mark_unassigned(entry.file_id, "no episode parsed")
        file_ids.append(entry.file_id)
    state = ScanState(
        folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"}
    )
    state.scanned = True
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state, file_ids


class BulkMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = EpisodeMappingService()

    def test_apply_assignments_batches_with_single_reproject(self):
        state, file_ids = _table_state()
        calls: list[int] = []
        original = EpisodeMappingService.reproject

        def counting(service_self, target):
            calls.append(1)
            return original(service_self, target)

        EpisodeMappingService.reproject = counting
        try:
            applied, skipped = self.service.apply_assignments(
                state,
                [(file_ids[0], 1, 2), (file_ids[1], 1, 3)],
            )
        finally:
            EpisodeMappingService.reproject = original
        self.assertEqual((applied, skipped), (2, 0))
        self.assertEqual(len(calls), 1)
        table = state.assignments
        self.assertEqual(table.assignment_for(file_ids[0]).episodes, (2,))
        self.assertEqual(table.assignment_for(file_ids[1]).episodes, (3,))

    def test_apply_assignments_skips_invalid_pairs(self):
        state, file_ids = _table_state()
        applied, skipped = self.service.apply_assignments(
            state,
            [(file_ids[0], 1, 1), (file_ids[1], 1, 99)],  # E99 has no slot
        )
        self.assertEqual((applied, skipped), (1, 1))
        self.assertIsNotNone(state.assignments.assignment_for(file_ids[0]))
        self.assertIsNone(state.assignments.assignment_for(file_ids[1]))

    def test_apply_assignments_empty_is_noop(self):
        state, _file_ids = _table_state()
        before = list(state.preview_items)
        self.assertEqual(self.service.apply_assignments(state, []), (0, 0))
        self.assertEqual(state.preview_items, before)  # no reproject ran

    def test_unassign_all_clears_every_assignment_once(self):
        state, file_ids = _table_state()
        self.service.apply_assignments(state, [(file_ids[0], 1, 1), (file_ids[1], 1, 2)])
        count = self.service.unassign_all(state)
        self.assertEqual(count, 2)
        table = state.assignments
        self.assertEqual(table.assignments(), [])
        self.assertEqual(table.unassigned_reasons[file_ids[0]], REASON_MANUAL_UNASSIGN)
        self.assertEqual(self.service.unassign_all(state), 0)  # idempotent no-op

    def test_slot_choices_carry_claimed_file_id(self):
        state = table_state()
        service = EpisodeMappingService()
        choices = service.episode_slot_choices(state)
        claimed = [c for c in choices if c.claimed_by]
        self.assertTrue(claimed)
        self.assertTrue(all(isinstance(c.claimed_file_id, int) for c in claimed))
        free = next(c for c in choices if (c.season, c.episode) == (1, 2))
        self.assertIsNone(free.claimed_file_id)

    def test_all_primary_file_previews_includes_assigned_and_unassigned(self):
        state, file_ids = _table_state()
        self.service.apply_assignments(state, [(file_ids[0], 1, 1)])
        previews = self.service.all_primary_file_previews(state)
        seen_ids = {p.file_id for p in previews}
        self.assertEqual(seen_ids, set(file_ids))

    def test_apply_bulk_unassigns_then_assigns(self):
        state, file_ids = _table_state()
        self.service.apply_assignments(state, [(file_ids[0], 1, 1)])
        table = state.assignments
        victim = file_ids[0]
        free_file = file_ids[1]
        applied, skipped = self.service.apply_bulk(
            state,
            assign_pairs=[(free_file, 1, 3)],
            unassign_file_ids=[victim],
        )
        self.assertEqual((applied, skipped), (1, 0))
        self.assertIsNone(table.assignment_for(victim))
        self.assertEqual(table.assignment_for(free_file).episodes, (3,))

    def test_apply_bulk_groups_multi_episode_file(self):
        state, file_ids = _table_state()
        free_file = file_ids[0]
        self.service.apply_bulk(
            state,
            assign_pairs=[(free_file, 1, 3), (free_file, 1, 4)],
            unassign_file_ids=[],
        )
        assignment = state.assignments.assignment_for(free_file)
        self.assertEqual(sorted(assignment.episodes), [3, 4])

    def test_apply_bulk_single_reproject_for_mixed_batch(self):
        state, file_ids = _table_state()
        self.service.apply_assignments(state, [(file_ids[0], 1, 1)])
        calls: list[int] = []
        original = EpisodeMappingService.reproject

        def counting(service_self, target):
            calls.append(1)
            return original(service_self, target)

        EpisodeMappingService.reproject = counting
        try:
            applied, skipped = self.service.apply_bulk(
                state,
                assign_pairs=[(file_ids[1], 1, 2), (file_ids[2], 1, 99)],
                unassign_file_ids=[file_ids[0]],
            )
        finally:
            EpisodeMappingService.reproject = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(applied, 1)
        self.assertIsNone(state.assignments.assignment_for(file_ids[0]))

    def test_apply_assignments_delegates_to_apply_bulk(self):
        state, file_ids = _table_state()
        applied, skipped = self.service.apply_assignments(
            state,
            [(file_ids[0], 1, 1)],
        )
        self.assertEqual((applied, skipped), (1, 0))
        self.assertEqual(state.assignments.assignment_for(file_ids[0]).episodes, (1,))


# ── Task 14: suggest_assignments (evidence-based auto-map) ──────────────


class SuggestAssignmentsTests(unittest.TestCase):
    """auto_map_remaining must follow scan-time parse evidence, never a
    positional zip: silent wrong mappings cost far more than leaving a file
    unstaged."""

    def _state_with_parsed_files(self, specs: dict[str, tuple[int | None, tuple[int, ...]]]):
        """Build a table-backed ScanState directly (no TMDB): each spec maps
        a filename to (season_hint, parsed_episodes)."""
        table = EpisodeAssignmentTable()
        # Fixed small season regardless of what specs ask for, so a spec'd
        # episode outside this range (e.g. E99) exercises the "no slot for
        # this evidence" skip path rather than growing the table to fit.
        for episode in range(1, 5):
            table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
        for name, (season_hint, episodes) in specs.items():
            entry = table.add_file(
                ROOT / name,
                parsed_episodes=tuple(episodes),
                season_hint=season_hint,
            )
            table.mark_unassigned(entry.file_id, "could not parse episode number")
        state = ScanState(folder=ROOT, media_info=SHOW)
        state.scanned = True
        state.assignments = table
        service = EpisodeMappingService()
        service.reproject(state)
        return state, service

    @staticmethod
    def _fid_by_name(table, name: str) -> int:
        return next(fid for fid, entry in table.files.items() if entry.path.name == name)

    def test_suggest_assignments_follows_parse_evidence(self):
        state, service = self._state_with_parsed_files(
            {
                "Show - S01E03.mkv": (1, (3,)),
                "Show - S01E01E02.mkv": (1, (1, 2)),
                "randomname.mkv": (None, ()),
            }
        )
        table = state.assignments
        file_ids = [fid for fid in table.files]
        pairs = service.suggest_assignments(state, file_ids, taken=set())
        by_file: dict[int, list[tuple[int, int]]] = {}
        for fid, season, episode in pairs:
            by_file.setdefault(fid, []).append((season, episode))
        parsed3 = self._fid_by_name(table, "Show - S01E03.mkv")
        multi = self._fid_by_name(table, "Show - S01E01E02.mkv")
        unparsed = self._fid_by_name(table, "randomname.mkv")
        self.assertEqual(by_file[parsed3], [(1, 3)])
        self.assertEqual(sorted(by_file[multi]), [(1, 1), (1, 2)])
        self.assertNotIn(unparsed, by_file)  # never positional-filled

    def test_suggest_assignments_skips_when_target_slot_missing(self):
        state, service = self._state_with_parsed_files(
            {
                "Show - S01E99.mkv": (1, (99,)),  # no S01E99 slot in the table
            }
        )
        table = state.assignments
        fid = self._fid_by_name(table, "Show - S01E99.mkv")
        pairs = service.suggest_assignments(state, [fid], taken=set())
        self.assertEqual(pairs, [])

    def test_suggest_assignments_skips_keys_already_in_taken(self):
        state, service = self._state_with_parsed_files(
            {
                "Show - S01E01.mkv": (1, (1,)),
            }
        )
        table = state.assignments
        fid = self._fid_by_name(table, "Show - S01E01.mkv")
        pairs = service.suggest_assignments(state, [fid], taken={(1, 1)})
        self.assertEqual(pairs, [])

    def test_suggest_assignments_does_not_double_claim_one_slot(self):
        state, service = self._state_with_parsed_files(
            {
                "Show - S01E01.mkv": (1, (1,)),
                "Show - S01E01 (dup).mkv": (1, (1,)),
            }
        )
        table = state.assignments
        file_ids = [fid for fid in table.files]
        pairs = service.suggest_assignments(state, file_ids, taken=set())
        self.assertEqual(len(pairs), 1)  # only the first-seen claims the slot

    def test_suggest_assignments_uses_taken_as_sole_source_not_claimed_slots(self):
        """Regression: the caller (panel) owns availability. A file that is
        already assigned in the table but whose slot the caller has marked
        available via `taken` (e.g. because the caller unassign-staged it)
        must be able to re-map onto its OWN parsed slot. If the service also
        consulted table.claimed_slots(), this would wrongly stay blocked,
        breaking the Unassign-all -> Auto-map-remaining round trip."""
        state, service = self._state_with_parsed_files(
            {
                "Show - S01E01.mkv": (1, (1,)),
            }
        )
        table = state.assignments
        fid = self._fid_by_name(table, "Show - S01E01.mkv")
        table.assign(fid, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        self.assertIn((1, 1), table.claimed_slots())  # table itself still shows it claimed
        pairs = service.suggest_assignments(state, [fid], taken=set())
        self.assertEqual(pairs, [(fid, 1, 1)])
