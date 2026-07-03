"""RC24(b)/RC25/RC26/RC23: specials-path guards."""
from pathlib import Path

from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot


def _table_with(season, titles, s0_titles=None):
    table = EpisodeAssignmentTable()
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))
    for episode, title in (s0_titles or {}).items():
        table.add_slot(EpisodeSlot(season=0, episode=episode, title=title))
    return table


def test_valid_own_season_episode_not_pulled_to_specials(tmp_path):
    season_titles = {9: "The Satan Pit", 10: "Love & Monsters", 11: "Fear Her"}
    s0_titles = {28: "Tardisode 10: Love And Monsters"}
    table = _table_with(2, season_titles, s0_titles)
    file_path = tmp_path / "Doctor Who - S02E10 - Love and Monsters.mkv"
    file_path.touch()
    _resolve_into_table(
        table,
        file_path=file_path,
        season_num=2,
        season_titles=season_titles,
        specials_titles=s0_titles,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 2
    assert assignment.episodes == (10,)


def test_inexact_s0_match_never_overrides_valid_explicit_own_number(tmp_path):
    # Own season titles match NOTHING (own_match is None) but the explicit
    # S02E10 is valid; an S0 SUBSTRING hit (inexact) must not pull the file
    # to specials.
    season_titles = {9: "The Satan Pit", 10: "Fear Her", 11: "Army of Ghosts"}
    s0_titles = {28: "Tardisode 10: Love And Monsters"}
    table = _table_with(2, season_titles, s0_titles)
    file_path = tmp_path / "Doctor Who - S02E10 - Love and Monsters.mkv"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=2,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 2
    assert assignment.episodes == (10,)


def test_exact_s0_title_still_loses_to_valid_own_number_with_own_match(tmp_path):
    season_titles = {9: "The Satan Pit", 10: "Love & Monsters", 11: "Fear Her"}
    s0_titles = {28: "Love and Monsters"}
    table = _table_with(2, season_titles, s0_titles)
    file_path = tmp_path / "Doctor Who - S02E10 - Love and Monsters.mkv"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=2,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment.season == 2 and assignment.episodes == (10,)


def test_prequel_with_parent_number_does_not_claim_s0_number(tmp_path):
    s0_titles = {
        13: "Planet of the Dead",
        85: "She Said, He Said (The Name of the Doctor Prequel)",
        86: "Clarence and the Whispermen (The Name of the Doctor Prequel)",
    }
    table = _table_with(0, {}, s0_titles)
    file_path = (
        tmp_path
        / "Prequel - S07E13 - The Name of the Doctor - Clarence and the Whispermen.mkv"
    )
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=0,
        season_titles=s0_titles, from_extras_folder=True,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 0
    assert assignment.episodes == (86,)


def test_root_file_with_no_parse_matches_special_by_stem(tmp_path):
    season_titles = {1: "Your Real Best Friend!", 2: "Why June?"}
    s0_titles = {2: "The Henry & June Show", 3: "An Off-Beats Valentine's"}
    table = _table_with(1, season_titles, s0_titles)
    file_path = tmp_path / "The Henry & June Show (1999).mp4"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=1,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="KaBlam!",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 0 and assignment.episodes == (2,)


def test_offbeats_valentines_stem_substring(tmp_path):
    season_titles = {1: "Your Real Best Friend!"}
    s0_titles = {2: "The Henry & June Show", 3: "An Off-Beats Valentine's"}
    table = _table_with(1, season_titles, s0_titles)
    file_path = tmp_path / "The Off-Beats Valentine's Special (1998).mp4"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=1,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="KaBlam!",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 0 and assignment.episodes == (3,)
