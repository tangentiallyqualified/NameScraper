"""ShowDetails provider seam + fetch-failure-aware tiebreak (Task 8,
2026-07-10 review: TVDB-readiness and finding M-M5).

A transient TMDB failure used to read as "unaired show with zero episodes"
inside episode_count_tiebreak, handing a near-tie to the wrong show on
fabricated evidence. With the ShowDetails seam a failed fetch stays None
and the tiebreak abstains.
"""

from __future__ import annotations

import unittest

from plex_renamer.engine._batch_tv_match_policy import episode_count_tiebreak
from plex_renamer.engine.show_details import (
    SeasonSummary,
    ShowDetails,
    show_details_from_tmdb,
)


class ShowDetailsNormalizationTests(unittest.TestCase):
    def test_none_in_none_out(self):
        self.assertIsNone(show_details_from_tmdb(None))

    def test_full_payload_normalizes(self):
        details = show_details_from_tmdb(
            {
                "id": 1396,
                "name": "Breaking Bad",
                "overview": "A chemistry teacher turns to crime.",
                "poster_path": "/poster.jpg",
                "number_of_episodes": 62,
                "number_of_seasons": 5,
                "first_air_date": "2008-01-20",
                "status": "Ended",
                "seasons": [
                    {"season_number": 0, "episode_count": 9, "name": "Specials"},
                    {"season_number": 1, "episode_count": 7, "name": "Season 1"},
                ],
            }
        )
        assert details is not None
        self.assertEqual(details.id, 1396)
        self.assertEqual(details.name, "Breaking Bad")
        self.assertEqual(details.overview, "A chemistry teacher turns to crime.")
        self.assertEqual(details.poster_path, "/poster.jpg")
        self.assertEqual(details.number_of_episodes, 62)
        self.assertEqual(details.number_of_seasons, 5)
        self.assertEqual(details.first_air_date, "2008-01-20")
        self.assertFalse(details.unaired)
        self.assertEqual(
            details.seasons,
            (SeasonSummary(0, 9, "Specials"), SeasonSummary(1, 7, "Season 1")),
        )

    def test_unaired_mapping(self):
        planned = show_details_from_tmdb(
            {
                "id": 1,
                "first_air_date": "2027-01-01",
                "status": "Planned",
            }
        )
        assert planned is not None
        self.assertTrue(planned.unaired)
        no_date = show_details_from_tmdb({"id": 2, "status": "Ended"})
        assert no_date is not None
        self.assertTrue(no_date.unaired)

    def test_empty_first_air_date_normalizes_to_none(self):
        details = show_details_from_tmdb({"first_air_date": ""})
        assert details is not None

        self.assertIsNone(details.first_air_date)
        self.assertTrue(details.unaired)

    def test_empty_payload_is_zeroes_not_none(self):
        details = show_details_from_tmdb({})
        assert details is not None
        self.assertIsInstance(details, ShowDetails)
        self.assertIsNone(details.id)
        self.assertEqual(details.name, "")
        self.assertEqual(details.overview, "")
        self.assertIsNone(details.poster_path)
        self.assertIsNone(details.first_air_date)
        self.assertEqual(details.number_of_episodes, 0)
        self.assertTrue(details.unaired)

    def test_wrong_scalar_types_default_and_malformed_seasons_are_ignored(self):
        details = show_details_from_tmdb(
            {
                "id": "1396",
                "name": 1396,
                "overview": ["not", "text"],
                "poster_path": 123,
                "number_of_episodes": "62",
                "number_of_seasons": False,
                "first_air_date": 2008,
                "status": ["Ended"],
                "seasons": [
                    None,
                    "Season 1",
                    {"season_number": 1, "episode_count": 7, "name": 1},
                    {"season_number": 2, "episode_count": 8},
                ],
            }
        )
        assert details is not None

        self.assertIsNone(details.id)
        self.assertEqual(details.name, "")
        self.assertEqual(details.overview, "")
        self.assertIsNone(details.poster_path)
        self.assertEqual(details.number_of_episodes, 0)
        self.assertEqual(details.number_of_seasons, 0)
        self.assertIsNone(details.first_air_date)
        self.assertTrue(details.unaired)
        self.assertEqual(
            details.seasons,
            (SeasonSummary(1, 7, ""), SeasonSummary(2, 8, "")),
        )


class _StubTMDB:
    def __init__(self, details_by_id):
        self._details = details_by_id

    def get_tv_details(self, show_id):
        return self._details.get(show_id)


class TiebreakAbstainsOnFetchFailureTests(unittest.TestCase):
    def test_failed_detail_fetch_abstains_instead_of_ranking_zeroes(self):
        """When any near-tie contender's details fail to load, the tiebreak
        must keep the original winner and report no discrimination, not rank
        the failed candidate as an unaired zero-episode show."""
        show_a = {"id": 1, "name": "Show", "year": "2010"}
        show_b = {"id": 2, "name": "Show", "year": "2012"}
        scored = [(show_a, 1.0), (show_b, 1.0)]
        # show_a's fetch fails (None); show_b has a perfect count match.
        tmdb = _StubTMDB(
            {
                2: {"number_of_episodes": 13, "first_air_date": "2012-01-01"},
            }
        )

        best, score, discriminated = episode_count_tiebreak(
            tmdb,
            scored,
            file_count=13,
        )

        self.assertIs(best, show_a, "abstention keeps the original winner")
        self.assertEqual(score, 1.0)
        self.assertFalse(discriminated)

    def test_tiebreak_still_ranks_when_all_fetches_succeed(self):
        show_a = {"id": 1, "name": "Show", "year": "2010"}
        show_b = {"id": 2, "name": "Show", "year": "2012"}
        scored = [(show_a, 1.0), (show_b, 1.0)]
        tmdb = _StubTMDB(
            {
                1: {"number_of_episodes": 190, "first_air_date": "2010-01-01"},
                2: {"number_of_episodes": 13, "first_air_date": "2012-01-01"},
            }
        )

        best, _score, discriminated = episode_count_tiebreak(
            tmdb,
            scored,
            file_count=13,
        )

        self.assertIs(best, show_b)
        self.assertTrue(discriminated)


if __name__ == "__main__":
    unittest.main()
