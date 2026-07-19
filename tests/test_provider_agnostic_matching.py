"""Prove matching runs against any MetadataProvider, not TMDBClient."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from plex_renamer.engine.matching import (
    score_tv_results,  # pyright: ignore[reportUnknownVariableType]
)
from plex_renamer.providers import MetadataProvider


class FakeProvider:
    provider_name = "fake"
    language = "en-US"

    def search_tv(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        return []

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        return [[] for _ in queries]

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable[..., Any],
        min_words: int = 1,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = search_fn(query, **kwargs)
        return result

    def get_tv_details(self, show_id: int) -> dict[str, Any] | None:
        return {
            "id": show_id,
            "name": "Frieren",
            "first_air_date": "2023-09-29",
            "status": "Ended",
            "number_of_episodes": 28,
            "number_of_seasons": 1,
            "seasons": [{"season_number": 1, "episode_count": 28, "name": "Season 1"}],
        }

    def get_season(self, show_id: int, season_num: int) -> dict[str, Any]:
        return {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        return {}, 0

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        return [("Sousou no Frieren", "")]

    def fetch_image(self, image_path: str | None, target_width: int = 300) -> Image.Image | None:
        return None

    def fetch_poster(
        self,
        media_id: int,
        media_type: str = "tv",
        season: int | None = None,
        ep_still: str | None = None,
        target_width: int = 300,
    ) -> Image.Image | None:
        return None

    def fetch_image_bytes(self, image_path: str | None, size: str = "original") -> bytes | None:
        return None

    def get_cached_poster_path(self, media_id: int, media_type: str = "tv") -> str | None:
        return None

    def clear_cache(self) -> None:
        return None


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(FakeProvider(), MetadataProvider)


def test_score_tv_results_accepts_any_provider(tmp_path: Path) -> None:
    results: list[dict[str, Any]] = [
        {
            "id": 1,
            "name": "Frieren: Beyond Journey's End",
            "year": "2023",
            "poster_path": None,
            "overview": "",
        },
        {
            "id": 2,
            "name": "Unrelated Show",
            "year": "1999",
            "poster_path": None,
            "overview": "",
        },
    ]
    scored: list[tuple[dict[str, Any], float]] = score_tv_results(  # pyright: ignore[reportUnknownVariableType]
        results, "Frieren", "2023", FakeProvider(), folder=tmp_path
    )
    assert len(scored) == 2
    scored_ids = {result["id"] for result, _score in scored}
    assert scored_ids == {1, 2}
    assert scored[0][0]["id"] == 1
