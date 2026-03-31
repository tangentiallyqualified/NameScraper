"""Tests for JoJo-style matching edge cases.

Covers:
  Bug 1 — bare-number OVA filenames detected as TV episodes
  Bug 2 — episode count tiebreaker in batch discovery
  Bug 3 — episode_confidence field on PreviewItem
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.services import (
    MovieLibraryDiscoveryService,
    TVLibraryDiscoveryService,
)
from plex_renamer.engine import BatchTVOrchestrator, MovieScanner
from plex_renamer.parsing import extract_episode, looks_like_tv_episode


# ── Bare-number OVA filenames (Bug 1) ──────────────────────────────────────

class BareNumberPatternTests(unittest.TestCase):
    """The ``01. Title Here.mkv`` naming convention should be recognized as TV."""

    OVA_FILENAMES = [
        "01. The Evil Spirit (2000).mkv",
        "02. Hierophant Green (2000).mkv",
        "08. Iggi The Fool and N'Dool The Geb (1993).mkv",
        "13. Dio's -The World- - Farewell, My Friends (1994).mkv",
    ]

    def test_bare_number_filenames_detected_as_tv(self):
        for name in self.OVA_FILENAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    looks_like_tv_episode(Path(f"/tmp/OVA/{name}")),
                    f"Expected TV detection for: {name}",
                )

    def test_normal_movie_filenames_not_detected_as_tv(self):
        """Ensure the pattern doesn't false-positive on regular movie files."""
        movie_names = [
            "Inception (2010).mkv",
            "Die Hard (1988).mkv",
            "2001 A Space Odyssey.mkv",
            "Blade Runner (1982) - Final Cut.mkv",
        ]
        for name in movie_names:
            with self.subTest(name=name):
                self.assertFalse(
                    looks_like_tv_episode(Path(f"/tmp/Movies/{name}")),
                    f"False positive TV detection for movie: {name}",
                )


class TVCompanionVideoPatternTests(unittest.TestCase):
    """NCOP/NCED-style extras should be treated as TV-related files."""

    COMPANION_FILENAMES = [
        "Show.Name.NCOP.mkv",
        "Show.Name.NCED1.mkv",
        "[Group] Show Name - NCOPv2 (BD 1080p).mkv",
        "Show Name - Creditless Opening.mkv",
        "Show Name - Clean Ending.mkv",
    ]

    def test_tv_companion_video_filenames_detected_as_tv(self):
        for name in self.COMPANION_FILENAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    looks_like_tv_episode(Path(f"/tmp/Anime/{name}")),
                    f"Expected TV companion detection for: {name}",
                )


class CombinedFansubEpisodeRangeTests(unittest.TestCase):
    """Fansub multi-episode ranges should classify as TV and parse correctly."""

    FILENAME = (
        "[GHOST][1080p] Inuyasha - 166-167 "
        "[BD HEVC 10bit Dual Audio AC3][720C96ED].mkv"
    )

    def test_combined_fansub_range_detected_as_tv(self):
        self.assertTrue(
            looks_like_tv_episode(Path(f"/tmp/Inuyasha/{self.FILENAME}")),
        )

    def test_combined_fansub_range_extracts_multiple_episodes(self):
        self.assertEqual(
            extract_episode(self.FILENAME),
            ([166, 167], None, False),
        )


