"""TMDB client lifecycle helpers for the main window."""

from __future__ import annotations

from typing import Any, Callable


class MainWindowTmdbCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        cache_namespace: str,
        snapshot_key: str,
    ) -> None:
        self._window = window
        self._cache_namespace = cache_namespace
        self._snapshot_key = snapshot_key

    def ensure_tmdb(
        self,
        *,
        api_key_lookup: Callable[[str], str | None],
        tmdb_client_factory: Callable[..., Any],
    ) -> Any | None:
        window = self._window
        if window._tmdb is not None:
            return window._tmdb
        api_key = api_key_lookup("TMDB")
        if not api_key:
            window.statusBar().showMessage(
                "No TMDB API key — set one in Settings first.",
                5000,
            )
            return None
        window._tmdb = tmdb_client_factory(
            api_key,
            language=window.settings_service.match_language,
            cache_service=window._cache_service,
            refresh_policy=window._refresh_policy,
        )
        self.restore_tmdb_cache_snapshot()
        return window._tmdb

    def restore_tmdb_cache_snapshot(self) -> None:
        window = self._window
        if window._tmdb is None:
            return
        cached_snapshot = window._cache_service.get(
            self._cache_namespace,
            self._snapshot_key,
        )
        if not cached_snapshot.is_hit or not cached_snapshot.value:
            return
        try:
            window._tmdb.import_cache_snapshot(
                cached_snapshot.value,
                clear_existing=True,
            )
        except Exception:
            window._cache_service.invalidate(
                self._cache_namespace,
                self._snapshot_key,
            )

    def persist_tmdb_cache_snapshot(self) -> None:
        window = self._window
        if window._tmdb is None:
            return
        snapshot = window._tmdb.export_cache_snapshot()
        window._cache_service.put(
            self._cache_namespace,
            self._snapshot_key,
            snapshot,
            metadata={"kind": "tmdb_cache_snapshot"},
        )

    def invalidate_tmdb(self) -> None:
        window = self._window
        self.persist_tmdb_cache_snapshot()
        window._tmdb = None

    def drop_tmdb_client(self) -> None:
        self._window._tmdb = None
