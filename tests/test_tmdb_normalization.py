from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from plex_renamer.tmdb import TMDBClient


class TMDBNormalizationTests(unittest.TestCase):
    def test_search_tv_maps_results_to_client_shape(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(
            return_value={
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
        client._get_safe.assert_called_once_with(
            "/search/tv", {"query": "Andor", "first_air_date_year": "2022"}
        )
        client._session.close()

    def test_search_tv_normalizes_malformed_scalar_fields(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(
            return_value={
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
        client._session.close()

    def test_search_movie_maps_results_to_client_shape(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(
            return_value={
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
        client._get_safe.assert_called_once_with(
            "/search/movie", {"query": "The Matrix", "year": "1999"}
        )
        client._session.close()

    def test_search_movie_normalizes_malformed_scalar_fields(self):
        client = TMDBClient("dummy-api-key")
        client._get_safe = MagicMock(
            return_value={
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
        client._session.close()

    def test_pillow_floor_supports_resampling_enum_used_by_image_resize(self):
        project = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertIn("Pillow>=9.1", project["project"]["dependencies"])
