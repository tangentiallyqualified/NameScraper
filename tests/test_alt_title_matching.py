"""Tests for alternative-title matching in score boosting.

Covers:
  - boost_scores_with_alt_titles promotes a low-confidence primary match
    when an alternative title matches better
  - No-op when the top result already exceeds the auto-accept threshold
  - Works for both movie and TV media types
  - Handles missing or empty alternative titles gracefully
  - Language priority: preferred country → English fallback → all others
  - Realistic movie and TV show scenarios with diverse alt title patterns
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.engine import (
    AUTO_ACCEPT_THRESHOLD,
    BatchMovieOrchestrator,
    boost_scores_with_alt_titles,
    score_results,
)


# ── Fake TMDB client ────────────────────────────────────────────────────────

class _FakeTMDB:
    """Minimal TMDB stub that returns configurable alternative titles.

    Alt titles are stored as ``{media_id: [(title, country_code), ...]}``.
    """

    def __init__(
        self,
        alt_titles_map: dict[int, list[tuple[str, str]]] | None = None,
    ):
        self._alt_titles = alt_titles_map or {}

    def get_alternative_titles(self, media_id: int, media_type: str = "movie"):
        return self._alt_titles.get(media_id, [])


# ── Unit tests for boost_scores_with_alt_titles ─────────────────────────────

class BoostScoresTests(unittest.TestCase):
    """Direct tests for the boost_scores_with_alt_titles function."""

    # -- Movies with subtitle differences --

    def test_dune_part_one_boosted_via_alt_title(self):
        """Dune (2021) primary title scores poorly against 'Dune Part One';
        the US alt title 'Dune: Part One' should push it above threshold."""
        results = [
            {"id": 438631, "title": "Dune", "year": "2021",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Dune Part One (2021)"
        year_hint = "2021"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({438631: [
            ("Dune: Part One", "US"),
            ("Dune: Parte uno", "IT"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertGreater(boosted[0][1], scored[0][1])
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_spider_man_across_the_spider_verse(self):
        """TMDB primary 'Spider-Man: Across the Spider-Verse' matches poorly
        against the folder name without the colon/hyphen; the alt title with
        slightly different formatting should still boost."""
        results = [
            {"id": 569094, "title": "Spider-Man: Across the Spider-Verse",
             "year": "2023", "poster_path": None, "overview": ""},
        ]
        raw_name = "Spider Man Across The Spider Verse (2023)"
        year_hint = "2023"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        # This may or may not be above threshold depending on normalization.
        # The test verifies the score is at least as good after boosting.
        original = scored[0][1]

        tmdb = _FakeTMDB({569094: [
            ("Spider-Man: Across the Spider-Verse (Part One)", "US"),
            ("Spider-Man: Cruzando el Multiverso", "ES"),
            ("Spider-Man: Através do Aranhaverso", "BR"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertGreaterEqual(boosted[0][1], original)

    def test_harry_potter_subtitle_difference(self):
        """US title is 'Sorcerer's Stone' but UK/original is 'Philosopher's
        Stone'. Both score well due to shared prefix, but the US alt title
        should score at least as high as the original."""
        results = [
            {"id": 671, "title": "Harry Potter and the Philosopher's Stone",
             "year": "2001", "poster_path": None, "overview": ""},
        ]
        raw_name = "Harry Potter and the Sorcerers Stone (2001)"
        year_hint = "2001"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        original = scored[0][1]

        tmdb = _FakeTMDB({671: [
            ("Harry Potter and the Sorcerer's Stone", "US"),
            ("Harry Potter à l'école des sorciers", "FR"),
            ("Harry Potter und der Stein der Weisen", "DE"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        # Primary already scores well due to long shared prefix;
        # score should be maintained (no-op when already above threshold)
        self.assertGreaterEqual(boosted[0][1], original)

    def test_spirited_away_japanese_primary(self):
        """TMDB primary is the Japanese title 'Sen to Chihiro no Kamikakushi'.
        An English-named folder should be boosted by the US alt title."""
        results = [
            {"id": 129, "title": "Sen to Chihiro no Kamikakushi",
             "year": "2001", "poster_path": None, "overview": ""},
        ]
        raw_name = "Spirited Away (2001)"
        year_hint = "2001"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD,
                        "Japanese primary vs English query should be low")

        tmdb = _FakeTMDB({129: [
            ("Spirited Away", "US"),
            ("Le Voyage de Chihiro", "FR"),
            ("Chihiros Reise ins Zauberland", "DE"),
            ("El viaje de Chihiro", "ES"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_parasite_korean_primary(self):
        """Korean primary title 'Gisaengchung' should be boosted when
        the folder is named with the English title 'Parasite'."""
        results = [
            {"id": 496243, "title": "Gisaengchung", "year": "2019",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Parasite (2019)"
        year_hint = "2019"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({496243: [
            ("Parasite", "US"),
            ("Parasite", "GB"),
            ("Parasit", "DE"),
            ("Parasita", "BR"),
            ("パラサイト 半地下の家族", "JP"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_crouching_tiger_hidden_dragon(self):
        """Mandarin primary title should be boosted when folder uses the
        well-known English title. Year is omitted from the query to ensure
        the primary score stays below threshold."""
        results = [
            {"id": 146, "title": "Wo hu cang long", "year": "2000",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Crouching Tiger Hidden Dragon"
        year_hint = None

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({146: [
            ("Crouching Tiger, Hidden Dragon", "US"),
            ("Tigre et Dragon", "FR"),
            ("Tiger and Dragon", "DE"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    # -- TV shows --

    def test_tv_abbreviated_name_boosted(self):
        """JJBA abbreviation should be boosted when the full title is
        available as an alternative."""
        results = [
            {"id": 456, "name": "JJBA", "year": "2012",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "JoJo's Bizarre Adventure (2012)"
        year_hint = "2012"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        original = scored[0][1]

        tmdb = _FakeTMDB({456: [("JoJo's Bizarre Adventure", "US")]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="name", media_type="tv",
        )
        self.assertGreater(boosted[0][1], original)

    def test_tv_attack_on_titan(self):
        """Japanese primary 'Shingeki no Kyojin' should be boosted for an
        English-titled folder 'Attack on Titan'. Year omitted to ensure
        primary score stays below threshold."""
        results = [
            {"id": 1429, "name": "Shingeki no Kyojin", "year": "2013",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Attack on Titan"
        year_hint = None

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({1429: [
            ("Attack on Titan", "US"),
            ("L'Attaque des Titans", "FR"),
            ("Ataque a los Titanes", "ES"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="name", media_type="tv",
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_tv_dark_german_show(self):
        """German show 'Dark' — primary title is already in English, but
        a German-titled folder 'Dark Staffel' should still work if the
        alt title matches."""
        results = [
            {"id": 70523, "name": "Dark", "year": "2017",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Dark (2017)"
        year_hint = "2017"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        # "Dark" vs "Dark" — should already be above threshold
        self.assertGreaterEqual(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        # No boost needed — verify no-op
        tmdb = _FakeTMDB({70523: [("Dark", "DE")]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="name", media_type="tv",
        )
        self.assertEqual(scored[0][1], boosted[0][1])

    def test_tv_money_heist_spanish_primary(self):
        """Spanish primary 'La Casa de Papel' should be boosted when
        the folder uses the Netflix English title 'Money Heist'."""
        results = [
            {"id": 71446, "name": "La Casa de Papel", "year": "2017",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Money Heist (2017)"
        year_hint = "2017"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({71446: [
            ("Money Heist", "US"),
            ("Money Heist", "GB"),
            ("Haus des Geldes", "DE"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="name", media_type="tv",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    # -- Edge cases and no-ops --

    def test_no_boost_when_already_above_threshold(self):
        """When the top result already exceeds the threshold, alt titles
        should NOT be fetched (the function is a no-op)."""
        results = [
            {"id": 1, "title": "The Matrix", "year": "1999",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "The Matrix (1999)"
        year_hint = "1999"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertGreaterEqual(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB()
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertEqual(scored[0][1], boosted[0][1])

    def test_alt_title_can_reorder_results(self):
        """When a lower-ranked result has a better alternative title match,
        it should be promoted above a higher-ranked primary-only match."""
        results = [
            {"id": 1, "title": "Dune", "year": "2021",
             "poster_path": None, "overview": ""},
            {"id": 2, "title": "Dune Messiah", "year": "2026",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Dune Part One (2021)"
        year_hint = "2021"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({1: [("Dune: Part One", "US")]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertEqual(boosted[0][0]["id"], 1)
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_disambiguation_via_alt_title(self):
        """Two movies with similar primary titles — the alt title on the
        correct one should promote it above the wrong match."""
        results = [
            {"id": 100, "title": "The Girl with the Dragon Tattoo",
             "year": "2011", "poster_path": None, "overview": ""},
            {"id": 101, "title": "The Girl with the Dragon Tattoo",
             "year": "2009", "poster_path": None, "overview": ""},
        ]
        raw_name = "Män som hatar kvinnor (2009)"
        year_hint = "2009"

        scored = score_results(results, raw_name, year_hint, title_key="title")

        # The 2009 Swedish original has the Swedish alt title
        tmdb = _FakeTMDB({
            101: [("Män som hatar kvinnor", "SE")],
            100: [],  # US remake has no Swedish alt title
        })
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        # The 2009 Swedish version should be on top
        self.assertEqual(boosted[0][0]["id"], 101)

    def test_many_alt_titles_uses_best(self):
        """When a result has many alt titles, the best-scoring one should
        be selected and used for boosting."""
        results = [
            {"id": 200, "title": "Ziemlich beste Freunde", "year": "2011",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "The Intouchables (2011)"
        year_hint = "2011"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        original = scored[0][1]
        self.assertLess(original, AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({200: [
            ("The Intouchables", "US"),
            ("The Intouchables", "GB"),
            ("Intouchables", "FR"),
            ("Amigos intocables", "ES"),
            ("最強のふたり", "JP"),
            ("1+1", "RU"),
            ("Prijatelji", "RS"),
            ("Nedodirljivi", "HR"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertGreater(boosted[0][1], original)
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_empty_results_is_noop(self):
        """boost_scores_with_alt_titles handles empty input gracefully."""
        tmdb = _FakeTMDB()
        result = boost_scores_with_alt_titles(
            [], "Something", None, tmdb,
        )
        self.assertEqual(result, [])

    def test_no_alt_titles_preserves_scores(self):
        """When TMDB returns no alternative titles, scores are unchanged."""
        results = [
            {"id": 99, "title": "Dune", "year": "2021",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Dune Part One (2021)"
        year_hint = "2021"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        tmdb = _FakeTMDB({})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
        )
        self.assertAlmostEqual(scored[0][1], boosted[0][1], places=5)


# ── Integration: movie orchestrator with alt titles ──────────────────────────

class _FakeTMDBForMovieOrchestrator:
    """TMDB stub for testing the full movie discovery + alt title flow.

    Supports multiple movies to exercise realistic batch discovery:
      - Dune (2021) — subtitle mismatch, needs alt title boost
      - Spirited Away (2001) — Japanese primary, English alt needed
      - The Matrix (1999) — exact match, no boost needed
      - Parasite (2019) — Korean primary, English alt needed
    """

    language = "en-US"

    MOVIES = {
        "dune": [
            {"id": 438631, "title": "Dune", "year": "2021",
             "poster_path": None, "overview": "A noble family..."},
        ],
        "spirited away": [
            {"id": 129, "title": "Sen to Chihiro no Kamikakushi",
             "year": "2001", "poster_path": None, "overview": "A girl..."},
        ],
        "sen to chihiro": [
            {"id": 129, "title": "Sen to Chihiro no Kamikakushi",
             "year": "2001", "poster_path": None, "overview": "A girl..."},
        ],
        "matrix": [
            {"id": 603, "title": "The Matrix", "year": "1999",
             "poster_path": None, "overview": "A hacker..."},
        ],
        "parasite": [
            {"id": 496243, "title": "Gisaengchung", "year": "2019",
             "poster_path": None, "overview": "Greed and class..."},
        ],
        "gisaengchung": [
            {"id": 496243, "title": "Gisaengchung", "year": "2019",
             "poster_path": None, "overview": "Greed and class..."},
        ],
        "crouching tiger": [
            {"id": 146, "title": "Wo hu cang long", "year": "2000",
             "poster_path": None, "overview": "Two warriors..."},
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

    def search_movies_batch(self, queries, max_workers=8,
                            progress_callback=None):
        results = []
        for i, (query, year) in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append(
                self.search_with_fallback(query, self.search_movie, year=year))
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
                tmdb, root,
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
            state.confidence, AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, "
            f"got {state.confidence:.2f}",
        )
        self.assertTrue(state.checked, "Should be auto-checked")

    def test_matrix_exact_match_no_boost_needed(self):
        """The.Matrix.1999 should auto-accept without needing alt titles."""
        states = self._discover(["The.Matrix.1999.1080p.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 603)
        self.assertGreaterEqual(state.confidence, AUTO_ACCEPT_THRESHOLD)
        self.assertTrue(state.checked)

    def test_spirited_away_english_folder_matches_japanese_primary(self):
        """Spirited.Away.2001 should match the Japanese-titled TMDB entry
        via English alt title."""
        states = self._discover(["Spirited.Away.2001.1080p.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 129)
        self.assertGreaterEqual(
            state.confidence, AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, "
            f"got {state.confidence:.2f}",
        )

    def test_parasite_english_folder_matches_korean_primary(self):
        """Parasite.2019 should match the Korean-titled TMDB entry
        via English alt title."""
        states = self._discover(["Parasite.2019.2160p.UHD.BluRay"])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 496243)
        self.assertGreaterEqual(
            state.confidence, AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, "
            f"got {state.confidence:.2f}",
        )

    def test_crouching_tiger_english_folder(self):
        """Crouching.Tiger.Hidden.Dragon.2000 should match the Mandarin
        TMDB entry via English alt title."""
        states = self._discover([
            "Crouching.Tiger.Hidden.Dragon.2000.1080p.BluRay",
        ])
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, 146)
        self.assertGreaterEqual(
            state.confidence, AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, "
            f"got {state.confidence:.2f}",
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
            self.assertEqual(matrix_state.scanner.explicit_files, [matrix_file])
            self.assertEqual(len(matrix_state.preview_items), 1)
            self.assertEqual(matrix_state.preview_items[0].original, matrix_file)


# ── Language priority tests ──────────────────────────────────────────────────

class LanguagePriorityTests(unittest.TestCase):
    """Verify that preferred_country influences alt title ordering."""

    def test_preferred_country_titles_tried(self):
        """Alt titles from the preferred country should be considered."""
        results = [
            {"id": 10, "title": "Vollkommen Anderer Titel", "year": "2020",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "My Movie (2020)"
        year_hint = "2020"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({10: [("My Movie", "US"), ("Mein Film", "DE")]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
            preferred_country="FR",
        )
        # English fallback should still boost the score
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_preferred_country_match_wins(self):
        """When the preferred country has the matching title, it should
        be found and used for boosting."""
        results = [
            {"id": 20, "title": "Vollkommen Anderer Titel", "year": "2020",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Le Titre Français (2020)"
        year_hint = "2020"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({20: [
            ("Le Titre Français", "FR"),
            ("The French Title", "US"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
            preferred_country="FR",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_french_user_matches_french_alt_title(self):
        """A French user searching for 'Le Voyage de Chihiro' should match
        via the FR alt title of Spirited Away. Year omitted to keep primary
        score below threshold (shared 'chihiro' token would otherwise push
        the LCS high enough with the year bonus)."""
        results = [
            {"id": 129, "title": "Sen to Chihiro no Kamikakushi",
             "year": "2001", "poster_path": None, "overview": ""},
        ]
        raw_name = "Le Voyage de Chihiro"
        year_hint = None

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({129: [
            ("Spirited Away", "US"),
            ("Le Voyage de Chihiro", "FR"),
            ("Chihiros Reise ins Zauberland", "DE"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
            preferred_country="FR",
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_german_user_matches_german_alt_title(self):
        """A German user's folder 'Ziemlich beste Freunde' should match
        'Intouchables' via the DE alt title."""
        results = [
            {"id": 200, "title": "Intouchables", "year": "2011",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Ziemlich beste Freunde (2011)"
        year_hint = "2011"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({200: [
            ("The Intouchables", "US"),
            ("Ziemlich beste Freunde", "DE"),
            ("Amigos intocables", "ES"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
            preferred_country="DE",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_spanish_user_matches_spanish_tv_alt(self):
        """A Spanish user's folder 'La Casa de Papel' should match when
        the primary is the English Netflix title 'Money Heist'."""
        results = [
            {"id": 71446, "name": "Money Heist", "year": "2017",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "La Casa de Papel (2017)"
        year_hint = "2017"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({71446: [
            ("La Casa de Papel", "ES"),
            ("Haus des Geldes", "DE"),
            ("La Maison de Papier", "FR"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="name", media_type="tv",
            preferred_country="ES",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_japanese_user_anime_reverse_lookup(self):
        """A Japanese user with folder '進撃の巨人' should match
        'Attack on Titan' via JP alt title."""
        results = [
            {"id": 1429, "name": "Attack on Titan", "year": "2013",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "進撃の巨人 (2013)"
        year_hint = "2013"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({1429: [
            ("Shingeki no Kyojin", "JP"),
            ("進撃の巨人", "JP"),
            ("L'Attaque des Titans", "FR"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="name", media_type="tv",
            preferred_country="JP",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_no_preferred_country_falls_back_to_english(self):
        """When no preferred country is set, English alt titles should
        still be found as a fallback."""
        results = [
            {"id": 496243, "title": "Gisaengchung", "year": "2019",
             "poster_path": None, "overview": ""},
        ]
        raw_name = "Parasite (2019)"
        year_hint = "2019"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({496243: [
            ("Parasite", "US"),
            ("Parasita", "BR"),
        ]})
        boosted = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, tmdb,
            title_key="title", media_type="movie",
            # No preferred_country
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)


# ── Settings service tests ───────────────────────────────────────────────────

class SettingsServiceTests(unittest.TestCase):
    """Test the SettingsService persistence layer."""

    def test_default_match_language(self):
        from plex_renamer.app.services.settings_service import SettingsService
        with TemporaryDirectory() as tmp:
            svc = SettingsService(path=Path(tmp) / "settings.json")
            self.assertEqual(svc.match_language, "en-US")
            self.assertEqual(svc.match_country, "US")

    def test_set_and_persist_language(self):
        from plex_renamer.app.services.settings_service import SettingsService
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            svc = SettingsService(path=path)
            svc.match_language = "fr-FR"
            self.assertEqual(svc.match_language, "fr-FR")
            self.assertEqual(svc.match_country, "FR")

            # Reload from disk — should persist
            svc2 = SettingsService(path=path)
            self.assertEqual(svc2.match_language, "fr-FR")

    def test_corrupt_file_uses_defaults(self):
        from plex_renamer.app.services.settings_service import SettingsService
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("not valid json!!!")
            svc = SettingsService(path=path)
            self.assertEqual(svc.match_language, "en-US")


if __name__ == "__main__":
    unittest.main()
