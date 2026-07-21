"""Scan-time part-set detection (spec section 1 grouping rules)."""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._episode_resolution import detect_part_groups
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ROLE_PART,
    ROLE_PRIMARY,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=5, title="Five"))
    return table


def _add_claimant(table: EpisodeAssignmentTable, name: str, *, folder: str = "Season 01") -> int:
    entry = table.add_file(Path(folder) / name, parsed_episodes=(5,), source_relative_folder=folder)
    table.assign(entry.file_id, 1, [5], origin=ORIGIN_AUTO, confidence=0.9)
    return entry.file_id


def test_complete_run_groups_in_marker_order() -> None:
    table = _table()
    # Registration order deliberately scrambled; marker order must win.
    id2 = _add_claimant(table, "Show S01E05 (2).mkv")
    id1 = _add_claimant(table, "Show S01E05 (1).mkv")
    id3 = _add_claimant(table, "Show S01E05 (3).mkv")
    detect_part_groups(table)

    assignment1 = table.assignment_for(id1)
    assignment2 = table.assignment_for(id2)
    assignment3 = table.assignment_for(id3)
    assert assignment1 is not None
    assert assignment2 is not None
    assert assignment3 is not None

    assert assignment1.role == ROLE_PRIMARY and assignment1.part_order == 1
    assert assignment2.role == ROLE_PART and assignment2.part_order == 2
    assert assignment3.role == ROLE_PART and assignment3.part_order == 3
    assert table.conflicts() == {}
    assert table.files[id1].part_marker == 1
    # Group confidence: min of member confidences.
    assert assignment1.confidence == 0.9


def test_incomplete_run_does_not_group() -> None:
    table = _table()
    _add_claimant(table, "Show S01E05 (1).mkv")
    _add_claimant(table, "Show S01E05 (3).mkv")
    detect_part_groups(table)
    assert (1, 5) in table.conflicts()  # untouched -> normal conflict flow


def test_unmarked_sibling_blocks_grouping() -> None:
    """file.mkv + file (1).mkv is a Windows duplicate download."""
    table = _table()
    _add_claimant(table, "Show S01E05.mkv")
    _add_claimant(table, "Show S01E05 (1).mkv")
    _add_claimant(table, "Show S01E05 (2).mkv")
    detect_part_groups(table)
    assert all(a.part_order == 0 for a in table.assignments())


def test_cross_directory_files_do_not_group() -> None:
    table = _table()
    _add_claimant(table, "Show S01E05 (1).mkv", folder="Season 01")
    _add_claimant(table, "Show S01E05 (2).mkv", folder="extras")
    detect_part_groups(table)
    assert all(a.part_order == 0 for a in table.assignments())


def test_different_slots_do_not_group() -> None:
    table = _table()
    table.add_slot(EpisodeSlot(season=1, episode=6, title="Six"))
    a = table.add_file(Path("Season 01") / "Show S01E05 (1).mkv", parsed_episodes=(5,))
    b = table.add_file(Path("Season 01") / "Show S01E05 (2).mkv", parsed_episodes=(5,))
    table.assign(a.file_id, 1, [5], origin=ORIGIN_AUTO)
    table.assign(b.file_id, 1, [6], origin=ORIGIN_AUTO)  # manually diverged
    detect_part_groups(table)
    assert all(x.part_order == 0 for x in table.assignments())


def test_detection_runs_inside_conflict_resolution_before_pileup() -> None:
    from plex_renamer.engine._episode_resolution import resolve_table_conflicts

    table = _table()
    ids = [_add_claimant(table, f"Show S01E05 ({index}).mkv") for index in (1, 2, 3)]
    resolve_table_conflicts(table)
    # Without detection the 3+ pile-up rule would unassign all three.
    assert all(table.assignment_for(i) is not None for i in ids)

    first_assignment = table.assignment_for(ids[0])
    assert first_assignment is not None
    assert first_assignment.role == ROLE_PRIMARY
