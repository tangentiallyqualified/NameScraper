from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._episode_resolution import CONF_SPECIAL_NUMBER_ONLY
from plex_renamer.engine._tv_scanner_consolidated import build_consolidated_table

SHOW = {"id": 7, "name": "Demo Show", "year": "2020"}


class _NoTmdb:
    """Season 0 is provided inline; get_season must not be called."""

    def get_season(self, show_id, season_num):  # pragma: no cover - guard
        raise AssertionError("Season 0 already supplied in tmdb_seasons")


def _seasons():
    return {
        0: {
            "titles": {8: "How to Draw Eddy", 12: "The Grim Adventures of the KND"},
            "posters": {}, "episodes": {}, "count": 12,
        },
        1: {
            "titles": {1: "Pilot", 2: "The Heist"},
            "posters": {}, "episodes": {}, "count": 2,
        },
    }


def _build(tmp_path, filenames):
    root = tmp_path / "Demo Show"
    root.mkdir()
    for name in filenames:
        (root / name).write_text("x")
    return build_consolidated_table(
        season_dirs=[(root, 1)],
        tmdb_seasons=_seasons(),
        tmdb=_NoTmdb(),
        show_info=SHOW,
        root=root,
        store_tmdb_data=lambda *a, **k: None,
    )


def test_registers_season_zero_slots(tmp_path):
    table = _build(tmp_path, ["Demo Show - S01E01 - Pilot.mkv"])
    assert (0, 8) in table.slots
    assert (0, 12) in table.slots


def test_special_maps_by_title_not_number(tmp_path):
    table = _build(
        tmp_path,
        ["Demo Show - S00E08 - The Grim Adventures of the KND.mkv"],
    )
    claimant = table.claimant(0, 12)
    assert claimant is not None
    assert claimant.path.name.startswith("Demo Show - S00E08")
    assert table.claimant(0, 8) is None  # not the bare-number slot


def test_special_number_only_lands_in_review(tmp_path):
    table = _build(tmp_path, ["Demo Show - S00E08 - Mystery Clip.mkv"])
    assignment = table.claims(0, 8)
    assert assignment, "expected the special to map by number"
    assert assignment[0].confidence == CONF_SPECIAL_NUMBER_ONLY


def test_multi_episode_run_maps_to_all_episodes(tmp_path):
    # Season-relative multi-episode files (S01E01-E02) must claim the whole run
    # in the consolidated path, not collapse to the first episode.
    table = _build(tmp_path, ["Demo Show - S01E01-E02 - Pilot & The Heist.mkv"])

    first = table.claimant(1, 1)
    second = table.claimant(1, 2)
    assert first is not None and second is not None
    assert first is second, "both episodes must be claimed by the same file"
    assert table.assignment_for(first.file_id).episodes == (1, 2)
