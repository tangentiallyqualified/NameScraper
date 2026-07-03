"""RC50: segment titles pinning non-adjacent SAME-season slots -> queue.

Rugrats S9's files pair segments by broadcast half-hour, but TMDB orders
the segments differently, so 'Bug Off & The Crawl Space' is E02 + E17.
Such a file cannot be a run anywhere in the season; its weak number claim
presented the wrong titles ('Diapies & Dragons-Lil's Phil of Trash'), or
its lost-conflict fallback hid the identification the cross-season path
already mints ("segment titles match Season N non-contiguously").
"""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_WEAK_TITLE_NUMBER_CAP,
    rescue_same_season_fuzzy_titles,
    unassign_same_season_scattered_titles,
)
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
    lost_conflict_reason,
)

RUGRATS_S9 = {
    2: "Bug Off",
    4: "Hold the Pickles",
    5: "Diapies & Dragons",
    6: "Lil's Phil of Trash",
    8: "Baby Power",
    9: "Bestest of Show",
    16: "Starstruck",
    17: "The Crawl Space",
    29: "They Came From The Backyard",
}

SCATTERED_REASON = "segment titles match Season 9 non-contiguously"


def _table_with_s9_slots() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode, title in RUGRATS_S9.items():
        table.add_slot(EpisodeSlot(season=9, episode=episode, title=title))
    return table


def test_weak_number_claim_unassigned_when_titles_scatter():
    table = _table_with_s9_slots()
    entry = table.add_file(
        Path("Rugrats - S09E05-E06 - Bug Off & The Crawl Space.mkv"),
        parsed_episodes=(5, 6),
        raw_title="Bug Off & The Crawl Space",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.assign(
        entry.file_id, 9, [5, 6], origin=ORIGIN_AUTO,
        confidence=CONF_WEAK_TITLE_NUMBER_CAP,
        evidence=frozenset({"number", "title-ambiguous", "title-multi-segment"}),
    )
    unassign_same_season_scattered_titles(table)
    assert table.assignment_for(entry.file_id) is None
    assert table.unassigned_reasons[entry.file_id] == SCATTERED_REASON


def test_lost_conflict_scattered_file_gets_informative_reason():
    table = _table_with_s9_slots()
    entry = table.add_file(
        Path("Rugrats - S09E20-E21 - Bestest of Show & Hold The Pickles.mkv"),
        parsed_episodes=(20, 21),
        raw_title="Bestest of Show & Hold The Pickles",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.mark_unassigned(entry.file_id, lost_conflict_reason(9, 20))
    unassign_same_season_scattered_titles(table)
    assert table.unassigned_reasons[entry.file_id] == SCATTERED_REASON


def test_separator_inside_title_matches_through_merged_atoms():
    # 'Diapies and Dragons' splits at 'and' but still names E05
    # 'Diapies & Dragons' ('&' folds to 'and' in normalization).
    table = _table_with_s9_slots()
    entry = table.add_file(
        Path("Rugrats - S09E14-E15 - Diapies and Dragons & Baby Power.mkv"),
        parsed_episodes=(14, 15),
        raw_title="Diapies and Dragons & Baby Power",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.mark_unassigned(entry.file_id, lost_conflict_reason(9, 14))
    unassign_same_season_scattered_titles(table)
    assert table.unassigned_reasons[entry.file_id] == SCATTERED_REASON


def test_contiguous_title_matches_left_alone():
    # Adjacent slots are a real run other passes may still place; only
    # scattered matches are queue-locked.
    table = EpisodeAssignmentTable()
    for episode, title in {
        47: "Davy Omelette",
        48: "Hearts of Twilight",
        49: "The Boids",
    }.items():
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
    entry = table.add_file(
        Path("Animaniacs - S01E20 - Hitchcock Opening, Hearts of Twilight & The Boids.mkv"),
        parsed_episodes=(20,),
        raw_title="Hitchcock Opening, Hearts of Twilight & The Boids",
        is_season_relative=True,
        season_hint=1,
        folder_season=1,
    )
    reason = lost_conflict_reason(1, 20)
    table.mark_unassigned(entry.file_id, reason)
    unassign_same_season_scattered_titles(table)
    assert table.unassigned_reasons[entry.file_id] == reason


def test_scattered_file_excluded_from_single_slot_fuzzy_rescue():
    # With E06 claimed by another file, the fuzzy rescue would half-claim
    # E29 for a two-segment file; the scattered reason must lock it out.
    table = _table_with_s9_slots()
    holder = table.add_file(
        Path("Rugrats - S09E06 - Holder.mkv"),
        parsed_episodes=(6,),
        raw_title="Lil's Phil of Trash",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.assign(
        holder.file_id, 9, [6], origin=ORIGIN_AUTO,
        confidence=0.92,
        evidence=frozenset({"number", "title-agree"}),
    )
    entry = table.add_file(
        Path("Rugrats - S09E18-E19 - They Came From The Backyard & Lil's Phil of Trash.mkv"),
        parsed_episodes=(18, 19),
        raw_title="They Came From The Backyard & Lil's Phil of Trash",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    table.mark_unassigned(entry.file_id, lost_conflict_reason(9, 18))
    unassign_same_season_scattered_titles(table)
    rescue_same_season_fuzzy_titles(table)
    assert table.assignment_for(entry.file_id) is None
    assert table.unassigned_reasons[entry.file_id] == SCATTERED_REASON
