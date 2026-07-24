# pyright: reportPrivateUsage=false
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
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from test_alt_title_matching import _FakeTMDB

from plex_renamer import engine
from plex_renamer.engine import AUTO_ACCEPT_THRESHOLD, BatchMovieOrchestrator, ScanState
from plex_renamer.engine._movie_scanner import MovieScanner
from plex_renamer.metadata_types import MediaInfo
from plex_renamer.tmdb import TMDBClient

SearchResult = MediaInfo

_score_results = engine.score_results
_boost_scores = engine.boost_scores_with_alt_titles


def _discover_movies(orchestrator: BatchMovieOrchestrator) -> list[ScanState]:
    return orchestrator.discover_movies()  # pyright: ignore[reportUnknownMemberType]


def _scan_movie(orchestrator: BatchMovieOrchestrator, state: ScanState) -> None:
    orchestrator.scan_movie(state)  # pyright: ignore[reportUnknownMemberType]


def _result(
    media_id: int,
    title: str,
    year: str,
    *,
    key: str = "title",
    overview: str = "",
) -> SearchResult:
    return {"id": media_id, key: title, "year": year, "poster_path": None, "overview": overview}


# ── Integration: movie orchestrator with alt titles ──────────────────────────


class _FakeTMDBForMovieOrchestrator:
    """TMDB stub for testing the full movie discovery + alt title flow.

    Not a real TMDBClient; construction sites cast it to one. Supports
    multiple movies to exercise realistic batch discovery:
      - Dune (2021) — subtitle mismatch, needs alt title boost
      - Spirited Away (2001) — Japanese primary, English alt needed
      - The Matrix (1999) — exact match, no boost needed
      - Parasite (2019) — Korean primary, English alt needed
    """

    language = "en-US"

    MOVIES: dict[str, list[SearchResult]] = {
        "dune": [_result(438631, "Dune", "2021", overview="A noble family...")],
        "spirited away": [
            _result(129, "Sen to Chihiro no Kamikakushi", "2001", overview="A girl...")
        ],
        "sen to chihiro": [
            _result(129, "Sen to Chihiro no Kamikakushi", "2001", overview="A girl...")
        ],
        "matrix": [_result(603, "The Matrix", "1999", overview="A hacker...")],
        "parasite": [_result(496243, "Gisaengchung", "2019", overview="Greed and class...")],
        "gisaengchung": [_result(496243, "Gisaengchung", "2019", overview="Greed and class...")],
        "crouching tiger": [_result(146, "Wo hu cang long", "2000", overview="Two warriors...")],
    }

    ALT_TITLES: dict[int, list[tuple[str, str]]] = {
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

    def search_movie(self, query: str, year: str | None = None) -> list[SearchResult]:
        q = query.lower()
        for movie_key, results in self.MOVIES.items():
            if movie_key in q:
                return list(results)
        return []

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable[..., list[SearchResult]],
        **kwargs: object,
    ) -> list[SearchResult]:
        words = query.split()
        for n in range(len(words), 0, -1):
            attempt = " ".join(words[:n])
            results = search_fn(attempt, **kwargs)
            if results:
                return results
        return []

    def search_movies_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[list[SearchResult]]:
        results: list[list[SearchResult]] = []
        for i, (query, year) in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append(self.search_with_fallback(query, self.search_movie, year=year))
        return results

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        return self.ALT_TITLES.get(media_id, [])


class MovieOrchestratorAltTitleTests(unittest.TestCase):
    """The movie orchestrator should use alt titles to boost low-confidence
    matches during discovery."""

    def _discover(self, folder_names: list[str]) -> list[ScanState]:
        """Helper: create temp dirs and run movie discovery."""
        from plex_renamer.app.services import MovieLibraryDiscoveryService

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in folder_names:
                folder = root / name
                folder.mkdir()
                (folder / f"{name.split('.')[0]}.mkv").write_text("x")

            tmdb = cast(TMDBClient, _FakeTMDBForMovieOrchestrator())
            orchestrator = BatchMovieOrchestrator(
                tmdb,
                root,
                discovery_service=MovieLibraryDiscoveryService(),
            )
            return _discover_movies(orchestrator)

    def _assert_single_confident_match(self, states: list[ScanState], show_id: int) -> ScanState:
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.show_id, show_id)
        self.assertGreaterEqual(
            state.confidence,
            AUTO_ACCEPT_THRESHOLD,
            f"Expected confidence >= {AUTO_ACCEPT_THRESHOLD}, got {state.confidence:.2f}",
        )
        return state

    def test_dune_part_one_matched_with_high_confidence(self) -> None:
        """Dune.Part.One.2021 folder should auto-accept via alt title boost."""
        states = self._discover(["Dune.Part.One.2021.2160p.UHD.BluRay"])
        state = self._assert_single_confident_match(states, 438631)
        self.assertFalse(state.checked, "Matched results start unchecked until explicitly queued")

    def test_matrix_exact_match_no_boost_needed(self) -> None:
        """The.Matrix.1999 should auto-accept without needing alt titles."""
        states = self._discover(["The.Matrix.1999.1080p.BluRay"])
        state = self._assert_single_confident_match(states, 603)
        self.assertFalse(state.checked)

    def test_spirited_away_english_folder_matches_japanese_primary(self) -> None:
        """Spirited.Away.2001 should match the Japanese-titled TMDB entry
        via English alt title."""
        states = self._discover(["Spirited.Away.2001.1080p.BluRay"])
        self._assert_single_confident_match(states, 129)

    def test_parasite_english_folder_matches_korean_primary(self) -> None:
        """Parasite.2019 should match the Korean-titled TMDB entry
        via English alt title."""
        states = self._discover(["Parasite.2019.2160p.UHD.BluRay"])
        self._assert_single_confident_match(states, 496243)

    def test_crouching_tiger_english_folder(self) -> None:
        """Crouching.Tiger.Hidden.Dragon.2000 should match the Mandarin
        TMDB entry via English alt title."""
        states = self._discover(["Crouching.Tiger.Hidden.Dragon.2000.1080p.BluRay"])
        self._assert_single_confident_match(states, 146)

    def test_multi_movie_folder_scan_uses_only_selected_source_file(self) -> None:
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

            tmdb = cast(TMDBClient, _FakeTMDBForMovieOrchestrator())
            orchestrator = BatchMovieOrchestrator(
                tmdb,
                root,
                discovery_service=MovieLibraryDiscoveryService(),
            )

            states = _discover_movies(orchestrator)
            self.assertEqual(len(states), 3)

            matrix_state = next(state for state in states if state.show_id == 603)
            self.assertEqual(matrix_state.source_file, matrix_file)

            _scan_movie(orchestrator, matrix_state)

            self.assertTrue(matrix_state.scanned)
            scanner = matrix_state.scanner
            assert isinstance(scanner, MovieScanner)
            self.assertEqual(scanner.explicit_files, [matrix_file])
            self.assertEqual(len(matrix_state.preview_items), 1)
            self.assertEqual(matrix_state.preview_items[0].original, matrix_file)