class MovieDiscoveryOVATests(unittest.TestCase):
    """OVA folders with bare-number files should NOT become movie candidates."""

    def test_ova_folder_excluded_from_movie_discovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for name in [
                "01. The Evil Spirit (2000).mkv",
                "02. Hierophant Green (2000).mkv",
                "03. Silver Chariot and Strength (2000).mkv",
            ]:
                (ova / name).write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            self.assertEqual(len(candidates), 0, "OVA folder should not be a movie candidate")

    def test_mixed_library_ova_excluded_movie_kept(self):
        """OVA folder excluded, proper movie folder kept."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for i in range(1, 14):
                (ova / f"{i:02d}. Episode Title.mkv").write_text("x")

            movie = root / "Inception (2010)"
            movie.mkdir()
            (movie / "Inception.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, "Inception (2010)")

    def test_show_folder_with_ncop_nced_files_excluded_from_movie_discovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Frieren"
            show.mkdir()
            (show / "Frieren.S01E01.mkv").write_text("x")
            (show / "Frieren.NCOP.mkv").write_text("x")
            (show / "Frieren.NCED.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(candidates, [])

    def test_combined_fansub_episode_range_excluded_from_movie_discovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Inuyasha"
            show.mkdir()
            (
                show
                / "[GHOST][1080p] Inuyasha - 166-167 [BD HEVC 10bit Dual Audio AC3][720C96ED].mkv"
            ).write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(candidates, [])


class _FakeMovieTMDB:
    language = "en-US"

    def __init__(self):
        self.queries = []

    def search_movies_batch(self, queries, progress_callback=None):
        self.queries.extend(queries)
        results = []
        total = len(queries)
        for index, (query, _year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            if "matrix" in query.lower():
                results.append([
                    {"id": 603, "title": "The Matrix", "year": "1999", "poster_path": None, "overview": ""},
                ])
            else:
                results.append([])
        return results

    def search_movie(self, query, year=None):
        self.queries.append((query, year))
        if "matrix" in query.lower():
            return [
                {"id": 603, "title": "The Matrix", "year": "1999", "poster_path": None, "overview": ""},
            ]
        return []

    def search_with_fallback(self, query, search_fn, **kwargs):
        return search_fn(query, **kwargs)

    def get_alternative_titles(self, media_id, media_type="movie"):
        return []


class MovieScannerCompanionVideoTests(unittest.TestCase):
    """MovieScanner should skip TV companion videos instead of matching them as movies."""

    def test_movie_scanner_skips_ncop_and_only_searches_real_movie_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie_file = root / "The.Matrix.1999.1080p.BluRay.mkv"
            companion_file = root / "Series.Name.NCOP.mkv"
            movie_file.write_text("x")
            companion_file.write_text("x")

            tmdb = _FakeMovieTMDB()
            scanner = MovieScanner(tmdb, root)

            items = scanner.scan()

            self.assertEqual(tmdb.queries, [("The Matrix", "1999")])
            by_name = {item.original.name: item for item in items}
            self.assertIn(movie_file.name, by_name)
            self.assertIn(companion_file.name, by_name)
            self.assertEqual(
                by_name[companion_file.name].status,
                "SKIP: looks like a TV episode",
            )
            self.assertEqual(by_name[movie_file.name].media_type, "movie")


class TVDiscoveryOVATests(unittest.TestCase):
    """OVA folders with bare-number files SHOULD be found by TV discovery."""

    def test_ova_folder_included_in_tv_discovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for name in [
                "01. The Evil Spirit (2000).mkv",
                "02. Hierophant Green (2000).mkv",
                "03. Silver Chariot and Strength (2000).mkv",
            ]:
                (ova / name).write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {c.relative_folder for c in candidates}
            self.assertIn("Jojos bizarre adventure", relative_paths)


# ── Episode count tiebreaker (Bug 2) ───────────────────────────────────────

class _FakeTMDBWithEpisodeCounts:
    """TMDB stub that returns two JoJo series with different episode counts."""

    language = "en-US"

    JOJO_2012 = {
        "id": 31911,
        "name": "JoJo's Bizarre Adventure",
        "year": "2012",
        "poster_path": None,
        "overview": "2012 TV series",
    }
    JOJO_1993 = {
        "id": 29955,
        "name": "JoJo's Bizarre Adventure",
        "year": "1993",
        "poster_path": None,
        "overview": "1993 OVA",
    }

    DETAILS = {
        31911: {"number_of_episodes": 190, "number_of_seasons": 5},
        29955: {"number_of_episodes": 13, "number_of_seasons": 1},
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        for i, (_name, _year) in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            # Both series returned for every query, 2012 first (higher popularity)
            results.append([self.JOJO_2012, self.JOJO_1993])
        return results

    def get_tv_details(self, show_id):
        return self.DETAILS.get(show_id)

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []


class EpisodeCountTiebreakerTests(unittest.TestCase):
    """When title scores are tied, prefer the TMDB match whose episode count
    is closest to the number of video files on disk."""

    def test_ova_folder_matches_ova_series_not_2012(self):
        """13-file OVA folder should match the 13-episode 1993 OVA, not the
        190-episode 2012 series."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for i in range(1, 14):
                (ova / f"{i:02d}. Episode Title.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBWithEpisodeCounts(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            # Should pick the 1993 OVA (13 eps) over 2012 (190 eps)
            self.assertEqual(state.show_id, 29955,
                             f"Expected 1993 OVA (29955), got {state.show_id}")

    def test_large_folder_matches_large_series(self):
        """A folder with 48+ S##E## files should prefer the 190-episode 2012
        series over the 13-episode OVA."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "JoJo's Bizarre Adventure (2012)"
            (show / "Season 01").mkdir(parents=True)
            for i in range(1, 49):
                (show / "Season 01" / f"S01E{i:02d}.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBWithEpisodeCounts(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            # Should pick the 2012 series (190 eps) over 1993 OVA (13 eps)
            self.assertEqual(state.show_id, 31911,
                             f"Expected 2012 series (31911), got {state.show_id}")


# ── Episode confidence field (Bug 3) ───────────────────────────────────────

class EpisodeConfidenceTests(unittest.TestCase):
    """PreviewItem.episode_confidence should reflect match quality."""

    def test_default_confidence_is_1(self):
        from plex_renamer.engine import PreviewItem
        item = PreviewItem(
            original=Path("/tmp/test.mkv"),
            new_name="test.mkv",
            target_dir=None,
            season=1,
            episodes=[1],
            status="OK",
        )
        self.assertEqual(item.episode_confidence, 1.0)

    def test_confidence_field_accepts_low_values(self):
        from plex_renamer.engine import PreviewItem
        item = PreviewItem(
            original=Path("/tmp/test.mkv"),
            new_name="test.mkv",
            target_dir=None,
            season=1,
            episodes=[1],
            status="OK",
            episode_confidence=0.3,
        )
        self.assertEqual(item.episode_confidence, 0.3)


# ── Flat folder → multi-season distribution ────────────────────────────────

class _FakeTMDBForOVAScan:
    """TMDB stub that returns season data for the 1993 JoJo OVA (2 seasons).

    Season 1 (1993-1994): 6 episodes — the later-numbered disk files (08-13)
    Season 2 (2000):      7 episodes — the early-numbered disk files (01-07)

    The episode titles mirror the filenames used in the tests so that
    title-based matching can correctly assign files to seasons even though
    the on-disk numbering order doesn't match the TMDB season order.
    """

    SHOW_INFO = {
        "id": 29955,
        "name": "JoJo's Bizarre Adventure",
        "year": "1993",
    }

    # Season 1 titles correspond to files 08-13 (the 1993/1994 episodes)
    _S1_TITLES = {
        1: "Iggy the Fool and N'Doul the Geb",
        2: "The Judgement D'Arby the Gambler",
        3: "D'Arby the Player",
        4: "The Warrior of the Void Vanilla Ice",
        5: "DIO's World",
        6: "DIO's World Farewell My Friends",
    }

    # Season 2 titles correspond to files 01-07 (the 2000 episodes)
    _S2_TITLES = {
        1: "The Evil Spirit",
        2: "Hierophant Green",
        3: "Silver Chariot and Strength",
        4: "The Emperor and the Hanged Man",
        5: "The Judgement",
        6: "The Mist of Vengeance",
        7: "Iggy the Fool and Geb's N'Doul",
    }

    _SEASON_MAP = {
        1: {
            "titles": _S1_TITLES,
            "posters": {i: None for i in range(1, 7)},
            "episodes": {},
            "count": 6,
        },
        2: {
            "titles": _S2_TITLES,
            "posters": {i: None for i in range(1, 8)},
            "episodes": {},
            "count": 7,
        },
    }

    def get_season_map(self, show_id):
        return self._SEASON_MAP, 13

    def get_season(self, show_id, season_num):
        if season_num in self._SEASON_MAP:
            return self._SEASON_MAP[season_num]
        return {"titles": {}, "posters": {}, "episodes": {}}


class FlatFolderMultiSeasonTests(unittest.TestCase):
    """A flat folder with 13 bare-number files should be distributed across
    TMDB's 2 seasons (6 + 7), not crammed into Season 01.

    The on-disk numbering (01-13) does NOT match the TMDB season order:
      files 01-07 carry (2000) titles → TMDB Season 2
      files 08-13 carry (1993/1994) titles → TMDB Season 1

    Title-based matching should assign each file to the correct season
    regardless of the sequential numbering.
    """

    # Files 01-07: Season 2 episode titles (2000 OVA)
    # Files 08-13: Season 1 episode titles (1993/1994 OVA)
    _OVA_FILES = [
        "01. The Evil Spirit (2000).mkv",
        "02. Hierophant Green (2000).mkv",
        "03. Silver Chariot and Strength (2000).mkv",
        "04. The Emperor and the Hanged Man (2000).mkv",
        "05. The Judgement (2000).mkv",
        "06. The Mist of Vengeance (2000).mkv",
        "07. Iggy the Fool and Geb's N'Doul (2000).mkv",
        "08. Iggy the Fool and N'Doul the Geb (1993).mkv",
        "09. The Judgement D'Arby the Gambler (1993).mkv",
        "10. D'Arby the Player (1993).mkv",
        "11. The Warrior of the Void Vanilla Ice (1993).mkv",
        "12. DIO's World (1994).mkv",
        "13. DIO's World Farewell My Friends (1994).mkv",
    ]

    def test_flat_ova_distributes_across_seasons(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in self._OVA_FILES:
                (root / name).write_text("x")

            from plex_renamer.engine import TVScanner
            tmdb = _FakeTMDBForOVAScan()
            scanner = TVScanner(tmdb, tmdb.SHOW_INFO, root)
            items, _ = scanner.scan()

            # Should have 13 items total
            self.assertEqual(len(items), 13)

            season_1_items = [it for it in items if it.season == 1]
            season_2_items = [it for it in items if it.season == 2]

            self.assertEqual(len(season_1_items), 6,
                             f"Expected 6 items in Season 1, got {len(season_1_items)}")
            self.assertEqual(len(season_2_items), 7,
                             f"Expected 7 items in Season 2, got {len(season_2_items)}")

    def test_title_matching_assigns_correct_files_to_seasons(self):
        """Verify that specific files end up in the correct season based on
        their episode titles, not their sequential numbering."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in self._OVA_FILES:
                (root / name).write_text("x")

            from plex_renamer.engine import TVScanner
            tmdb = _FakeTMDBForOVAScan()
            scanner = TVScanner(tmdb, tmdb.SHOW_INFO, root)
            items, _ = scanner.scan()

            # Build a map of original filename → assigned season
            season_by_file = {it.original.name: it.season for it in items}

            # Files 01-07 (2000 titles) should be in Season 2
            for name in self._OVA_FILES[:7]:
                with self.subTest(name=name):
                    self.assertEqual(season_by_file[name], 2,
                                     f"{name} should be Season 2")

            # Files 08-13 (1993/1994 titles) should be in Season 1
            for name in self._OVA_FILES[7:]:
                with self.subTest(name=name):
                    self.assertEqual(season_by_file[name], 1,
                                     f"{name} should be Season 1")

    def test_sequential_fallback_for_generic_filenames(self):
        """When filenames have no recognizable titles (generic names),
        title matching should fall back to sequential distribution."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(1, 14):
                (root / f"{i:02d}. Episode Title.mkv").write_text("x")

            from plex_renamer.engine import TVScanner
            tmdb = _FakeTMDBForOVAScan()
            scanner = TVScanner(tmdb, tmdb.SHOW_INFO, root)
            items, _ = scanner.scan()

            self.assertEqual(len(items), 13)
            # Sequential: first 6 → S1, next 7 → S2
            season_1_items = [it for it in items if it.season == 1]
            season_2_items = [it for it in items if it.season == 2]
            self.assertEqual(len(season_1_items), 6)
            self.assertEqual(len(season_2_items), 7)

    def test_flat_single_season_not_affected(self):
        """A flat folder matching a single-season show should still work normally."""
        single_season_map = {
            1: {
                "titles": {i: f"Episode {i}" for i in range(1, 14)},
                "posters": {i: None for i in range(1, 14)},
                "episodes": {},
                "count": 13,
            },
        }

        class _FakeSingleSeason:
            SHOW_INFO = {"id": 1, "name": "Test Show", "year": "2020"}
            def get_season_map(self, show_id):
                return single_season_map, 13
            def get_season(self, show_id, season_num):
                return single_season_map.get(season_num, {"titles": {}, "posters": {}, "episodes": {}})

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(1, 14):
                (root / f"{i:02d}. Episode Title.mkv").write_text("x")

            from plex_renamer.engine import TVScanner
            tmdb = _FakeSingleSeason()
            scanner = TVScanner(tmdb, tmdb.SHOW_INFO, root)
            items, _ = scanner.scan()

            self.assertEqual(len(items), 13)
            # All should be Season 1
            for item in items:
                self.assertEqual(item.season, 1)


class FlatFolderSpecialsOffsetRegressionTests(unittest.TestCase):
    """Flat-folder absolute mapping must not consume regular episodes with TMDB specials."""

    class _FakeInuyashaTMDB:
        SHOW_INFO = {"id": 249, "name": "Inuyasha", "year": "2000"}

        _SEASON_MAP = {
            0: {
                "titles": {1: "Special 1"},
                "posters": {1: None},
                "episodes": {},
                "count": 1,
            },
            1: {
                "titles": {
                    1: "The Girl Who Overcame Time... and the Boy Who Was Just Overcome",
                    2: "Seekers of the Sacred Jewel",
                },
                "posters": {1: None, 2: None},
                "episodes": {},
                "count": 2,
            },
            2: {
                "titles": {
                    1: "Naraku's Trap, Kagome's Decision",
                    2: "The Stolen Sacred Jewel",
                },
                "posters": {1: None, 2: None},
                "episodes": {},
                "count": 2,
            },
        }

        def get_season_map(self, show_id):
            return self._SEASON_MAP, 4

        def get_season(self, show_id, season_num):
            return self._SEASON_MAP.get(
                season_num,
                {"titles": {}, "posters": {}, "episodes": {}},
            )

    def test_flat_absolute_numbering_ignores_specials_offset(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [
                "[GHOST][1080p] Inuyasha - 001 [BD HEVC 10bit Dual Audio AC3][5C86C2BB].mkv",
                "[GHOST][1080p] Inuyasha - 002 [BD HEVC 10bit Dual Audio AC3][BEEE35EE].mkv",
                "[GHOST][1080p] Inuyasha - 003 [BD HEVC 10bit Dual Audio AC3][11111111].mkv",
                "[GHOST][1080p] Inuyasha - 004 [BD HEVC 10bit Dual Audio AC3][22222222].mkv",
            ]
            for name in files:
                (root / name).write_text("x")

            from plex_renamer.engine import TVScanner

            tmdb = self._FakeInuyashaTMDB()
            scanner = TVScanner(tmdb, tmdb.SHOW_INFO, root)
            items, _ = scanner.scan()

            by_name = {item.original.name: item for item in items}

            self.assertEqual(by_name[files[0]].season, 1)
            self.assertEqual(by_name[files[0]].episodes, [1])
            self.assertEqual(by_name[files[1]].season, 1)
            self.assertEqual(by_name[files[1]].episodes, [2])
            self.assertEqual(by_name[files[2]].season, 2)
            self.assertEqual(by_name[files[2]].episodes, [1])
            self.assertEqual(by_name[files[3]].season, 2)
            self.assertEqual(by_name[files[3]].episodes, [2])


if __name__ == "__main__":
    unittest.main()
