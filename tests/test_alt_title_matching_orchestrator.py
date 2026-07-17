"""Movie-orchestrator and language-priority alt-title matching tests.

Split from test_alt_title_matching.py to keep both files under the
repository's LOC ceiling; the shared _FakeTMDB fixture stays in the
original module and is imported back here.

Covers:
  - Full movie discovery + alt title flow through BatchMovieOrchestrator
  - Language priority: preferred country -> English fallback -> all others
  - Realistic movie and TV show scenarios with diverse alt title patterns
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_alt_title_matching import _FakeTMDB

from plex_renamer.engine import (
    AUTO_ACCEPT_THRESHOLD,
    BatchMovieOrchestrator,
    boost_scores_with_alt_titles,
    score_results,
)
from plex_renamer.engine._movie_scanner import MovieScanner
from plex_renamer.tmdb import TMDBClient

# ── Integration: movie orchestrator with alt titles ──────────────────────────


class _FakeTMDBForMovieOrchestrator(TMDBClient):
    """TMDB stub for testing the full movie discovery + alt title flow.

    Subclasses TMDBClient (without calling its __init__) purely so it type
    checks as one at the BatchMovieOrchestrator call sites below.

    Supports multiple movies to exercise realistic batch discovery:
      - Dune (2021) — subtitle mismatch, needs alt title boost
      - Spirited Away (2001) — Japanese primary, English alt needed
      - The Matrix (1999) — exact match, no boost needed
      - Parasite (2019) — Korean primary, English alt needed
    """

    language = "en-US"

    def __init__(self) -> None:
        pass  # deliberately skip TMDBClient.__init__; this fake is stateless

    MOVIES = {
        "dune": [
            {
                "id": 438631,
                "title": "Dune",
                "year": "2021",
                "poster_path": None,
                "overview": "A noble family...",
            },
        ],
        "spirited away": [
            {
                "id": 129,
                "title": "Sen to Chihiro no Kamikakushi",
                "year": "2001",
                "poster_path": None,
                "overview": "A girl...",
            },
        ],
        "sen to chihiro": [
            {
                "id": 129,
                "title": "Sen to Chihiro no Kamikakushi",
                "year": "2001",
                "poster_path": None,
                "overview": "A girl...",
            },
        ],
        "matrix": [
            {
                "id": 603,
                "title": "The Matrix",
                "year": "1999",
                "poster_path": None,
                "overview": "A hacker...",
            },
        ],
        "parasite": [
            {
                "id": 496243,
                "title": "Gisaengchung",
                "year": "2019",
                "poster_path": None,
                "overview": "Greed and class...",
            },
        ],
        "gisaengchung": [
            {
                "id": 496243,
                "title": "Gisaengchung",
                "year": "2019",
                "poster_path": None,
                "overview": "Greed and class...",
            },
        ],
        "crouching tiger": [
            {
                "id": 146,
                "title": "Wo hu cang long",
                "year": "2000",
                "poster_path": None,
                "overview": "Two warriors...",
            },
        ],
    }

    ALT_TITLES = {
        438631: [
            ("Dune: Part One", "US"),
            ("Dune: Parte uno", "IT"),
            ("Dune: Première partie", "FR"),
        ],
        129: [
            ("Spirited Away", "US"),
            ("Le Voyage de Chihiro", "FR"),
            ("Chihiros Reise ins Zauberland", "DE"),
        ],
        603: [],  # The Matrix needs no alt titles
        496243: [
            ("Parasite", "US"),
            ("Parasite", "GB"),
            ("パラサイト 半地下の家族", "JP"),
        ],
        146: [
            ("Crouching Tiger, Hidden Dragon", "US"),
            ("Tigre et Dragon", "FR"),
        ],
    }

    def search_movie(self, query, year=None):
        q = query.lower()
        for key, results in self.MOVIES.items():
            if key in q:
                return list(results)
        return []

    def search_with_fallback(self, query, search_fn, **kwargs):
        words = query.split()
        for n in range(len(words), 0, -1):
            attempt = " ".join(words[:n])
            results = search_fn(attempt, **kwargs)
            if results:
                return results
        return []

    def search_movies_batch(self, queries, max_workers=8, progress_callback=None):
        results = []
        for i, (query, year) in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append(self.search_with_fallback(query, self.search_movie, year=year))
        return results

    def get_alternative_titles(self, media_id, media_type="movie"):
        return self.ALT_TITLES.get(media_id, [])


class MovieOrchestratorAltTitleTests(unittest.TestCase):
    """The movie orchestrator should use alt titles to boost low-confidence
    matches during discovery."""

    def _discover(self, folder_names):
        """Helper: create temp dirs and run movie discovery."""
        from plex_renamer.app.services import MovieLibraryDiscoveryService

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in folder_names:
                d = root / name
                d.mkdir()
                (d / f"{name.split('.')[0]}.mkv").write_text("x")

            tmdb = _FakeTMDBForMovieOrchestrator()
            orchestrator = BatchMovieOrchestrator(
                tmdb,
                root,
                discovery_service=MovieLibraryDiscoveryService(),
            )
            return orchestrator.discover_movies()

    def test_dune_part_one_matched_with_high_confidence(self):
        """Dune.Part.One.2021 folder should auto-accept via alt title boost."""
        states = self._discover(["Dune.Part.One.2021.2160p.UHD.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 438631)
        self.assertGreaterEqual(
            state.confidence,
            AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, got {state.confidence:.2f}",
        )
        self.assertFalse(state.checked, "Matched results start unchecked until explicitly queued")

    def test_matrix_exact_match_no_boost_needed(self):
        """The.Matrix.1999 should auto-accept without needing alt titles."""
        states = self._discover(["The.Matrix.1999.1080p.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 603)
        self.assertGreaterEqual(state.confidence, AUTO_ACCEPT_THRESHOLD)
        self.assertFalse(state.checked)

    def test_spirited_away_english_folder_matches_japanese_primary(self):
        """Spirited.Away.2001 should match the Japanese-titled TMDB entry
        via English alt title."""
        states = self._discover(["Spirited.Away.2001.1080p.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 129)
        self.assertGreaterEqual(
            state.confidence,
            AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, got {state.confidence:.2f}",
        )

    def test_parasite_english_folder_matches_korean_primary(self):
        """Parasite.2019 should match the Korean-titled TMDB entry
        via English alt title."""
        states = self._discover(["Parasite.2019.2160p.UHD.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 496243)
        self.assertGreaterEqual(
            state.confidence,
            AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, got {state.confidence:.2f}",
        )

    def test_crouching_tiger_english_folder(self):
        """Crouching.Tiger.Hidden.Dragon.2000 should match the Mandarin
        TMDB entry via English alt title."""
        states = self._discover(
            [
                "Crouching.Tiger.Hidden.Dragon.2000.1080p.BluRay",
            ]
        )
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 146)
        self.assertGreaterEqual(
            state.confidence,
            AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, got {state.confidence:.2f}",
        )

    def test_multi_movie_folder_scan_uses_only_selected_source_file(self):
        """A multi-movie dump folder should scan only the matched source file."""
        from plex_renamer.app.services import MovieLibraryDiscoveryService

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump = root / "Unsorted"
            dump.mkdir()
            matrix_file = dump / "The.Matrix.1999.1080p.BluRay.mkv"
            dune_file = dump / "Dune.Part.One.2021.2160p.UHD.BluRay.mkv"
            parasite_file = dump / "Parasite.2019.2160p.UHD.BluRay.mkv"
            matrix_file.write_text("x")
            dune_file.write_text("x")
            parasite_file.write_text("x")

            tmdb = _FakeTMDBForMovieOrchestrator()
            orchestrator = BatchMovieOrchestrator(
                tmdb,
                root,
                discovery_service=MovieLibraryDiscoveryService(),
            )

            states = orchestrator.discover_movies()
            self.assertEqual(len(states), 3)

            matrix_state = next(state for state in states if state.show_id == 603)
            self.assertEqual(matrix_state.source_file, matrix_file)

            orchestrator.scan_movie(matrix_state)

            self.assertTrue(matrix_state.scanned)
            scanner = matrix_state.scanner
            assert isinstance(scanner, MovieScanner)
            self.assertEqual(scanner.explicit_files, [matrix_file])
            self.assertEqual(len(matrix_state.preview_items), 1)
            self.assertEqual(matrix_state.preview_items[0].original, matrix_file)


# ── Language priority tests ──────────────────────────────────────────────────


class LanguagePriorityTests(unittest.TestCase):
    """Verify that preferred_country influences alt title ordering."""

    def test_preferred_country_titles_tried(self):
        """Alt titles from the preferred country should be considered."""
        results = [
            {
                "id": 10,
                "title": "Vollkommen Anderer Titel",
                "year": "2020",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "My Movie (2020)"
        year_hint = "2020"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({10: [("My Movie", "US"), ("Mein Film", "DE")]})
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="FR",
        )
        # English fallback should still boost the score
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_preferred_country_match_wins(self):
        """When the preferred country has the matching title, it should
        be found and used for boosting."""
        results = [
            {
                "id": 20,
                "title": "Vollkommen Anderer Titel",
                "year": "2020",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Le Titre Français (2020)"
        year_hint = "2020"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                20: [
                    ("Le Titre Français", "FR"),
                    ("The French Title", "US"),
                ]
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="FR",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_french_user_matches_french_alt_title(self):
        """A French user searching for 'Le Voyage de Chihiro' should match
        via the FR alt title of Spirited Away. Year omitted to keep primary
        score below threshold (shared 'chihiro' token would otherwise push
        the LCS high enough with the year bonus)."""
        results = [
            {
                "id": 129,
                "title": "Sen to Chihiro no Kamikakushi",
                "year": "2001",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Le Voyage de Chihiro"
        year_hint = None

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                129: [
                    ("Spirited Away", "US"),
                    ("Le Voyage de Chihiro", "FR"),
                    ("Chihiros Reise ins Zauberland", "DE"),
                ]
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="FR",
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_german_user_matches_german_alt_title(self):
        """A German user's folder 'Ziemlich beste Freunde' should match
        'Intouchables' via the DE alt title."""
        results = [
            {
                "id": 200,
                "title": "Intouchables",
                "year": "2011",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Ziemlich beste Freunde (2011)"
        year_hint = "2011"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                200: [
                    ("The Intouchables", "US"),
                    ("Ziemlich beste Freunde", "DE"),
                    ("Amigos intocables", "ES"),
                ]
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="DE",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_spanish_user_matches_spanish_tv_alt(self):
        """A Spanish user's folder 'La Casa de Papel' should match when
        the primary is the English Netflix title 'Money Heist'."""
        results = [
            {
                "id": 71446,
                "name": "Money Heist",
                "year": "2017",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "La Casa de Papel (2017)"
        year_hint = "2017"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                71446: [
                    ("La Casa de Papel", "ES"),
                    ("Haus des Geldes", "DE"),
                    ("La Maison de Papier", "FR"),
                ]
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="name",
            media_type="tv",
            preferred_country="ES",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_japanese_user_anime_reverse_lookup(self):
        """A Japanese user with folder '進撃の巨人' should match
        'Attack on Titan' via JP alt title."""
        results = [
            {
                "id": 1429,
                "name": "Attack on Titan",
                "year": "2013",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "進撃の巨人 (2013)"
        year_hint = "2013"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                1429: [
                    ("Shingeki no Kyojin", "JP"),
                    ("進撃の巨人", "JP"),
                    ("L'Attaque des Titans", "FR"),
                ]
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="name",
            media_type="tv",
            preferred_country="JP",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_no_preferred_country_falls_back_to_english(self):
        """When no preferred country is set, English alt titles should
        still be found as a fallback."""
        results = [
            {
                "id": 496243,
                "title": "Gisaengchung",
                "year": "2019",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Parasite (2019)"
        year_hint = "2019"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                496243: [
                    ("Parasite", "US"),
                    ("Parasita", "BR"),
                ]
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            # No preferred_country
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