# ── Language priority tests ──────────────────────────────────────────────────


class LanguagePriorityTests(unittest.TestCase):
    """Verify that preferred_country influences alt title ordering."""

    def test_preferred_country_titles_tried(self) -> None:
        """Alt titles from the preferred country should be considered."""
        results = [_result(10, "Vollkommen Anderer Titel", "2020")]
        raw_name = "My Movie (2020)"
        year_hint = "2020"

        scored = _score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({10: [("My Movie", "US"), ("Mein Film", "DE")]})
        boosted = _boost_scores(
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

    def test_preferred_country_match_wins(self) -> None:
        """When the preferred country has the matching title, it should
        be found and used for boosting."""
        results = [_result(20, "Vollkommen Anderer Titel", "2020")]
        raw_name = "Le Titre Français (2020)"
        year_hint = "2020"

        scored = _score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                20: [
                    ("Le Titre Français", "FR"),
                    ("The French Title", "US"),
                ]
            }
        )
        boosted = _boost_scores(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="FR",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_french_user_matches_french_alt_title(self) -> None:
        """A French user searching for 'Le Voyage de Chihiro' should match
        via the FR alt title of Spirited Away. Year omitted to keep primary
        score below threshold (shared 'chihiro' token would otherwise push
        the LCS high enough with the year bonus)."""
        results = [_result(129, "Sen to Chihiro no Kamikakushi", "2001")]
        raw_name = "Le Voyage de Chihiro"
        year_hint = None

        scored = _score_results(results, raw_name, year_hint, title_key="title")
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
        boosted = _boost_scores(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="FR",
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_german_user_matches_german_alt_title(self) -> None:
        """A German user's folder 'Ziemlich beste Freunde' should match
        'Intouchables' via the DE alt title."""
        results = [_result(200, "Intouchables", "2011")]
        raw_name = "Ziemlich beste Freunde (2011)"
        year_hint = "2011"

        scored = _score_results(results, raw_name, year_hint, title_key="title")
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
        boosted = _boost_scores(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
            preferred_country="DE",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_spanish_user_matches_spanish_tv_alt(self) -> None:
        """A Spanish user's folder 'La Casa de Papel' should match when
        the primary is the English Netflix title 'Money Heist'."""
        results = [_result(71446, "Money Heist", "2017", key="name")]
        raw_name = "La Casa de Papel (2017)"
        year_hint = "2017"

        scored = _score_results(results, raw_name, year_hint, title_key="name")
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
        boosted = _boost_scores(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="name",
            media_type="tv",
            preferred_country="ES",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_japanese_user_anime_reverse_lookup(self) -> None:
        """A Japanese user with folder '進撃の巨人' should match
        'Attack on Titan' via JP alt title."""
        results = [_result(1429, "Attack on Titan", "2013", key="name")]
        raw_name = "進撃の巨人 (2013)"
        year_hint = "2013"

        scored = _score_results(results, raw_name, year_hint, title_key="name")
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
        boosted = _boost_scores(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="name",
            media_type="tv",
            preferred_country="JP",
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_no_preferred_country_falls_back_to_english(self) -> None:
        """When no preferred country is set, English alt titles should
        still be found as a fallback."""
        results = [_result(496243, "Gisaengchung", "2019")]
        raw_name = "Parasite (2019)"
        year_hint = "2019"

        scored = _score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                496243: [
                    ("Parasite", "US"),
                    ("Parasita", "BR"),
                ]
            }
        )
        boosted = _boost_scores(
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
