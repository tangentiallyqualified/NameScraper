"""RC21: '_' between segment titles in dot-spaced names is a separator."""

from plex_renamer.engine._episode_resolution import CONF_TITLE_WINS_INEXACT, resolve_file
from plex_renamer.parsing import extract_episode


def test_underscore_becomes_segment_separator():
    eps, title, rel = extract_episode("Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse.mkv")
    assert eps == [1] and rel is True
    assert title == "To The Moon & Bringin' Down The Mouse"


def test_underscore_spaced_names_unaffected():
    eps, title, _ = extract_episode("Show_Name_S01E01_Some_Title.mkv")
    assert eps == [1]
    assert title == "Some Title"


def test_catscratch_file_resolves_to_run():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse", 3: "Unicorn Club", 4: "Go Gomez Go"}
    eps, title, rel = extract_episode("Catscratch.S01E02.Unicorn.Club_Go.Gomez.Go.mkv")
    resolution = resolve_file(
        parsed_episodes=tuple(eps),
        raw_title=title,
        is_season_relative=rel,
        season_titles=titles,
        season=1,
    )
    assert resolution.episodes == (3, 4)
