"""Regression tests for umbrella-folder season handling.

Bug: a multi-season umbrella folder named with a season RANGE
("Archer.2009.S01-S14", "Futurama Season 1-7 S01-S07") parsed as season 1,
so merging it with a same-show sibling collapsed it to `{1: ...\\Season 01}`
and dropped every other season's episodes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plex_renamer.engine._batch_tv_season_merge import (
    expanded_season_folders,
    merge_umbrella_siblings,
)
from plex_renamer.engine.models import ScanState
from plex_renamer.parsing import get_season


class TestGetSeasonRanges:
    @pytest.mark.parametrize(
        "name",
        [
            "Archer.2009.S01-S14.1080p.WEB.DD.AV1-DBMS",
            "Regular Show (2010) Season 1-8 S01-08 (1080p MiXED x265)",
            "MASH (1972) Season 01-11 S01-11 (1080p AMZN WEB-DL x265)",
            "Trailer.Park.Boys.2001.S01-S16.COMPLETE.x264-SURGE",
            "Buffy the Vampire Slayer (1997) S01-S07 (480p DVD x265)",
            "Rugrats (1991) Season 1-9 S01-09 (480p AMZN.WEBDL x265)",
        ],
    )
    def test_season_range_folders_have_no_single_season(self, name):
        assert get_season(Path(name)) is None

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Archer.2009.S09.1080p.AMZN.WEBRip", 9),
            ("The.Last.Of.Us.S01.ITA.ENG.2160p", 1),
            ("Ed, Edd n Eddy (1999) Season 6 S06 + Specials (1080p AI4K)", 6),
            ("Season 02", 2),
            ("S05", 5),
            ("Specials", 0),
        ],
    )
    def test_single_season_folders_still_parse(self, name, expected):
        assert get_season(Path(name)) == expected


def _umbrella_state(tmp_path: Path, seasons: list[int]) -> ScanState:
    root = tmp_path / "Show.S01-S03.Complete"
    for season in seasons:
        season_dir = root / f"Season {season:02d}"
        season_dir.mkdir(parents=True)
        (season_dir / f"Show S{season:02d}E01.mkv").touch()
    state = ScanState(
        folder=root,
        media_info={"id": 77, "name": "Show", "year": "2001"},
        confidence=1.5,
    )
    state.has_direct_season_subdirs = True
    return state


def _season_folder_state(tmp_path: Path, seasons: list[int]) -> ScanState:
    state = ScanState(
        folder=tmp_path / "Show.S08.1080p",
        media_info={"id": 77, "name": "Show", "year": "2001"},
        confidence=1.2,
    )
    state.season_folders = {season: tmp_path / f"Show.S{season:02d}.1080p" for season in seasons}
    for folder in state.season_folders.values():
        folder.mkdir(exist_ok=True)
    return state


class TestExpandedSeasonFolders:
    def test_umbrella_state_expands_direct_season_subdirs(self, tmp_path):
        state = _umbrella_state(tmp_path, [1, 2, 3])
        expanded = expanded_season_folders(state)
        assert set(expanded) == {1, 2, 3}


class TestUmbrellaAbsorbsSeasonFolderSiblings:
    def test_disjoint_multi_season_sibling_is_absorbed(self, tmp_path):
        umbrella = _umbrella_state(tmp_path, [1, 2, 3])
        sibling = _season_folder_state(tmp_path, [8, 9])
        merged = merge_umbrella_siblings([umbrella, sibling])
        assert merged == [umbrella]
        assert set(umbrella.season_folders) == {1, 2, 3, 8, 9}

    def test_overlapping_sibling_is_left_for_duplicate_labeling(self, tmp_path):
        umbrella = _umbrella_state(tmp_path, [1, 2, 3])
        sibling = _season_folder_state(tmp_path, [2])
        merged = merge_umbrella_siblings([umbrella, sibling])
        assert sibling in merged
        assert set(umbrella.season_folders) == {1, 2, 3}

    def test_same_numeric_id_different_provider_not_absorbed(self, tmp_path: Path) -> None:
        # Numeric IDs collide between TMDB and TVDB (Task 4 follow-up) — a
        # disjoint-season sibling from a different provider must never be
        # folded into the umbrella just because show_id matches by chance.
        umbrella = _umbrella_state(tmp_path, [1, 2, 3])
        sibling = _season_folder_state(tmp_path, [8, 9])
        sibling.provider_name = "tvdb"
        merged = merge_umbrella_siblings([umbrella, sibling])
        assert sibling in merged
        assert umbrella in merged
        assert umbrella.season_folders == {}
        assert set(sibling.season_folders) == {8, 9}
