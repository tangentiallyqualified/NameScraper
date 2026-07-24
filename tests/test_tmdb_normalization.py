from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from plex_renamer.tmdb import TMDBClient


class _StubTMDBClient(TMDBClient):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__("dummy-api-key")
        self._payload = payload
        self.fetch_calls: list[tuple[str, dict[str, object] | None]] = []

    def _get_safe(
        self,
        path: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        self.fetch_calls.append((path, params))
        return self._payload

    def close(self) -> None:
        self._session.close()


class TMDBNormalizationTests(unittest.TestCase):
    def test_search_tv_maps_results_to_client_shape(self):
        client = _StubTMDBClient(
            {
                "results": [
                    {
                        "id": 77,
                        "name": "Andor",
                        "first_air_date": "2022-09-21",
                        "poster_path": "/andor.jpg",
                        "overview": "Rebel spy drama.",
                    }
                ]
            }
        )

        results = client.search_tv("Andor", year="2022")

        self.assertEqual(
            results,
            [
                {
                    "id": 77,
                    "name": "Andor",
                    "year": "2022",
                    "poster_path": "/andor.jpg",
                    "overview": "Rebel spy drama.",
                }
            ],
        )
        self.assertEqual(
            client.fetch_calls,
            [("/search/tv", {"query": "Andor", "first_air_date_year": "2022"})],
        )
        client.close()

    def test_search_tv_normalizes_malformed_scalar_fields(self):
        client = _StubTMDBClient(
            {
                "results": [
                    {
                        "id": True,
                        "name": ["Andor"],
                        "first_air_date": 2022,
                        "poster_path": 42,
                        "overview": {},
                    },
                    "not-a-record",
                ]
            }
        )

        results = client.search_tv("Andor")

        self.assertEqual(
            results,
            [
                {
                    "id": None,
                    "name": "",
                    "year": "",
                    "poster_path": None,
                    "overview": "",
                }
            ],
        )
        client.close()

    def test_search_movie_maps_results_to_client_shape(self):
        client = _StubTMDBClient(
            {
                "results": [
                    {
                        "id": 11,
                        "title": "The Matrix",
                        "release_date": "1999-03-31",
                        "poster_path": "/matrix.jpg",
                        "overview": "Simulation sci-fi.",
                    }
                ]
            }
        )

        results = client.search_movie("The Matrix", year="1999")

        self.assertEqual(
            results,
            [
                {
                    "id": 11,
                    "title": "The Matrix",
                    "year": "1999",
                    "poster_path": "/matrix.jpg",
                    "overview": "Simulation sci-fi.",
                }
            ],
        )
        self.assertEqual(
            client.fetch_calls,
            [("/search/movie", {"query": "The Matrix", "year": "1999"})],
        )
        client.close()

    def test_search_movie_normalizes_malformed_scalar_fields(self):
        client = _StubTMDBClient(
            {
                "results": [
                    {
                        "id": False,
                        "title": {"unexpected": "title"},
                        "release_date": ["1", "9", "9", "9"],
                        "poster_path": 11,
                        "overview": ["unexpected"],
                    },
                    None,
                ]
            }
        )

        results = client.search_movie("The Matrix")

        self.assertEqual(
            results,
            [
                {
                    "id": None,
                    "title": "",
                    "year": "",
                    "poster_path": None,
                    "overview": "",
                }
            ],
        )
        client.close()

    def test_pillow_floor_supports_resampling_enum_used_by_image_resize(self):
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertIn("Pillow>=9.1", project["project"]["dependencies"])
