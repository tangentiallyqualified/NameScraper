"""RC36: number-only claims whose titles live in another season.

Rugrats' 'S08E18 - Murmur On The Ornery Express' auto-accepted at 0.88 on
number evidence while its title exactly matches unclaimed S09E27; the
'Happy Taffy & Imagine That' pack squatted on S08E16-17 while its segment
titles are S09E01 and S09E10 (non-contiguous), blocking the S7-pack rescues.
"""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_NUMBER_RELATIVE,
    CONF_TITLE_WINS_INEXACT,
    rescue_cross_season_segmented,
    rescue_cross_season_titles,
)
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def test_number_only_claim_with_exact_cross_season_title_moves():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=8, episode=18, title="The Great Unknown"))
    table.add_slot(
        EpisodeSlot(season=9, episode=27, title="Murmur on the Ornery Express")
    )
    entry = table.add_file(
        Path("Rugrats - S08E18 - Murmur On The Ornery Express.mkv"),
        parsed_episodes=(18,),
        raw_title="Murmur On The Ornery Express",
        is_season_relative=True,
        season_hint=8,
        folder_season=8,
    )
    table.assign(
        entry.file_id, 8, [18], origin="auto",
        confidence=CONF_NUMBER_RELATIVE,
        evidence=frozenset({"number", "season-relative"}),
    )

    rescue_cross_season_titles(table)

    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 9
    assert assignment.episodes == (27,)
    assert assignment.confidence == CONF_TITLE_WINS_INEXACT
    assert "cross-season-rescue" in assignment.evidence


def test_number_only_claim_with_agreeing_own_season_title_stays():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=8, episode=18, title="The Great Unknown"))
    table.add_slot(EpisodeSlot(season=9, episode=27, title="Something Else"))
    entry = table.add_file(
        Path("Rugrats - S08E18.mkv"),
        parsed_episodes=(18,),
        raw_title=None,
        is_season_relative=True,
        season_hint=8,
        folder_season=8,
    )
    table.assign(
        entry.file_id, 8, [18], origin="auto",
        confidence=CONF_NUMBER_RELATIVE,
        evidence=frozenset({"number", "season-relative"}),
    )

    rescue_cross_season_titles(table)

    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 8 and assignment.episodes == (18,)


def _rugrats_pack_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode, title in {
        16: "Falling Stars",
        17: "Dayscare",
        18: "The Great Unknown",
        19: "Cat Got Your Tongue?",
        20: "The War Room",
        21: "Attention Please",
    }.items():
        table.add_slot(EpisodeSlot(season=8, episode=episode, title=title))
    for episode, title in {
        1: "Happy Taffy",
        10: "Imagine That",
        21: "Back to School",
        22: "Sweet Dreams",
    }.items():
        table.add_slot(EpisodeSlot(season=9, episode=episode, title=title))
    return table


def test_non_contiguous_segment_titles_unassign_to_review():
    table = _rugrats_pack_table()
    entry = table.add_file(
        Path("Rugrats - S08E16-E17 - Happy Taffy & Imagine That.mkv"),
        parsed_episodes=(16, 17),
        raw_title="Happy Taffy & Imagine That",
        is_season_relative=True,
        season_hint=8,
        folder_season=8,
    )
    table.assign(
        entry.file_id, 8, [16, 17], origin="auto", confidence=0.70,
        evidence=frozenset({"number", "title-no-match", "title-multi-segment"}),
    )

    rescue_cross_season_segmented(table)

    assert table.assignment_for(entry.file_id) is None
    reason = table.unassigned_reasons[entry.file_id]
    assert "Season 9" in reason


def test_freed_slots_allow_contiguous_rescue_same_pass():
    table = _rugrats_pack_table()
    for episode in (14, 15, 16):
        table.add_slot(EpisodeSlot(season=7, episode=episode, title=""))
    squatter = table.add_file(
        Path("Rugrats - S08E19-E20 - Back To School & Sweet Dreams.mkv"),
        parsed_episodes=(19, 20),
        raw_title="Back To School & Sweet Dreams",
        is_season_relative=True,
        season_hint=8,
        folder_season=8,
    )
    pack = table.add_file(
        Path(
            "Rugrats - S07E14-E16 - Cat Got Your Tongue & The War Room"
            " & Attention Please.mkv"
        ),
        parsed_episodes=(14, 15, 16),
        raw_title="Cat Got Your Tongue & The War Room & Attention Please",
        is_season_relative=True,
        season_hint=7,
        folder_season=7,
    )
    table.assign(
        squatter.file_id, 8, [19, 20], origin="auto", confidence=0.70,
        evidence=frozenset({"number", "title-no-match", "title-multi-segment"}),
    )
    table.assign(
        pack.file_id, 7, [14, 15, 16], origin="auto", confidence=0.70,
        evidence=frozenset({"number", "title-no-match", "title-multi-segment"}),
    )

    rescue_cross_season_segmented(table)

    # 'Back To School & Sweet Dreams' = S09E21 + S09E22 (contiguous) -> moved
    squatter_assignment = table.assignment_for(squatter.file_id)
    assert squatter_assignment is not None
    assert squatter_assignment.season == 9
    assert squatter_assignment.episodes == (21, 22)
    # …which frees S08E19-20 so the S7 pack's contiguous S8 run can land.
    pack_assignment = table.assignment_for(pack.file_id)
    assert pack_assignment is not None
    assert pack_assignment.season == 8
    assert pack_assignment.episodes == (19, 20, 21)
