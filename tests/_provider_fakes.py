"""Shared metadata-provider test fakes.

``RecordingProvider`` is a minimal ``MetadataProvider``-shaped fake that
records every call made to it (as ``"method:arg"`` strings in ``.calls``)
and returns harmless defaults. Promoted from
``tests/test_provider_pool_routing.py`` so other provider-pool/routing
tests (e.g. ``tests/test_id_tag_routing.py``) can share one implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PIL import Image

from plex_renamer.metadata_types import MediaInfo


class RecordingProvider:
    def __init__(self, name: str) -> None:
        self.provider_name = name
        self.language = "en-US"
        self.calls: list[str] = []

    def search_tv(self, query: str, year: str | None = None) -> list[MediaInfo]:
        self.calls.append(f"search_tv:{query}")
        return []

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[MediaInfo]]:
        self.calls.append("search_tv_batch")
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
        self.calls.append(f"get_tv_details:{show_id}")
        return {"id": show_id, "name": "Show", "seasons": [], "number_of_episodes": 0}

    def get_season(self, show_id: int, season_num: int) -> dict[str, Any]:
        self.calls.append(f"get_season:{show_id}:{season_num}")
        return {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        self.calls.append(f"get_season_map:{show_id}")
        return {}, 0

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        self.calls.append(f"get_alternative_titles:{media_id}")
        return []

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
        self.calls.append("clear_cache")
