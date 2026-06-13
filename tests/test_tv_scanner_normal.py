"""Tests for _resolve_into_table in the normal TV scanner."""

from pathlib import Path

import pytest

from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot
from plex_renamer.parsing import extract_episode


def make_season1_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for ep in range(1, 6):
        table.add_slot(EpisodeSlot(season=1, episode=ep, title=f"Ep {ep}"))
    return table


SEASON_TITLES = {1: "Ep 1", 2: "Ep 2", 3: "Ep 3", 4: "Ep 4", 5: "Ep 5"}


def test_extract_episode_noncontiguous_yields_3_and_5():
    """Verify the parse that triggers the bug produces [3, 5]."""
    episodes, _, is_season_relative = extract_episode("Show S01E03E05.mkv")
    assert episodes == [3, 5]
    assert is_season_relative is True


def test_resolve_into_table_contiguous_file_is_assigned():
    table = make_season1_table()
    _resolve_into_table(
        table,
        file_path=Path("Show S01E01.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,
    )
    assigned = [fid for fid in table.files if table.assignment_for(fid) is not None]
    assert len(assigned) == 1


def test_resolve_into_table_noncontiguous_file_does_not_raise():
    """A non-contiguous multi-episode file must not raise — it must be marked unassigned."""
    table = make_season1_table()
    # Assign a good file first so we can confirm it is not disturbed.
    _resolve_into_table(
        table,
        file_path=Path("Show S01E01.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,
    )
    # This should NOT raise ValueError even though [3, 5] is non-contiguous.
    _resolve_into_table(
        table,
        file_path=Path("Show S01E03E05.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,
    )

    # E01 file must still be assigned.
    e01_entry = next(e for e in table.files.values() if e.path.name == "Show S01E01.mkv")
    assert table.assignment_for(e01_entry.file_id) is not None

    # E03E05 file must be unassigned (in unassigned_files).
    bad_entry = next(e for e in table.files.values() if e.path.name == "Show S01E03E05.mkv")
    assert table.assignment_for(bad_entry.file_id) is None
    unassigned_ids = {entry.file_id for entry, _ in table.unassigned_files()}
    assert bad_entry.file_id in unassigned_ids
