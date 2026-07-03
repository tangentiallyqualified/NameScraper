"""RC45: chained title-no-match squatters must unwind, not block each other.

Rugrats: 'Back To School & Sweet Dreams' (really S09E21-22) squats on
S08E19-20, which blocks 'Cat Got Your Tongue & The War Room & Attention
Please' (an exact contiguous run at S08E19-21) from leaving S07E14-16.
The single rescue pass processed the blocked file first and gave up.
"""
from pathlib import Path

from plex_renamer.engine._episode_resolution import rescue_cross_season_segmented
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)

SQUATTER_EVIDENCE = frozenset({"number", "title-no-match", "title-multi-segment"})


def _build_table() -> tuple[EpisodeAssignmentTable, int, int]:
    table = EpisodeAssignmentTable()
    for season, episode, title in [
        (7, 14, "Doctor Susie"),
        (7, 15, "Accidents Happen"),
        (7, 16, "Pee Wee Scouts"),
        (8, 19, "Cat Got Your Tongue?"),
        (8, 20, "The War Room"),
        (8, 21, "Attention Please"),
        (9, 21, "Back to School"),
        (9, 22, "Sweet Dreams"),
    ]:
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))

    # Added (and therefore iterated) BEFORE its blocker, like the real scan.
    cat_got = table.add_file(
        Path("Rugrats - S07E14-E16 - Cat Got Your Tongue & The War Room & Attention Please.mkv"),
        parsed_episodes=(14, 15, 16),
        raw_title="Cat Got Your Tongue & The War Room & Attention Please",
        is_season_relative=True,
        season_hint=7,
        folder_season=7,
    )
    table.assign(
        cat_got.file_id, 7, [14, 15, 16], origin=ORIGIN_AUTO,
        confidence=0.7, evidence=SQUATTER_EVIDENCE,
    )
    back_to_school = table.add_file(
        Path("Rugrats - S08E19-E20 - Back To School & Sweet Dreams.mkv"),
        parsed_episodes=(19, 20),
        raw_title="Back To School & Sweet Dreams",
        is_season_relative=True,
        season_hint=8,
        folder_season=8,
    )
    table.assign(
        back_to_school.file_id, 8, [19, 20], origin=ORIGIN_AUTO,
        confidence=0.7, evidence=SQUATTER_EVIDENCE,
    )
    return table, cat_got.file_id, back_to_school.file_id


def test_squatter_chain_unwinds():
    table, cat_got_id, back_to_school_id = _build_table()

    rescue_cross_season_segmented(table)

    bts = table.assignment_for(back_to_school_id)
    assert bts is not None
    assert (bts.season, bts.episodes) == (9, (21, 22))

    cat = table.assignment_for(cat_got_id)
    assert cat is not None
    assert (cat.season, cat.episodes) == (8, (19, 20, 21))
