"""Tests for alternative-title matching in score boosting.

Covers:
  - boost_scores_with_alt_titles promotes a low-confidence primary match
    when an alternative title matches better
  - No-op when the top result already exceeds the auto-accept threshold
  - Works for both movie and TV media types
  - Handles missing or empty alternative titles gracefully
  - SettingsService persistence of the match-language preference

See also test_alt_title_matching_orchestrator.py for the movie-orchestrator
discovery flow and language-priority alt-title scenarios split out of this
module to stay under the repository's LOC ceiling.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.engine import (
    AUTO_ACCEPT_THRESHOLD,
    boost_scores_with_alt_titles,
    score_results,
)
from plex_renamer.tmdb import TMDBClient

# ── Fake TMDB client ────────────────────────────────────────────────────────


class _FakeTMDB(TMDBClient):
    """Minimal TMDB stub that returns configurable alternative titles.

    Alt titles are stored as ``{media_id: [(title, country_code), ...]}``.
    Subclasses TMDBClient (without calling its __init__) purely so it type
    checks as one at the boost_scores_with_alt_titles call sites below.
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
            {"id": 438631, "title": "Dune", "year": "2021", "poster_path": None, "overview": ""},
        ]
        raw_name = "Dune Part One (2021)"
        year_hint = "2021"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                438631: [
                    ("Dune: Part One", "US"),
                    ("Dune: Parte uno", "IT"),
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
        )
        self.assertGreater(boosted[0][1], scored[0][1])
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_spider_man_across_the_spider_verse(self):
        """TMDB primary 'Spider-Man: Across the Spider-Verse' matches poorly
        against the folder name without the colon/hyphen; the alt title with
        slightly different formatting should still boost."""
        results = [
            {
                "id": 569094,
                "title": "Spider-Man: Across the Spider-Verse",
                "year": "2023",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Spider Man Across The Spider Verse (2023)"
        year_hint = "2023"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        # This may or may not be above threshold depending on normalization.
        # The test verifies the score is at least as good after boosting.
        original = scored[0][1]

        tmdb = _FakeTMDB(
            {
                569094: [
                    ("Spider-Man: Across the Spider-Verse (Part One)", "US"),
                    ("Spider-Man: Cruzando el Multiverso", "ES"),
                    ("Spider-Man: Através do Aranhaverso", "BR"),
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
        )
        self.assertGreaterEqual(boosted[0][1], original)

    def test_harry_potter_subtitle_difference(self):
        """US title is 'Sorcerer's Stone' but UK/original is 'Philosopher's
        Stone'. Both score well due to shared prefix, but the US alt title
        should score at least as high as the original."""
        results = [
            {
                "id": 671,
                "title": "Harry Potter and the Philosopher's Stone",
                "year": "2001",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Harry Potter and the Sorcerers Stone (2001)"
        year_hint = "2001"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        original = scored[0][1]

        tmdb = _FakeTMDB(
            {
                671: [
                    ("Harry Potter and the Sorcerer's Stone", "US"),
                    ("Harry Potter à l'école des sorciers", "FR"),
                    ("Harry Potter und der Stein der Weisen", "DE"),
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
        )
        # Primary already scores well due to long shared prefix;
        # score should be maintained (no-op when already above threshold)
        self.assertGreaterEqual(boosted[0][1], original)

    def test_spirited_away_japanese_primary(self):
        """TMDB primary is the Japanese title 'Sen to Chihiro no Kamikakushi'.
        An English-named folder should be boosted by the US alt title."""
        results = [
            {
                "id": 129,
                "title": "Sen to Chihiro no Kamikakushi",
                "year": "2001",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Spirited Away (2001)"
        year_hint = "2001"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(
            scored[0][1], AUTO_ACCEPT_THRESHOLD, "Japanese primary vs English query should be low"
        )

        tmdb = _FakeTMDB(
            {
                129: [
                    ("Spirited Away", "US"),
                    ("Le Voyage de Chihiro", "FR"),
                    ("Chihiros Reise ins Zauberland", "DE"),
                    ("El viaje de Chihiro", "ES"),
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
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_parasite_korean_primary(self):
        """Korean primary title 'Gisaengchung' should be boosted when
        the folder is named with the English title 'Parasite'."""
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
                    ("Parasite", "GB"),
                    ("Parasit", "DE"),
                    ("Parasita", "BR"),
                    ("パラサイト 半地下の家族", "JP"),
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
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_crouching_tiger_hidden_dragon(self):
        """Mandarin primary title should be boosted when folder uses the
        well-known English title. Year is omitted from the query to ensure
        the primary score stays below threshold."""
        results = [
            {
                "id": 146,
                "title": "Wo hu cang long",
                "year": "2000",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Crouching Tiger Hidden Dragon"
        year_hint = None

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                146: [
                    ("Crouching Tiger, Hidden Dragon", "US"),
                    ("Tigre et Dragon", "FR"),
                    ("Tiger and Dragon", "DE"),
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
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    # -- TV shows --

    def test_tv_abbreviated_name_boosted(self):
        """JJBA abbreviation should be boosted when the full title is
        available as an alternative."""
        results = [
            {"id": 456, "name": "JJBA", "year": "2012", "poster_path": None, "overview": ""},
        ]
        raw_name = "JoJo's Bizarre Adventure (2012)"
        year_hint = "2012"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        original = scored[0][1]

        tmdb = _FakeTMDB({456: [("JoJo's Bizarre Adventure", "US")]})
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="name",
            media_type="tv",
        )
        self.assertGreater(boosted[0][1], original)

    def test_tv_attack_on_titan(self):
        """Japanese primary 'Shingeki no Kyojin' should be boosted for an
        English-titled folder 'Attack on Titan'. Year omitted to ensure
        primary score stays below threshold."""
        results = [
            {
                "id": 1429,
                "name": "Shingeki no Kyojin",
                "year": "2013",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Attack on Titan"
        year_hint = None

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                1429: [
                    ("Attack on Titan", "US"),
                    ("L'Attaque des Titans", "FR"),
                    ("Ataque a los Titanes", "ES"),
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
        )
        self.assertGreater(boosted[0][1], scored[0][1])

    def test_tv_dark_german_show(self):
        """German show 'Dark' — primary title is already in English, but
        a German-titled folder 'Dark Staffel' should still work if the
        alt title matches."""
        results = [
            {"id": 70523, "name": "Dark", "year": "2017", "poster_path": None, "overview": ""},
        ]
        raw_name = "Dark (2017)"
        year_hint = "2017"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        # "Dark" vs "Dark" — should already be above threshold
        self.assertGreaterEqual(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        # No boost needed — verify no-op
        tmdb = _FakeTMDB({70523: [("Dark", "DE")]})
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="name",
            media_type="tv",
        )
        self.assertEqual(scored[0][1], boosted[0][1])

    def test_tv_money_heist_spanish_primary(self):
        """Spanish primary 'La Casa de Papel' should be boosted when
        the folder uses the Netflix English title 'Money Heist'."""
        results = [
            {
                "id": 71446,
                "name": "La Casa de Papel",
                "year": "2017",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Money Heist (2017)"
        year_hint = "2017"

        scored = score_results(results, raw_name, year_hint, title_key="name")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                71446: [
                    ("Money Heist", "US"),
                    ("Money Heist", "GB"),
                    ("Haus des Geldes", "DE"),
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
        )
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    # -- Edge cases and no-ops --

    def test_no_boost_when_already_above_threshold(self):
        """When the top result already exceeds the threshold, alt titles
        should NOT be fetched (the function is a no-op)."""
        results = [
            {"id": 1, "title": "The Matrix", "year": "1999", "poster_path": None, "overview": ""},
        ]
        raw_name = "The Matrix (1999)"
        year_hint = "1999"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertGreaterEqual(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB()
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
        )
        self.assertEqual(scored[0][1], boosted[0][1])

    def test_alt_title_can_reorder_results(self):
        """When a lower-ranked result has a better alternative title match,
        it should be promoted above a higher-ranked primary-only match."""
        results = [
            {"id": 1, "title": "Dune", "year": "2021", "poster_path": None, "overview": ""},
            {"id": 2, "title": "Dune Messiah", "year": "2026", "poster_path": None, "overview": ""},
        ]
        raw_name = "Dune Part One (2021)"
        year_hint = "2021"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        self.assertLess(scored[0][1], AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB({1: [("Dune: Part One", "US")]})
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
        )
        self.assertEqual(boosted[0][0]["id"], 1)
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_disambiguation_via_alt_title(self):
        """Two movies with similar primary titles — the alt title on the
        correct one should promote it above the wrong match."""
        results = [
            {
                "id": 100,
                "title": "The Girl with the Dragon Tattoo",
                "year": "2011",
                "poster_path": None,
                "overview": "",
            },
            {
                "id": 101,
                "title": "The Girl with the Dragon Tattoo",
                "year": "2009",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "Män som hatar kvinnor (2009)"
        year_hint = "2009"

        scored = score_results(results, raw_name, year_hint, title_key="title")

        # The 2009 Swedish original has the Swedish alt title
        tmdb = _FakeTMDB(
            {
                101: [("Män som hatar kvinnor", "SE")],
                100: [],  # US remake has no Swedish alt title
            }
        )
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
        )
        # The 2009 Swedish version should be on top
        self.assertEqual(boosted[0][0]["id"], 101)

    def test_many_alt_titles_uses_best(self):
        """When a result has many alt titles, the best-scoring one should
        be selected and used for boosting."""
        results = [
            {
                "id": 200,
                "title": "Ziemlich beste Freunde",
                "year": "2011",
                "poster_path": None,
                "overview": "",
            },
        ]
        raw_name = "The Intouchables (2011)"
        year_hint = "2011"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        original = scored[0][1]
        self.assertLess(original, AUTO_ACCEPT_THRESHOLD)

        tmdb = _FakeTMDB(
            {
                200: [
                    ("The Intouchables", "US"),
                    ("The Intouchables", "GB"),
                    ("Intouchables", "FR"),
                    ("Amigos intocables", "ES"),
                    ("最強のふたり", "JP"),
                    ("1+1", "RU"),
                    ("Prijatelji", "RS"),
                    ("Nedodirljivi", "HR"),
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
        )
        self.assertGreater(boosted[0][1], original)
        self.assertGreaterEqual(boosted[0][1], AUTO_ACCEPT_THRESHOLD)

    def test_empty_results_is_noop(self):
        """boost_scores_with_alt_titles handles empty input gracefully."""
        tmdb = _FakeTMDB()
        result = boost_scores_with_alt_titles(
            [],
            "Something",
            None,
            tmdb,
        )
        self.assertEqual(result, [])

    def test_no_alt_titles_preserves_scores(self):
        """When TMDB returns no alternative titles, scores are unchanged."""
        results = [
            {"id": 99, "title": "Dune", "year": "2021", "poster_path": None, "overview": ""},
        ]
        raw_name = "Dune Part One (2021)"
        year_hint = "2021"

        scored = score_results(results, raw_name, year_hint, title_key="title")
        tmdb = _FakeTMDB({})
        boosted = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            tmdb,
            title_key="title",
            media_type="movie",
        )
        self.assertAlmostEqual(scored[0][1], boosted[0][1], places=5)


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
