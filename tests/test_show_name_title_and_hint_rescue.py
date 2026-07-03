"""RC44: bare show-name titles must not claim slots; explicit hints rescue.

The consolidated phase-1 title pass ran before show-name stripping, so
'Futurama S09E01 Futurama.mkv' (leftover title 'Futurama') claimed
S06E13 'The Futurama Holiday Spectacular' over its own explicit S09E01,
lost the conflict to the real E13 file, and no rescue fell back to the
explicit hint slot.
"""
from pathlib import Path

from plex_renamer.engine._episode_resolution import rescue_explicit_hint_slots
from plex_renamer.engine._tv_scanner_consolidated import try_title_based_matching
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
    lost_conflict_reason,
)


def _entry(name, abs_num, raw_title, eps, rel, hint):
    return (Path(name), abs_num, raw_title, eps, rel, hint)


def _seasons(spec):
    return {
        season: {"count": len(titles), "titles": dict(titles), "posters": {}}
        for season, titles in spec.items()
    }


def test_bare_show_name_title_does_not_claim_cross_season():
    tmdb = _seasons({
        6: {13: "The Futurama Holiday Spectacular"},
        9: {1: "The One Amigo", 2: "Quids Game"},
    })
    files = [
        _entry("Futurama S09E01 Futurama.mkv", 1, "Futurama", [1], True, 9),
        _entry("Futurama S09E02 Quids Game.mkv", 2, "Quids Game", [2], True, 9),
    ]
    matches = try_title_based_matching(files, tmdb, show_name="Futurama")
    assert matches is not None
    assert matches[0] == (9, 1, "The One Amigo")


def test_lost_conflict_file_rescued_to_explicit_hint_slot():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=9, episode=1, title="The One Amigo"))
    table.add_slot(EpisodeSlot(season=6, episode=13, title="The Futurama Holiday Spectacular"))
    entry = table.add_file(
        Path("Futurama S09E01 Futurama.mkv"),
        parsed_episodes=(1,),
        raw_title=None,
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.mark_unassigned(entry.file_id, lost_conflict_reason(6, 13))

    rescue_explicit_hint_slots(table)

    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 9
    assert assignment.episodes == (1,)


def test_hint_rescue_leaves_claimed_slots_alone():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=9, episode=1, title="The One Amigo"))
    owner = table.add_file(
        Path("real-e01.mkv"),
        parsed_episodes=(1,),
        raw_title="The One Amigo",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.assign(
        owner.file_id, 9, [1], origin=ORIGIN_AUTO,
        confidence=0.96, evidence=frozenset({"number", "title-agree"}),
    )
    loser = table.add_file(
        Path("other-e01.mkv"),
        parsed_episodes=(1,),
        raw_title=None,
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.mark_unassigned(loser.file_id, lost_conflict_reason(9, 1))

    rescue_explicit_hint_slots(table)

    assert table.assignment_for(loser.file_id) is None
