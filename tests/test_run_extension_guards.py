"""RC30: run extension must not inflate single-episode files."""
from plex_renamer._parsing_names import MAX_FILENAME, _common_title_base
from plex_renamer.engine._episode_resolution import (
    CONF_AGREE,
    CONF_TITLE_WINS,
    CONF_TITLE_WINS_INEXACT,
    resolve_file,
)
from plex_renamer.parsing import extract_episode

TIGTONE_S1 = {
    1: "Tigtone and His Fellowship Of",
    2: "Tigtone and the Beautiful War",
    3: "Tigtone and the Wine Crisis",
    4: "Tigtone and Those Elemental Kings",
}


def test_exact_full_title_match_stays_single():
    resolution = resolve_file(
        parsed_episodes=(4,),
        raw_title="Tigtone and the Wine Crisis",
        is_season_relative=True,
        season_titles=TIGTONE_S1,
        season=1,
    )
    assert resolution.episodes == (3,)
    assert resolution.confidence == CONF_TITLE_WINS
    assert "run-extended" not in resolution.evidence


PPG_S0 = {
    9: "The Powerpuff Girls: Dance Pantsed",
    10: "Show & Tell - Blossom",
    11: "Show & Tell - Buttercup",
    12: "Show & Tell - Bubbles",
}


def test_show_and_tell_exact_match_stays_single():
    resolution = resolve_file(
        parsed_episodes=(9,),
        raw_title="Show & Tell - Blossom",
        is_season_relative=True,
        season_titles=PPG_S0,
        season=0,
    )
    assert resolution.episodes == (10,)
    assert "run-extended" not in resolution.evidence


RM_S1 = {
    3: "Anatomy Park",
    4: "M. Night Shaym-Aliens!",
    5: "Meeseeks and Destroy",
}


def test_underscore_junk_suffix_is_not_a_segment():
    eps, title, _rel = extract_episode("S01E04.M.Night.Shaym-Aliens!_new.mkv")
    assert eps == [4]
    assert title == "M Night Shaym-Aliens! new"


def test_underscore_between_dotted_titles_still_splits():
    _eps, title, _rel = extract_episode(
        "Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse.mkv"
    )
    assert title == "To The Moon & Bringin' Down The Mouse"


def test_rick_and_morty_dup_marker_resolves_single():
    eps, title, rel = extract_episode("S01E04.M.Night.Shaym-Aliens!_new.mkv")
    resolution = resolve_file(
        parsed_episodes=tuple(eps),
        raw_title=title,
        is_season_relative=rel,
        season_titles=RM_S1,
        season=1,
    )
    assert resolution.episodes == (4,)
    assert resolution.confidence == CONF_AGREE


def test_single_token_leftover_atom_blocks_extension():
    resolution = resolve_file(
        parsed_episodes=(4,),
        raw_title="M Night Shaym-Aliens! & new",
        is_season_relative=True,
        season_titles=RM_S1,
        season=1,
    )
    assert resolution.episodes == (4,)
    assert "run-extended" not in resolution.evidence


RUGRATS_S4 = {
    19: "Chuckie Is Rich",
    20: "The Unfair Pair",
    21: "Looking for Jack",
}


def test_mattress_case_still_extends():
    resolution = resolve_file(
        parsed_episodes=(21,),
        raw_title="The Mattress & Looking for Jack",
        is_season_relative=True,
        season_titles=RUGRATS_S4,
        season=4,
    )
    assert resolution.episodes == (20, 21)
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT
    assert "run-extended" in resolution.evidence


def test_dangling_conjunction_base_keeps_full_titles():
    # "Tigtone and the" is a fragment of the episode titles, not a shared
    # series name — no collapse, no truncation (user directive: episode
    # titles containing 'and' must survive intact).
    base = _common_title_base(
        ["Tigtone and the Beautiful War", "Tigtone and the Wine Crisis"]
    )
    assert base is None


def test_genuine_shared_base_still_collapses():
    base = _common_title_base(["Sozin's Comet - Part 1", "Sozin's Comet - Part 2"])
    assert base == "Sozin's Comet"


def test_base_with_interior_conjunction_kept():
    base = _common_title_base(["Rock and Roll Part 1", "Rock and Roll Part 2"])
    assert base == "Rock and Roll"


def test_single_episode_tigtone_keeps_full_title():
    from plex_renamer._parsing_names import build_tv_name

    name = build_tv_name(
        "Tigtone", "2019", 1, [3], ["Tigtone and the Wine Crisis"], ".mkv"
    )
    assert name == "Tigtone (2019) - S01E03 - Tigtone and the Wine Crisis.mkv"


def test_conjunction_prefix_run_keeps_both_full_titles():
    from plex_renamer._parsing_names import build_tv_name

    name = build_tv_name(
        "Tigtone", "2019", 1, [2, 3],
        ["Tigtone and the Beautiful War", "Tigtone and the Wine Crisis"],
        ".mkv",
    )
    assert "Tigtone and the Beautiful War" in name
    assert "Tigtone and the Wine Crisis" in name


def test_max_filename_is_170():
    assert MAX_FILENAME == 170
