from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from PIL import Image

from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.refresh_policy_service import RefreshPolicyService
from plex_renamer.tmdb import TMDBClient, _HTTP_POOL_CONNECTIONS, _HTTP_POOL_MAXSIZE


class TMDBClientTests(unittest.TestCase):
    def test_tmdb_client_uses_expanded_connection_pool_without_changing_rate_limit(self):
        client = TMDBClient("dummy-api-key")
        try:
            api_adapter = client._session.get_adapter("https://api.themoviedb.org/3/configuration")
            image_adapter = client._session.get_adapter("https://image.tmdb.org/t/p/w500/test.jpg")

            self.assertEqual(api_adapter._pool_connections, _HTTP_POOL_CONNECTIONS)
            self.assertEqual(api_adapter._pool_maxsize, _HTTP_POOL_MAXSIZE)
            self.assertEqual(image_adapter._pool_connections, _HTTP_POOL_CONNECTIONS)
            self.assertEqual(image_adapter._pool_maxsize, _HTTP_POOL_MAXSIZE)
            self.assertEqual(client._rate_limiter._rate, 35.0)
        finally:
            client._session.close()

    def test_fetch_poster_reuses_persisted_poster_across_client_instances(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")

            first_client = TMDBClient("dummy-api-key", cache_service=cache)
            first_client._get_safe = MagicMock(return_value={"poster_path": "/poster.jpg"})
            first_client.fetch_image = MagicMock(return_value=Image.new("RGB", (96, 144), color="red"))

            first_result = first_client.fetch_poster(123, media_type="movie", target_width=96)

            self.assertIsNotNone(first_result)
            first_client._get_safe.assert_called_once_with("/movie/123")
            first_client.fetch_image.assert_called_once_with("/poster.jpg", 96)
            first_client._session.close()

            second_client = TMDBClient("dummy-api-key", cache_service=cache)
            second_client._get_safe = MagicMock(side_effect=AssertionError("metadata should not be fetched"))
            second_client.fetch_image = MagicMock(side_effect=AssertionError("poster should not be redownloaded"))

            second_result = second_client.fetch_poster(123, media_type="movie", target_width=96)

            self.assertIsNotNone(second_result)
            self.assertEqual(second_result.size, (96, 144))
            second_client._session.close()

    def test_fetch_image_reuses_persisted_source_across_widths(self):
        png_buffer = io.BytesIO()
        Image.new("RGB", (200, 300), color="blue").save(png_buffer, format="PNG")
        payload = png_buffer.getvalue()

        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")

            first_client = TMDBClient("dummy-api-key", cache_service=cache)
            response = MagicMock()
            response.content = payload
            first_client._session.get = MagicMock(return_value=response)

            first_result = first_client.fetch_image("/poster.jpg", target_width=96)

            self.assertIsNotNone(first_result)
            self.assertEqual(first_result.size, (96, 144))
            first_client._session.get.assert_called_once()
            first_client._session.close()

            second_client = TMDBClient("dummy-api-key", cache_service=cache)
            second_client._session.get = MagicMock(side_effect=AssertionError("source image should not be redownloaded"))

            second_result = second_client.fetch_image("/poster.jpg", target_width=42)

            self.assertIsNotNone(second_result)
            self.assertEqual(second_result.size, (42, 63))
            second_client._session.close()

    def test_get_tv_details_reuses_persisted_details_across_client_instances(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")
            refresh_policy = RefreshPolicyService()

            first_client = TMDBClient(
                "dummy-api-key",
                cache_service=cache,
                refresh_policy=refresh_policy,
            )
            first_client._get_safe = MagicMock(return_value={"id": 321, "name": "Andor", "status": "Ended"})

            first_result = first_client.get_tv_details(321)

            self.assertEqual(first_result["name"], "Andor")
            first_client._get_safe.assert_called_once_with("/tv/321")
            first_client._session.close()

            second_client = TMDBClient(
                "dummy-api-key",
                cache_service=cache,
                refresh_policy=refresh_policy,
            )
            second_client._get_safe = MagicMock(side_effect=AssertionError("details should not be refetched"))

            second_result = second_client.get_tv_details(321)

            self.assertEqual(second_result["name"], "Andor")
            second_client._session.close()

    def test_get_season_reuses_persisted_season_with_int_episode_keys(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")
            refresh_policy = RefreshPolicyService()
            season_payload = {
                "poster_path": "/season.jpg",
                "episodes": [
                    {
                        "episode_number": 1,
                        "name": "Pilot",
                        "overview": "Episode overview",
                        "air_date": "2024-01-01",
                        "vote_average": 8.5,
                        "vote_count": 100,
                        "runtime": 42,
                        "still_path": "/still.jpg",
                        "guest_stars": [{"name": "Guest", "character": "Visitor"}],
                        "crew": [{"job": "Director", "name": "Director Name"}],
                    }
                ],
            }

            first_client = TMDBClient(
                "dummy-api-key",
                cache_service=cache,
                refresh_policy=refresh_policy,
            )
            first_client._get_safe = MagicMock(return_value=season_payload)

            first_result = first_client.get_season(555, 1)

            self.assertEqual(first_result["titles"][1], "Pilot")
            first_client._get_safe.assert_called_once_with("/tv/555/season/1")
            first_client._session.close()

            second_client = TMDBClient(
                "dummy-api-key",
                cache_service=cache,
                refresh_policy=refresh_policy,
            )
            second_client._get_safe = MagicMock(side_effect=AssertionError("season should not be refetched"))

            second_result = second_client.get_season(555, 1)

            self.assertEqual(list(second_result["titles"].keys()), [1])
            self.assertEqual(second_result["episodes"][1]["name"], "Pilot")
            second_client._session.close()

    def test_search_tv_maps_results_to_client_shape(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(return_value={
            "results": [
                {
                    "id": 77,
                    "name": "Andor",
                    "first_air_date": "2022-09-21",
                    "poster_path": "/andor.jpg",
                    "overview": "Rebel spy drama.",
                }
            ]
        })

        results = client.search_tv("Andor", year="2022")

        self.assertEqual(results, [{
            "id": 77,
            "name": "Andor",
            "year": "2022",
            "poster_path": "/andor.jpg",
            "overview": "Rebel spy drama.",
        }])
        client._get_safe.assert_called_once_with("/search/tv", {"query": "Andor", "first_air_date_year": "2022"})
        client._session.close()

    def test_search_movie_maps_results_to_client_shape(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(return_value={
            "results": [
                {
                    "id": 11,
                    "title": "The Matrix",
                    "release_date": "1999-03-31",
                    "poster_path": "/matrix.jpg",
                    "overview": "Simulation sci-fi.",
                }
            ]
        })

        results = client.search_movie("The Matrix", year="1999")

        self.assertEqual(results, [{
            "id": 11,
            "title": "The Matrix",
            "year": "1999",
            "poster_path": "/matrix.jpg",
            "overview": "Simulation sci-fi.",
        }])
        client._get_safe.assert_called_once_with("/search/movie", {"query": "The Matrix", "year": "1999"})
        client._session.close()

    def test_get_season_builds_detail_panel_metadata(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(return_value={
            "poster_path": "/season.jpg",
            "episodes": [
                {
                    "episode_number": 1,
                    "name": "Pilot",
                    "overview": "Episode overview",
                    "air_date": "2024-01-01",
                    "vote_average": 8.5,
                    "vote_count": 100,
                    "runtime": 42,
                    "still_path": "/still.jpg",
                    "guest_stars": [
                        {"name": f"Guest {index}", "character": f"Character {index}"}
                        for index in range(1, 8)
                    ],
                    "crew": [
                        {"job": "Director", "name": "Director Name"},
                        {"job": "Writer", "name": "Writer Name"},
                        {"job": "Teleplay", "name": "Teleplay Name"},
                        {"job": "Story", "name": "Story Name"},
                        {"job": "Producer", "name": "Producer Name"},
                    ],
                }
            ],
        })

        result = client.get_season(555, 1)

        self.assertEqual(result["titles"][1], "Pilot")
        self.assertEqual(result["posters"][1], "/still.jpg")
        self.assertEqual(result["episodes"][1]["directors"], ["Director Name"])
        self.assertEqual(result["episodes"][1]["writers"], ["Writer Name", "Teleplay Name", "Story Name"])
        self.assertEqual(len(result["episodes"][1]["guest_stars"]), 5)
        self.assertEqual(result["season_poster_path"], "/season.jpg")
        client._session.close()

    def test_search_movies_batch_falls_back_to_yearless_results_and_reports_progress(self):
        client = TMDBClient("dummy-api-key")
        progress_events: list[tuple[int, int]] = []

        def fake_search_with_fallback(query, search_fn, **kwargs):
            year = kwargs.get("year")
            if query == "JoJo" and year == "2012":
                return []
            if query == "JoJo" and year is None:
                return [{"id": 7, "title": "JoJo", "year": "2012"}]
            if query == "Matrix" and year == "1999":
                return [{"id": 11, "title": "The Matrix", "year": "1999"}]
            return []

        client.search_with_fallback = MagicMock(side_effect=fake_search_with_fallback)

        results = client.search_movies_batch(
            [("JoJo", "2012"), ("Matrix", "1999")],
            max_workers=2,
            progress_callback=lambda done, total: progress_events.append((done, total)),
        )

        self.assertEqual(results, [
            [{"id": 7, "title": "JoJo", "year": "2012"}],
            [{"id": 11, "title": "The Matrix", "year": "1999"}],
        ])
        self.assertEqual(progress_events, [(1, 2), (2, 2)])
        client._session.close()

    def test_search_tv_batch_merges_yearless_results_without_duplicates(self):
        client = TMDBClient("dummy-api-key")

        def fake_search_with_fallback(query, search_fn, **kwargs):
            year = kwargs.get("year")
            if query == "BSG" and year == "2003":
                return [{"id": 1, "name": "Battlestar Galactica", "year": "2004"}]
            if query == "BSG" and year is None:
                return [
                    {"id": 1, "name": "Battlestar Galactica", "year": "2004"},
                    {"id": 2, "name": "Battlestar Galactica", "year": "1978"},
                ]
            return []

        client.search_with_fallback = MagicMock(side_effect=fake_search_with_fallback)

        results = client.search_tv_batch([("BSG", "2003")], max_workers=1)

        self.assertEqual(results, [[
            {"id": 1, "name": "Battlestar Galactica", "year": "2004"},
            {"id": 2, "name": "Battlestar Galactica", "year": "1978"},
        ]])
        client._session.close()

    def test_get_alternative_titles_deduplicates_and_caches_results(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(return_value={
            "titles": [
                {"title": "Spirited Away", "iso_3166_1": "US"},
                {"title": "Spirited Away", "iso_3166_1": "GB"},
                {"title": "Sen to Chihiro no kamikakushi", "iso_3166_1": "JP"},
                {"title": "", "iso_3166_1": "FR"},
            ]
        })

        first_result = client.get_alternative_titles(42, media_type="movie")
        second_result = client.get_alternative_titles(42, media_type="movie")

        self.assertEqual(first_result, [
            ("Spirited Away", "US"),
            ("Sen to Chihiro no kamikakushi", "JP"),
        ])
        self.assertEqual(second_result, first_result)
        client._get_safe.assert_called_once_with("/movie/42/alternative_titles")
        client._session.close()

    def test_search_with_fallback_trims_query_until_match(self):
        client = TMDBClient("dummy-api-key")
        attempts: list[tuple[str, str | None]] = []

        def fake_search(query, year=None):
            attempts.append((query, year))
            if query == "The Matrix":
                return [{"id": 11}]
            return []

        result = client.search_with_fallback(
            "The Matrix Reloaded",
            fake_search,
            min_words=2,
            year="1999",
        )

        self.assertEqual(result, [{"id": 11}])
        self.assertEqual(attempts, [
            ("The Matrix Reloaded", "1999"),
            ("The Matrix", "1999"),
        ])
        client._session.close()

    def test_search_with_fallback_respects_min_words(self):
        client = TMDBClient("dummy-api-key")
        attempts: list[str] = []

        def fake_search(query):
            attempts.append(query)
            return []

        result = client.search_with_fallback(
            "One Two Three",
            fake_search,
            min_words=2,
        )

        self.assertEqual(result, [])
        self.assertEqual(attempts, ["One Two Three", "One Two"])
        client._session.close()

    def test_cache_snapshot_roundtrip_restores_runtime_metadata(self):
        client = TMDBClient("dummy-api-key")
        snapshot = {
            "show_cache": {"321": {"poster_path": "/andor.jpg", "name": "Andor"}},
            "season_cache": {
                "321:1": {
                    "titles": {"1": "Pilot"},
                    "posters": {"1": "/still.jpg"},
                    "episodes": {"1": {"name": "Pilot"}},
                    "season_poster_path": "/season.jpg",
                }
            },
            "season_map_cache": {
                "321": {
                    "seasons": {
                        "1": {
                            "titles": {"1": "Pilot"},
                            "posters": {"1": "/still.jpg"},
                            "episodes": {"1": {"name": "Pilot"}},
                            "count": 1,
                            "season_poster_path": "/season.jpg",
                        }
                    },
                    "total_episodes": 1,
                }
            },
            "movie_cache": {"123": {"poster_path": "/movie.jpg", "title": "Movie"}},
        }

        client.import_cache_snapshot(snapshot, clear_existing=True)

        self.assertEqual(client.get_cached_poster_path(321), "/andor.jpg")
        self.assertEqual(client.get_cached_poster_path(123, media_type="movie"), "/movie.jpg")
        self.assertEqual(client.get_season(321, 1)["titles"][1], "Pilot")
        season_map, total_episodes = client.get_season_map(321)
        self.assertEqual(total_episodes, 1)
        self.assertEqual(season_map[1]["titles"][1], "Pilot")

        exported = client.export_cache_snapshot()

        self.assertEqual(exported["show_cache"][321]["poster_path"], "/andor.jpg")
        self.assertIn("321:1", exported["season_cache"])
        self.assertEqual(exported["movie_cache"][123]["poster_path"], "/movie.jpg")
        client._session.close()


if __name__ == "__main__":
    unittest.main()