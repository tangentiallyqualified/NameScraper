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


from plex_renamer.engine._tv_scanner_consolidated import build_consolidated_table


class _NoTmdb:
    """Season 0 supplied inline; get_season must not be called."""

    def get_season(self, show_id, season_num):  # pragma: no cover - guard
        raise AssertionError("Season 0 already supplied in tmdb_seasons")


def test_hint_missing_files_are_not_sequence_mapped(tmp_path):
    (tmp_path / "Season 7").mkdir()
    (tmp_path / "Season 1").mkdir()
    s7 = tmp_path / "Season 7" / "Reno - S07E01 - Unknown Title.mkv"
    s1 = tmp_path / "Season 1" / "Reno - S01E05 - Nonmatching Name.mkv"
    s7.touch()
    s1.touch()
    tmdb = _seasons({1: {1: "The Investigation", 2: "Fireworks"}, 0: {}})
    table = build_consolidated_table(
        season_dirs=[(tmp_path / "Season 1", 1), (tmp_path / "Season 7", 7)],
        tmdb_seasons=tmdb,
        tmdb=_NoTmdb(),
        show_info={"id": 1, "name": "Reno 911!", "year": "2003"},
        root=tmp_path,
        store_tmdb_data=lambda *args: None,
    )
    s7_entry = next(e for e in table.files.values() if e.path == s7)
    # S7 doesn't exist on TMDB: the file must NOT be sequence-mapped into S1.
    assert table.assignment_for(s7_entry.file_id) is None


def test_leftover_files_re_resolved_against_hinted_season(tmp_path):
    (tmp_path / "Season 3").mkdir()
    # Both segment titles carry a typo so the cross-season title pass cannot
    # whole-match them; only the hinted-season seg-run (fuzzy) can.
    f = (
        tmp_path / "Season 3"
        / "CatDog - S03 E27-E28 - Monster Truk Folly and CatDogs Golf.mkv"
    )
    anchor = tmp_path / "Season 3" / "CatDog - S03 E29 - Filler 5.mkv"
    f.touch()
    anchor.touch()
    tmdb = _seasons({
        3: {1: "Monster Truck Folly", 2: "CatDog's Gold"},
        # a big season so the anchor keeps the title pass alive at 50%:
        1: {n: f"Filler {n}" for n in range(1, 30)},
        0: {},
    })
    table = build_consolidated_table(
        season_dirs=[(tmp_path / "Season 3", 3)],
        tmdb_seasons=tmdb,
        tmdb=_NoTmdb(),
        show_info={"id": 1, "name": "CatDog", "year": "1998"},
        root=tmp_path,
        store_tmdb_data=lambda *args: None,
    )
    entry = next(e for e in table.files.values() if e.path == f)
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 3
    assert assignment.episodes == (1, 2)
