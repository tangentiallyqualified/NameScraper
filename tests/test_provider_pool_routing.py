"""Provider pool: per-state routing of downstream metadata calls."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image


class RecordingProvider:
    def __init__(self, name: str) -> None:
        self.provider_name = name
        self.language = "en-US"
        self.calls: list[str] = []

    def search_tv(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(f"search_tv:{query}")
        return []

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
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


def _orchestrator(
    tmp_path: Path,
) -> tuple[Any, RecordingProvider, RecordingProvider]:
    from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
    from plex_renamer.engine._discovery_ports import (
        TVDiscoveryCandidateLike,  # verify import path
    )

    primary = RecordingProvider("tmdb")
    fallback = RecordingProvider("tvdb")

    class NoDiscovery:
        def discover_show_roots(self, library_root: Path) -> list[TVDiscoveryCandidateLike]:
            return []

    orch = BatchTVOrchestrator(primary, tmp_path, NoDiscovery(), fallback_provider=fallback)
    return orch, primary, fallback


def test_provider_for_routes_by_attribution(tmp_path: Path) -> None:
    from plex_renamer.engine.models import ScanState

    orch, primary, fallback = _orchestrator(tmp_path)
    state = ScanState(folder=tmp_path, media_info={"id": 7, "name": "S"})
    assert orch.provider_for(state) is primary
    state.provider_name = "tvdb"
    assert orch.provider_for(state) is fallback


def test_provider_for_unknown_name_falls_back_to_primary(tmp_path: Path) -> None:
    from plex_renamer.engine.models import ScanState

    orch, primary, _fallback = _orchestrator(tmp_path)
    state = ScanState(folder=tmp_path, media_info={"id": 7, "name": "S"})
    state.provider_name = "nonsense"
    assert orch.provider_for(state) is primary


def test_provider_named_returns_none_for_unknown(tmp_path: Path) -> None:
    orch, _primary, _fallback = _orchestrator(tmp_path)
    assert orch.provider_named("nonsense") is None


def test_provider_named_finds_fallback(tmp_path: Path) -> None:
    orch, _primary, fallback = _orchestrator(tmp_path)
    assert orch.provider_named("tvdb") is fallback


def test_provider_pool_without_fallback_still_resolves_primary(tmp_path: Path) -> None:
    from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
    from plex_renamer.engine._discovery_ports import TVDiscoveryCandidateLike
    from plex_renamer.engine.models import ScanState

    primary = RecordingProvider("tmdb")

    class NoDiscovery:
        def discover_show_roots(self, library_root: Path) -> list[TVDiscoveryCandidateLike]:
            return []

    orch = BatchTVOrchestrator(primary, tmp_path, NoDiscovery())
    state = ScanState(folder=tmp_path, media_info={"id": 7, "name": "S"})
    assert orch.provider_for(state) is primary
    assert orch.provider_named("tvdb") is None


def test_season_names_use_attributed_provider(tmp_path: Path) -> None:
    orch, primary, fallback = _orchestrator(tmp_path)
    orch._season_names_for_match({"id": 7}, provider=fallback)
    assert "get_tv_details:7" in fallback.calls
    assert primary.calls == []


def test_season_names_default_to_primary(tmp_path: Path) -> None:
    orch, primary, fallback = _orchestrator(tmp_path)
    orch._season_names_for_match({"id": 7})
    assert "get_tv_details:7" in primary.calls
    assert fallback.calls == []
