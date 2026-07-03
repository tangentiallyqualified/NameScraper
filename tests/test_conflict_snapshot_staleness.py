"""RC32: conflict auto-resolution must survive cascading unassignments.

Samurai Jack's scan died with "File 28 does not claim S03E06": resolving an
earlier slot unassigned a run-claim file that was the pre-computed winner of
a later slot, and the stale snapshot crashed the whole show scan.
"""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    _auto_resolve_strong_title_conflicts,
)
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _build_table() -> tuple[EpisodeAssignmentTable, int, int, int]:
    table = EpisodeAssignmentTable()
    for episode, title in {5: "Alpha", 6: "Beta", 7: "Gamma"}.items():
        table.add_slot(EpisodeSlot(season=3, episode=episode, title=title))
    exact = table.add_file(
        Path("a.mkv"), parsed_episodes=(5,), raw_title="Alpha",
        is_season_relative=True, season_hint=3, folder_season=3,
    )
    run = table.add_file(
        Path("b.mkv"), parsed_episodes=(5, 6), raw_title="Qq Ww Ee Rr",
        is_season_relative=True, season_hint=3, folder_season=3,
    )
    number = table.add_file(
        Path("c.mkv"), parsed_episodes=(6,), raw_title=None,
        is_season_relative=False, season_hint=None, folder_season=3,
    )
    table.assign(
        exact.file_id, 3, [5], origin="auto", confidence=0.92,
        evidence=frozenset({"title-strong"}),
    )
    table.assign(
        run.file_id, 3, [5, 6], origin="auto", confidence=0.70,
        evidence=frozenset({"title-strong-inexact", "run-extended"}),
    )
    table.assign(
        number.file_id, 3, [6], origin="auto", confidence=0.50,
        evidence=frozenset({"number"}),
    )
    return table, exact.file_id, run.file_id, number.file_id


def test_stale_winner_does_not_crash_resolution():
    table, exact_id, run_id, number_id = _build_table()

    _auto_resolve_strong_title_conflicts(table)  # must not raise

    exact_assignment = table.assignment_for(exact_id)
    assert exact_assignment is not None and exact_assignment.episodes == (5,)
    # The run claim lost slot 5 to the exact title and was unassigned; the
    # later slot-6 conflict must then resolve to the surviving claimant
    # instead of crashing on the stale winner.
    assert table.assignment_for(run_id) is None
    number_assignment = table.assignment_for(number_id)
    assert number_assignment is not None and number_assignment.episodes == (6,)
    assert not table.conflicts()
