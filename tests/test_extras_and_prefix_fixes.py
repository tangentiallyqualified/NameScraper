"""Regression tests for extras handling and punctuation-hostile prefix checks.

Covers three reproduced bugs:
- M*A*S*H / Hell's Paradise / Frieren: `_source_prefix_compatible` failed on
  punctuation ("M*A*S*H" -> "m a s h" vs "MASH" -> "mash"), capping perfect
  title-agree assignments at 0.45.
- Gundam 0083: `get_season("Extras") == 0` made `resolve_tv_season_dirs`
  return only the Extras dir, dropping the 13 root episode files.
- TNG / Gundam NCOP-NCED: extras-folder files claimed numbered S0 slots from
  bare numbers ("Season 2 Extra 1" parses 2), producing mass conflicts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plex_renamer.engine._episode_resolution import _source_prefix_compatible
from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine._tv_scanner_seasons import resolve_tv_season_dirs
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot
from plex_renamer.parsing import get_season, normalize_for_match


class TestPrefixCompatibility:
    @pytest.mark.parametrize(
        "source,show",
        [
            ("MASH", "M*A*S*H"),
            ("Hells Paradise", "Hell's Paradise"),
            ("Frieren Beyond Journeys End", "Frieren: Beyond Journey's End"),
            ("Star Trek TNG", "Star Trek: The Next Generation"),
        ],
    )
    def test_punctuation_and_acronym_variants_are_compatible(self, source, show):
        assert _source_prefix_compatible(
            normalize_for_match(source),
            normalize_for_match(show),
        )

    @pytest.mark.parametrize(
        "source,show",
        [
            ("Andromeda", "Andor"),
            ("Watchmen Motion Comic", "Watchmen"),  # prefix containment, was already True
        ],
    )
    def test_containment_still_behaves(self, source, show):
        # Andromeda/Andor must stay contradictory; containment stays compatible.
        expected = source.lower().startswith(show.lower())
        assert (
            _source_prefix_compatible(
                normalize_for_match(source),
                normalize_for_match(show),
            )
            is expected
        )


class TestRootEpisodesWithExtrasSubdir:
    def test_root_files_kept_when_only_specials_subdirs_found(self, tmp_path):
        root = tmp_path / "[Group] Gundam 0083 (BD)"
        extras = root / "Extras"
        extras.mkdir(parents=True)
        (root / "[Group] Gundam - 01 - Gundamjack.mkv").touch()
        (root / "[Group] Gundam - 02 - Endless Pursuit.mkv").touch()
        (extras / "[Group] Gundam - NCOP1.mkv").touch()

        season_dirs = resolve_tv_season_dirs(
            root,
            season_hint=None,
            season_folders=None,
            get_season=get_season,
            match_dirs_to_tmdb_seasons=lambda dirs, matched: [],
        )
        assert (root, 1) in season_dirs
        assert (extras, 0) in season_dirs


def _table_with_specials() -> tuple[EpisodeAssignmentTable, dict[int, str]]:
    table = EpisodeAssignmentTable()
    titles = {1: "Rabbot", 2: "Escape from Leprechaupolis", 3: "Mission Overview"}
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=0, episode=episode, title=title))
    return table, titles


class TestExtrasFolderNumberClaims:
    def test_bare_number_from_extras_file_does_not_claim_slot(self):
        table, titles = _table_with_specials()
        _resolve_into_table(
            table,
            file_path=Path("Star Trek TNG Season 2 Extra 4 - Production.m4v"),
            season_num=0,
            season_titles=titles,
            from_extras_folder=True,
        )
        assert table.assignments() == []
        assert len(table.unassigned_files()) == 1

    def test_extras_file_with_exact_title_still_matches(self):
        table, titles = _table_with_specials()
        _resolve_into_table(
            table,
            file_path=Path("Star Trek TNG Season 3 Extra 1 - Mission Overview.m4v"),
            season_num=0,
            season_titles=titles,
            from_extras_folder=True,
        )
        assignments = table.assignments()
        assert len(assignments) == 1
        assert assignments[0].episodes == (3,)

    def test_companion_ncop_nced_files_never_claim_slots(self):
        table, titles = _table_with_specials()
        for name in (
            "[Group] Gundam - NCOP1 (BD).mkv",
            "[Group] Gundam - NCED2 (BD).mkv",
        ):
            _resolve_into_table(
                table,
                file_path=Path(name),
                season_num=0,
                season_titles=titles,
                from_extras_folder=True,
            )
        assert table.assignments() == []
        assert len(table.unassigned_files()) == 2

    def test_gundam_layout_scans_root_episodes_once_and_nested_extras(self, tmp_path):
        """Root episodes + Extras subdir: no dropped episodes, no double scan."""
        from plex_renamer.engine import TVScanner

        root = tmp_path / "[Group] Space War 0083 (BD)"
        extras = root / "Extras"
        nested = extras / "The Mayfly of Space"
        nested.mkdir(parents=True)
        for index, title in enumerate(["Alpha", "Beta"], start=1):
            (root / f"[Group] Space War - 0{index} - {title} (BD).mkv").touch()
        (extras / "[Group] Space War - NCOP1 (BD).mkv").touch()
        (nested / "The Mayfly of Space (BD).mkv").touch()
        (nested / "Second Sortie (BD).mkv").touch()

        class _FakeTMDB:
            def get_season_map(self, show_id):
                return {
                    0: {
                        "titles": {1: "The Mayfly of Space", 2: "Second Sortie"},
                        "posters": {},
                        "episodes": {},
                        "count": 2,
                    },
                    1: {
                        "titles": {1: "Alpha", 2: "Beta"},
                        "posters": {},
                        "episodes": {},
                        "count": 2,
                    },
                }, 2

            def get_season(self, show_id, season_num):
                return self.get_season_map(show_id)[0].get(season_num, {"titles": {}})

            def get_tv_details(self, show_id):
                return {"id": show_id, "seasons": []}

        scanner = TVScanner(
            _FakeTMDB(),
            {"id": 9, "name": "Space War", "year": "1991"},
            root,
        )
        _items, _mismatch = scanner.scan()
        table = scanner.assignment_table

        paths = [entry.path for entry in table.files.values()]
        assert len(paths) == len(set(paths)), "files scanned twice"

        by_slot = {
            (a.season, a.episodes): table.files[a.file_id].path.name for a in table.assignments()
        }
        assert by_slot[(1, (1,))].startswith("[Group] Space War - 01")
        assert by_slot[(1, (2,))].startswith("[Group] Space War - 02")
        assert (0, (1,)) in by_slot and "Mayfly" in by_slot[(0, (1,))]
        assert (0, (2,)) in by_slot

    def test_explicit_s00e_number_in_extras_folder_still_claims(self):
        table, titles = _table_with_specials()
        _resolve_into_table(
            table,
            file_path=Path("Show S00E02 - Some Special.mkv"),
            season_num=0,
            season_titles=titles,
            from_extras_folder=True,
        )
        assignments = table.assignments()
        assert len(assignments) == 1
        assert assignments[0].episodes == (2,)
