"""RC35: lost-conflict files get exact-title cross-season rescues.

Ren & Stimpy's 'S02E11 - Son of Stimpy' lost its slot to the real S02E11
claimant and vanished, while unclaimed S03E05 is literally 'Son of Stimpy'.
"""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    rescue_cross_season_titles,
)
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
    lost_conflict_reason,
)


def _table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=2, episode=11, title="Monkey See, Monkey Don't"))
    table.add_slot(EpisodeSlot(season=3, episode=5, title="Son of Stimpy"))
    table.add_slot(EpisodeSlot(season=3, episode=6, title="Ren's Pecs"))
    return table


def test_lost_conflict_file_rescued_to_cross_season_exact_title():
    table = _table()
    winner = table.add_file(
        Path("The Ren & Stimpy Show - S02E12 - Monkey See...Monkey Don't.mkv"),
        parsed_episodes=(12,),
        raw_title="Monkey See...Monkey Don't",
        is_season_relative=True,
        season_hint=2,
        folder_season=2,
    )
    loser = table.add_file(
        Path("The Ren & Stimpy Show - S02E11 - Son of Stimpy.mkv"),
        parsed_episodes=(11,),
        raw_title="Son of Stimpy",
        is_season_relative=True,
        season_hint=2,
        folder_season=2,
    )
    table.assign(
        winner.file_id, 2, [11], origin="auto", confidence=0.92,
        evidence=frozenset({"title-strong", "number-disagree"}),
    )
    table.mark_unassigned(loser.file_id, lost_conflict_reason(2, 11))

    rescue_cross_season_titles(table)

    assignment = table.assignment_for(loser.file_id)
    assert assignment is not None
    assert assignment.season == 3
    assert assignment.episodes == (5,)
    assert assignment.confidence == CONF_TITLE_WINS_INEXACT
    assert "cross-season-rescue" in assignment.evidence


def test_lost_conflict_without_cross_season_title_stays_unassigned():
    table = _table()
    loser = table.add_file(
        Path("The Ren & Stimpy Show - S02E11 - Naked Beach Frenzy.mkv"),
        parsed_episodes=(11,),
        raw_title="Naked Beach Frenzy",
        is_season_relative=True,
        season_hint=2,
        folder_season=2,
    )
    table.mark_unassigned(loser.file_id, lost_conflict_reason(2, 11))

    rescue_cross_season_titles(table)

    assert table.assignment_for(loser.file_id) is None
