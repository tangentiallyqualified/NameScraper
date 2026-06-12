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
        assert table.unassigned_reasons[b.file_id] == REASON_LOST_CONFLICT


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
