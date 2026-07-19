"""TheTVDB v4 API client implementing the MetadataProvider protocol.

Every public method returns the TMDB-shaped payloads documented on
``plex_renamer.providers.MetadataProvider`` — raw TVDB JSON never leaks
past this module. TVDB artwork references are absolute URLs carried in
the same poster_path/still_path fields; image helpers detect "http".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ._tmdb_batch_search import (
    resolve_tv_batch_query as _resolve_tv_batch_query,  # type: ignore
    run_batch_search as _run_batch_search,  # type: ignore
)
from ._tmdb_search_helpers import search_with_fallback as _run_search_with_fallback  # type: ignore
from ._tvdb_transport import TVDBTransport

log = logging.getLogger(__name__)

resolve_tv_batch_query: Callable[..., list[dict[str, Any]]] = _resolve_tv_batch_query  # type: ignore
run_batch_search: Callable[..., list[list[dict[str, Any]]]] = _run_batch_search  # type: ignore
run_search_with_fallback: Callable[..., list[dict[str, Any]]] = _run_search_with_fallback  # type: ignore


class TVDBClient:
    provider_name = "tvdb"

    def __init__(
        self,
        api_key: str,
        language: str = "en-US",
        cache_service: Any | None = None,
        refresh_policy: Any | None = None,
        transport: TVDBTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.language = language
        self._cache_service = cache_service
        self._refresh_policy = refresh_policy
        self._transport = transport or TVDBTransport(api_key)

    # ─── Search ───────────────────────────────────────────────────────

    def search_tv(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query, "type": "series"}
        if year:
            params["year"] = year
        data = self._transport.get_json_safe("/search", params) or {}
        results: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = data.get("data") or []
        for entry in entries:
            try:
                show_id = int(entry.get("tvdb_id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "id": show_id,
                    "name": entry.get("name") or "",
                    "year": str(entry.get("year") or ""),
                    "poster_path": entry.get("image_url") or None,
                    "overview": entry.get("overview") or "",
                }
            )
        return results

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        def _search_query(query: str, year: str | None) -> list[dict[str, Any]]:
            return resolve_tv_batch_query(
                query,
                year,
                search_with_fallback=self.search_with_fallback,
                search_fn=self.search_tv,
            )

        return run_batch_search(
            queries,
            search_query=_search_query,
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable[..., Any],
        min_words: int = 1,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return run_search_with_fallback(query, search_fn, min_words=min_words, **kwargs)
