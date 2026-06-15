"""Unit tests for the episode assignment table."""

from pathlib import Path

import pytest

from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    REASON_DISPLACED,
    REASON_LOST_CONFLICT,
    ROLE_PRIMARY,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def make_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode in range(1, 6):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    table.add_slot(EpisodeSlot(season=0, episode=1, title="Special A"))
    table.add_slot(EpisodeSlot(season=0, episode=2, title="Special B"))
    return table


class TestFileAndSlotRegistration:
    def test_add_file_assigns_sequential_ids(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        assert (a.file_id, b.file_id) == (0, 1)

    def test_new_file_is_unassigned_without_reason(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        assert table.assignment_for(entry.file_id) is None


class TestAssignValidation:
    def test_assign_single_episode(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        assignment = table.assign(
            entry.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=0.9,
        )
        assert assignment.episodes == (3,)
        assert assignment.role == ROLE_PRIMARY

    def test_assign_contiguous_run(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        assignment = table.assign(
            entry.file_id, 1, [1, 2, 3], origin=ORIGIN_MANUAL,
        )
        assert assignment.episodes == (1, 2, 3)
        assert assignment.confidence == 1.0

    def test_non_contiguous_rejected(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [1, 3], origin=ORIGIN_MANUAL)

    def test_unknown_slot_rejected(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [99], origin=ORIGIN_MANUAL)

    def test_unknown_file_rejected(self):
        table = make_table()
        with pytest.raises(ValueError):
            table.assign(42, 1, [1], origin=ORIGIN_MANUAL)

    def test_empty_episodes_rejected(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [], origin=ORIGIN_MANUAL)

    def test_failed_assign_leaves_table_unchanged(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.assign(entry.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [4, 6], origin=ORIGIN_MANUAL)
        existing = table.assignment_for(entry.file_id)
        assert existing is not None and existing.episodes == (2,)


class TestConflictsAndDisplacement:
    def test_auto_claims_accumulate_as_conflict(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
        assert (1, 2) in table.conflicts()
        assert {item.file_id for item in table.claims(1, 2)} == {a.file_id, b.file_id}
        assert table.claimant(1, 2) is None  # ambiguous while conflicted

    def test_manual_assign_displaces(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_MANUAL, displace=True)
        assert table.assignment_for(a.file_id) is None
        assert table.unassigned_reasons[a.file_id] == REASON_DISPLACED
        assert table.claimant(1, 2).file_id == b.file_id

    def test_resolve_conflict_keeps_winner(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
        table.resolve_conflict(1, 2, winner_file_id=a.file_id)
        assert table.conflicts() == {}
        assert table.claimant(1, 2).file_id == a.file_id
        assert table.unassigned_reasons[b.file_id].startswith(REASON_LOST_CONFLICT)

    def test_resolve_conflict_reason_names_the_lost_slot(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
        table.resolve_conflict(1, 2, winner_file_id=a.file_id)
        assert table.unassigned_reasons[b.file_id] == "lost conflict for S01E02"


class TestQueries:
    def test_unclaimed_slots(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.assign(entry.file_id, 1, [1, 2], origin=ORIGIN_AUTO, confidence=0.9)
        unclaimed = {slot.key for slot in table.unclaimed_slots()}
        assert unclaimed == {(1, 3), (1, 4), (1, 5), (0, 1), (0, 2)}

    def test_unassigned_files_with_reason(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.mark_unassigned(entry.file_id, "could not parse episode number")
        files = table.unassigned_files()
        assert files == [(entry, "could not parse episode number")]

    def test_unassign_clears_claims(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_MANUAL)
        table.unassign(entry.file_id, reason="manually unassigned")
        assert table.claimant(1, 1) is None
        assert table.assignment_for(entry.file_id) is None


class TestContractPins:
    def test_displacing_one_episode_unassigns_whole_multi_episode_holder(self):
        table = make_table()
        holder = table.add_file(Path("multi.mkv"))
        taker = table.add_file(Path("single.mkv"))
        table.assign(holder.file_id, 1, [1, 2, 3], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(taker.file_id, 1, [2], origin=ORIGIN_MANUAL, displace=True)
        assert table.assignment_for(holder.file_id) is None
        assert table.unassigned_reasons[holder.file_id] == REASON_DISPLACED
        assert table.claimant(1, 1) is None  # whole run released, not just E02
        assert table.claimant(1, 3) is None

    def test_set_approved_and_set_confidence_raise_for_unassigned_file(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.set_approved(entry.file_id)
        with pytest.raises(ValueError):
            table.set_confidence(entry.file_id, 0.5)

    def test_resolve_conflict_keeps_multi_episode_winner_intact(self):
        table = make_table()
        winner = table.add_file(Path("multi.mkv"))
        loser = table.add_file(Path("dupe.mkv"))
        table.assign(winner.file_id, 1, [2, 3], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(loser.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
        table.resolve_conflict(1, 2, winner_file_id=winner.file_id)
        kept = table.assignment_for(winner.file_id)
        assert kept is not None and kept.episodes == (2, 3)
        assert table.assignment_for(loser.file_id) is None
        assert table.conflicts() == {}


from plex_renamer.engine.episode_assignments import ingest_preview_items
from plex_renamer.engine.models import PreviewItem


class TestIngestion:
    def test_ingest_assigned_and_skipped_items(self):
        table = make_table()
        ok_item = PreviewItem(
            original=Path("a.mkv"), new_name="x.mkv", target_dir=Path("out"),
            season=1, episodes=[2], status="OK", episode_confidence=0.7,
        )
        skip_item = PreviewItem(
            original=Path("b.mkv"), new_name=None, target_dir=None,
            season=0, episodes=[], status="SKIP: could not match episode title to TMDB",
        )
        ingest_preview_items(table, [ok_item, skip_item])
        assert table.claimant(1, 2) is not None
        assert len(table.unassigned_files()) == 1
        assert ok_item.file_id is not None

    def test_ingest_strips_skip_prefix_so_projection_does_not_double_mint(self):
        """Consolidated-path items with 'SKIP: ...' status must not produce 'SKIP: SKIP: ...'."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import EpisodeSlot

        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Ep 1"))
        skip_item = PreviewItem(
            original=Path("episode.mkv"), new_name=None, target_dir=None,
            season=None, episodes=[], status="SKIP: could not match episode title to TMDB",
        )
        ingest_preview_items(table, [skip_item])
        items = project_preview_items(
            table,
            show_info={"id": 1, "name": "Test", "year": "2020"},
            root=Path("C:/lib/Test"),
            media_fields={"media_id": 1, "media_name": "Test"},
        )
        assert len(items) == 1
        assert not items[0].status.startswith("SKIP: SKIP:"), (
            f"Double-prefixed status: {items[0].status!r}"
        )
        assert items[0].status.startswith("SKIP")

    def test_ingest_duplicate_claims_conflict(self):
        table = make_table()
        items = [
            PreviewItem(
                original=Path(name), new_name="x.mkv", target_dir=Path("out"),
                season=1, episodes=[2], status="OK", episode_confidence=0.7,
            )
            for name in ("a.mkv", "b.mkv")
        ]
        ingest_preview_items(table, items)
        assert (1, 2) in table.conflicts()


from plex_renamer.engine.episode_assignments import merge_tables, ROLE_VERSION


class TestMergeTables:
    def test_merge_remaps_file_ids_and_detects_cross_state_conflicts(self):
        primary = make_table()
        sibling = make_table()
        a = primary.add_file(Path("s1/opening.mkv"), source_relative_folder="s1")
        b = sibling.add_file(Path("s2/opening.mkv"), source_relative_folder="s2")
        primary.assign(a.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        sibling.assign(b.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        merge_tables(primary, sibling)
        assert len(primary.files) == 2
        assert (0, 1) in primary.conflicts()

    def test_merge_keeps_unassigned_reasons(self):
        primary = make_table()
        sibling = make_table()
        entry = sibling.add_file(Path("x.mkv"))
        sibling.mark_unassigned(entry.file_id, "could not parse episode number")
        merge_tables(primary, sibling)
        assert len(primary.unassigned_files()) == 1

    def test_merge_preserves_role(self):
        """role=ROLE_VERSION must round-trip through merge_tables."""
        from dataclasses import replace as dc_replace
        primary = make_table()
        sibling = make_table()
        entry = sibling.add_file(Path("version.mkv"))
        sibling.assign(entry.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        # Manually set ROLE_VERSION on the assignment in the sibling table.
        sibling._assignments[entry.file_id] = dc_replace(
            sibling._assignments[entry.file_id], role=ROLE_VERSION,
        )
        id_map = merge_tables(primary, sibling)
        new_id = id_map[entry.file_id]
        merged_assignment = primary.assignment_for(new_id)
        assert merged_assignment is not None
        assert merged_assignment.role == ROLE_VERSION


class TestManualCarryOver:
    def test_manual_assignments_survive_rescan_of_same_show(self):
        from plex_renamer.engine.episode_assignments import (
            carry_over_manual_assignments,
        )
        old = make_table()
        entry_old = old.add_file(Path("lib/show/e1.mkv"))
        old.assign(entry_old.file_id, 1, [2], origin=ORIGIN_MANUAL)

        new = make_table()
        entry_new = new.add_file(Path("lib/show/e1.mkv"))
        new.assign(entry_new.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)

        carry_over_manual_assignments(old, new)
        restored = new.assignment_for(entry_new.file_id)
        assert restored.episodes == (2,)
        assert restored.origin == ORIGIN_MANUAL

    def test_manual_carry_over_skips_files_missing_from_new_scan(self):
        from plex_renamer.engine.episode_assignments import (
            carry_over_manual_assignments,
        )
        old = make_table()
        gone = old.add_file(Path("lib/show/deleted.mkv"))
        old.assign(gone.file_id, 1, [1], origin=ORIGIN_MANUAL)
        new = make_table()
        carry_over_manual_assignments(old, new)  # must not raise
        assert new.assignments() == []
