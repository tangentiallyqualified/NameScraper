"""RC34: explicit S00E## labels with no contradicting title are trusted.

The IT Crowd's 'S00E01.mkv' in a 'season 0' folder parked at 0.50 review —
and the stem-title fallback minted the useless raw_title 'S00E01'.
"""

from plex_renamer.engine._episode_resolution import (
    CONF_NUMBER_RELATIVE,
    CONF_SPECIAL_NUMBER_ONLY,
    resolve_file,
)
from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
)

IT_CROWD_S0 = {1: "The Internet Is Coming", 2: "The IT Crowd Manual"}


def test_explicit_s00_number_with_no_title_auto_accepts():
    resolution = resolve_file(
        parsed_episodes=(1,),
        raw_title=None,
        is_season_relative=True,
        season_titles=IT_CROWD_S0,
        season=0,
        season_hint=0,
    )
    assert resolution.episodes == (1,)
    assert resolution.confidence == CONF_NUMBER_RELATIVE


def test_explicit_s00_number_with_foreign_title_stays_review():
    resolution = resolve_file(
        parsed_episodes=(5,),
        raw_title="Stimpy's Pregnant",
        is_season_relative=True,
        season_titles={5: "Sven Hoek Pencil Test", 6: "In the Beginning"},
        season=0,
        season_hint=0,
    )
    assert resolution.episodes == (5,)
    assert resolution.confidence == CONF_SPECIAL_NUMBER_ONLY


def test_inferred_special_number_stays_review():
    resolution = resolve_file(
        parsed_episodes=(1,),
        raw_title=None,
        is_season_relative=False,
        season_titles=IT_CROWD_S0,
        season=0,
        season_hint=None,
    )
    assert resolution.confidence == CONF_SPECIAL_NUMBER_ONLY


def test_stem_fallback_not_minted_for_bare_episode_marker(tmp_path):
    table = EpisodeAssignmentTable()
    for episode, title in IT_CROWD_S0.items():
        table.add_slot(EpisodeSlot(season=0, episode=episode, title=title))
    file_path = tmp_path / "S00E01.mkv"
    file_path.write_bytes(b"")

    _resolve_into_table(
        table,
        file_path=file_path,
        season_num=0,
        season_titles=IT_CROWD_S0,
        show_name="The IT Crowd",
    )

    entry = next(iter(table.files.values()))
    assert entry.raw_title is None
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 0 and assignment.episodes == (1,)
    assert assignment.confidence == CONF_NUMBER_RELATIVE
