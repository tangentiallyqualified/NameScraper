"""RC18a/b/d: two-phase consolidated title matching."""
from pathlib import Path

from plex_renamer.engine._tv_scanner_consolidated import try_title_based_matching


def _entry(name, abs_num, raw_title, eps, rel, hint):
    return (Path(name), abs_num, raw_title, eps, rel, hint)


def _seasons(spec):
    # spec: {season: {episode: title}}
    return {
        season: {"count": len(titles), "titles": dict(titles), "posters": {}}
        for season, titles in spec.items()
    }


def test_title_claims_beat_number_squatters():
    tmdb = _seasons({3: {1: "New Neighbors", 2: "Dummy Dummy"}})
    files = [
        # mis-filed file whose (hint, number) exists -> must NOT keep the slot
        _entry("S03 E01 - Sumo Enchanted Evening.mkv", 1, "Sumo Enchanted Evening", [1], True, 3),
        # genuinely titled file for the same slot
        _entry("S03 E27 - New Neighbors.mkv", 27, "New Neighbors", [27], True, 3),
    ]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None
    assert matches[1] == (3, 1, "New Neighbors")


def test_short_titles_participate():
    tmdb = _seasons({1: {1: "Cog", 2: "Passion", 3: "Longer Title Here"}})
    files = [
        _entry("a.mkv", 1, "Cog", [1], True, 1),
        _entry("b.mkv", 2, "Passion", [2], True, 1),
    ]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None
    assert matches[0] == (1, 1, "Cog")
    assert matches[1] == (1, 2, "Passion")


def test_s0_titles_available_for_hint_missing_seasons():
    tmdb = _seasons({
        1: {1: "The Pilot", 2: "Fireworks"},
        0: {46: "Space Force", 47: "Weekend at Bernie"},
    })
    files = [
        _entry("S07E01 - Space Force.mkv", 1, "Space Force", [1], True, 7),
        _entry("S01E01 - The Pilot.mkv", 1, "The Pilot", [1], True, 1),
    ]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None
    assert matches[0] == (0, 46, "Space Force")
    assert matches[1] == (1, 1, "The Pilot")


def test_regular_season_shadows_s0_duplicate_title():
    tmdb = _seasons({
        1: {1: "The Pilot"},
        0: {1: "The Pilot"},
    })
    files = [_entry("x.mkv", 1, "The Pilot", [1], True, 1)]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None and matches[0][0] == 1
