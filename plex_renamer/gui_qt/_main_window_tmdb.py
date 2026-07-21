"""TMDB client lifecycle helpers for the main window."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


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

    def ensure_tv_provider(
        self,
        *,
        api_key_lookup: Callable[[str], str | None],
    ) -> Any | None:
        """Active TV metadata client per settings; movies keep ensure_tmdb."""
        from ..providers import get_tv_provider_spec
        from ..tmdb import TMDBClient

        window = self._window
        spec = get_tv_provider_spec(window.settings_service.tv_metadata_source)
        if spec.name == "tmdb":
            return self.ensure_tmdb(
                api_key_lookup=api_key_lookup,
                tmdb_client_factory=TMDBClient,
            )
        if window._tv_provider is not None:
            return window._tv_provider
        api_key = api_key_lookup(spec.key_service)
        if not api_key:
            window.statusBar().showMessage(
                f"No {spec.label} API key — set one in Settings first.",
                5000,
            )
            return None
        window._tv_provider = spec.factory(
            api_key,
            language=window.settings_service.match_language,
            cache_service=window._cache_service,
            refresh_policy=window._refresh_policy,
        )
        return window._tv_provider

    def ensure_other_provider(
        self,
        *,
        api_key_lookup: Callable[[str], str | None],
    ) -> Any | None:
        """Client for the NON-active TV provider, whenever a key exists for
        it — quietly ``None`` otherwise (no status-bar nag).

        Gated on key presence ONLY, independent of the
        ``tv_fallback_enabled`` toggle: id-tag routing and the Source
        selector need this pool slot fed even with fallback matching off
        (spec precedence gates only the confidence-based second-opinion
        matching PASS on that toggle — see
        ``BatchTVOrchestrator.fallback_matching``)."""
        from ..providers import other_tv_provider_spec
        from ..tmdb import TMDBClient

        window = self._window
        other = other_tv_provider_spec(window.settings_service.tv_metadata_source)
        if other is None:
            return None
        api_key = api_key_lookup(other.key_service)
        if not api_key:
            return None
        if other.name == "tmdb":
            return self.ensure_tmdb(
                api_key_lookup=api_key_lookup,
                tmdb_client_factory=TMDBClient,
            )
        if window._tv_provider is not None:
            return window._tv_provider
        # Exactly two providers exist (TMDB, TVDB): _tv_provider caches
        # whichever one is non-TMDB, regardless of whether it is playing
        # the active or the fallback role right now — safe only because
        # there is no third provider slot to collide with.
        window._tv_provider = other.factory(
            api_key,
            language=window.settings_service.match_language,
            cache_service=window._cache_service,
            refresh_policy=window._refresh_policy,
        )
        return window._tv_provider

    def provider_named(
        self,
        name: str,
        *,
        api_key_lookup: Callable[[str], str | None],
    ) -> Any | None:
        """Client for the TV provider named *name* — independent of which
        provider is currently "active" or whether fallback is enabled.

        Job-detail poster fetches (Queue/History) must resolve by the
        JOB's own recorded provider (``RenameJob.data_source``), not by
        the window's current settings — a job queued while TVDB was
        active still carries a TVDB numeric ID after the user switches
        the active source back to TMDB. Falls back to the TMDB client
        (``ensure_tmdb``) when *name* is unresolvable or its key is
        missing — the same "active client" behavior Queue/History used
        before this method existed, so a missing key degrades exactly as
        before instead of ever leaving Queue/History without a poster
        client entirely."""
        from ..providers import TV_PROVIDERS
        from ..tmdb import TMDBClient

        window = self._window
        spec = TV_PROVIDERS.get(name)
        if spec is None:
            return self.ensure_tmdb(
                api_key_lookup=api_key_lookup,
                tmdb_client_factory=TMDBClient,
            )
        if spec.name == "tmdb":
            return self.ensure_tmdb(
                api_key_lookup=api_key_lookup,
                tmdb_client_factory=TMDBClient,
            )
        # Exactly two providers exist: a non-TMDB spec's client lives in
        # _tv_provider, the same cache ensure_tv_provider/ensure_other_provider
        # use for the non-TMDB slot (see the comment in ensure_other_provider).
        if window._tv_provider is not None:
            return window._tv_provider
        api_key = api_key_lookup(spec.key_service)
        if not api_key:
            return self.ensure_tmdb(
                api_key_lookup=api_key_lookup,
                tmdb_client_factory=TMDBClient,
            )
        window._tv_provider = spec.factory(
            api_key,
            language=window.settings_service.match_language,
            cache_service=window._cache_service,
            refresh_policy=window._refresh_policy,
        )
        return window._tv_provider

    def invalidate_tmdb(self) -> None:
        window = self._window
        self.persist_tmdb_cache_snapshot()
        window._tmdb = None
        window._tv_provider = None

    def drop_tmdb_client(self) -> None:
        window = self._window
        window._tmdb = None
        window._tv_provider = None
