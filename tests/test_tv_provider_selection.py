# pyright: strict
"""Provider selection: settings toggle -> which client the TV scan gets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _provider_fakes import RecordingProvider

from plex_renamer.app.controllers.media_controller import MediaController
from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.refresh_policy_service import RefreshPolicyService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.gui_qt._main_window_tmdb import MainWindowTmdbCoordinator
from plex_renamer.job_store import JobStore


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, text: str, timeout: int = 0) -> None:
        self.messages.append(text)


class _Settings:
    def __init__(self, source: str) -> None:
        self.tv_metadata_source = source
        self.match_language = "en-US"


class _MissLookup:
    is_hit = False
    value = None


class _CacheStub:
    def get(self, namespace: str, key: str) -> _MissLookup:
        return _MissLookup()


class _Window:
    def __init__(self, source: str) -> None:
        self._tmdb: Any | None = None
        self._tv_provider: Any | None = None
        self._cache_service: Any | None = _CacheStub()
        self._refresh_policy: Any | None = None
        self.settings_service = _Settings(source)
        self._status = _StatusBar()

    def statusBar(self) -> _StatusBar:
        return self._status


def _coordinator(window: _Window) -> MainWindowTmdbCoordinator:
    return MainWindowTmdbCoordinator(window, cache_namespace="ns", snapshot_key="k")


def test_tmdb_source_returns_tmdb_client() -> None:
    window = _Window("tmdb")
    client = _coordinator(window).ensure_tv_provider(api_key_lookup=lambda service: "key")
    assert client is not None and client.provider_name == "tmdb"
    assert client is window._tmdb  # pyright: ignore[reportPrivateUsage]


def test_tvdb_source_returns_tvdb_client() -> None:
    window = _Window("tvdb")
    client = _coordinator(window).ensure_tv_provider(
        api_key_lookup=lambda service: "key" if service == "TVDB" else None
    )
    assert client is not None and client.provider_name == "tvdb"
    assert client is window._tv_provider  # pyright: ignore[reportPrivateUsage]
    assert window._tmdb is None  # pyright: ignore[reportPrivateUsage]  # TMDB not built as a side effect


def test_missing_tvdb_key_blocks_with_message() -> None:
    window = _Window("tvdb")
    client = _coordinator(window).ensure_tv_provider(api_key_lookup=lambda service: None)
    assert client is None
    assert any("TheTVDB" in m for m in window._status.messages)  # pyright: ignore[reportPrivateUsage]


def test_invalidate_drops_both_clients() -> None:
    window = _Window("tvdb")
    coordinator = _coordinator(window)
    coordinator.ensure_tv_provider(api_key_lookup=lambda service: "key")
    coordinator.invalidate_tmdb()
    assert window._tv_provider is None and window._tmdb is None  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def settings_service(tmp_path: Path) -> SettingsService:
    """Provide a fresh SettingsService instance for testing."""
    return SettingsService(path=tmp_path / "settings.json")


def test_fallback_and_id_tag_setting_defaults(settings_service: SettingsService) -> None:
    assert settings_service.tv_fallback_enabled is False
    assert settings_service.tv_id_tag_routing_enabled is True
    assert settings_service.tv_provider_overrides == {}


def test_provider_override_round_trip(settings_service: SettingsService) -> None:
    settings_service.tv_provider_overrides = {
        "breaking bad|2008": {"provider": "tvdb", "show_id": 81189},
    }
    assert settings_service.tv_provider_overrides == {
        "breaking bad|2008": {"provider": "tvdb", "show_id": 81189},
    }


class _FallbackSettings(_Settings):
    def __init__(self, source: str, *, fallback_enabled: bool) -> None:
        super().__init__(source)
        self.tv_fallback_enabled = fallback_enabled


class _FallbackWindow(_Window):
    def __init__(self, source: str, *, fallback_enabled: bool) -> None:
        super().__init__(source)
        self.settings_service = _FallbackSettings(source, fallback_enabled=fallback_enabled)


def test_fallback_disabled_returns_none_quietly() -> None:
    window = _FallbackWindow("tmdb", fallback_enabled=False)
    client = _coordinator(window).ensure_fallback_provider(api_key_lookup=lambda service: "key")
    assert client is None
    assert window._status.messages == []  # pyright: ignore[reportPrivateUsage]


def test_fallback_enabled_returns_non_active_provider() -> None:
    window = _FallbackWindow("tmdb", fallback_enabled=True)
    client = _coordinator(window).ensure_fallback_provider(
        api_key_lookup=lambda service: "key" if service == "TVDB" else None
    )
    assert client is not None and client.provider_name == "tvdb"
    assert client is window._tv_provider  # pyright: ignore[reportPrivateUsage]
    assert window._tmdb is None  # pyright: ignore[reportPrivateUsage]


def test_fallback_enabled_tmdb_as_other_provider() -> None:
    window = _FallbackWindow("tvdb", fallback_enabled=True)
    client = _coordinator(window).ensure_fallback_provider(
        api_key_lookup=lambda service: "key" if service == "TMDB" else None
    )
    assert client is not None and client.provider_name == "tmdb"
    assert client is window._tmdb  # pyright: ignore[reportPrivateUsage]


def test_fallback_enabled_missing_other_key_returns_none_quietly() -> None:
    window = _FallbackWindow("tmdb", fallback_enabled=True)
    client = _coordinator(window).ensure_fallback_provider(api_key_lookup=lambda service: None)
    assert client is None
    assert window._status.messages == []  # pyright: ignore[reportPrivateUsage]


def test_provider_named_resolves_non_active_provider_independent_of_fallback_setting() -> None:
    # provider_named must resolve "tvdb" by name even when fallback is
    # disabled and tmdb is the active source: job-detail posters resolve
    # by the JOB's own recorded provider, not by the fallback toggle.
    window = _FallbackWindow("tmdb", fallback_enabled=False)
    client = _coordinator(window).provider_named(
        "tvdb", api_key_lookup=lambda service: "key" if service == "TVDB" else None
    )
    assert client is not None and client.provider_name == "tvdb"
    assert client is window._tv_provider  # pyright: ignore[reportPrivateUsage]


def test_provider_named_tmdb_returns_tmdb_client() -> None:
    window = _Window("tvdb")
    client = _coordinator(window).provider_named("tmdb", api_key_lookup=lambda service: "key")
    assert client is not None and client.provider_name == "tmdb"
    assert client is window._tmdb  # pyright: ignore[reportPrivateUsage]


def test_provider_named_missing_key_falls_back_to_tmdb_client() -> None:
    window = _Window("tvdb")
    client = _coordinator(window).provider_named(
        "tvdb", api_key_lookup=lambda service: "key" if service == "TMDB" else None
    )
    assert client is not None and client.provider_name == "tmdb"


def test_provider_named_unknown_name_falls_back_to_tmdb_client() -> None:
    window = _Window("tvdb")
    client = _coordinator(window).provider_named(
        "nonexistent", api_key_lookup=lambda service: "key"
    )
    assert client is not None and client.provider_name == "tmdb"


def _make_media_controller(tmp_path: Path, settings: SettingsService) -> MediaController:
    return MediaController(
        job_store=JobStore(db_path=tmp_path / "jobs.db"),
        command_gating=CommandGatingService(),
        settings=settings,
        cache_service=PersistentCacheService(db_path=tmp_path / "cache.db"),
        refresh_policy=RefreshPolicyService(),
    )


def test_orchestrator_receives_fallback_and_pins(tmp_path: Path) -> None:
    """Construction plumbing: settings flow into BatchTVOrchestrator via
    ``start_tv_batch`` -> ``MediaControllerTVWorkflow.start_batch`` ->
    ``start_tv_batch_session``. ``_batch_orchestrator`` is built
    synchronously before the background discovery worker starts, so it
    can be asserted on immediately."""
    settings = SettingsService(path=tmp_path / "settings.json")
    settings.tv_metadata_source = "tmdb"
    settings.tv_fallback_enabled = True
    settings.tv_id_tag_routing_enabled = False
    pins = {"x|2000": {"provider": "tvdb", "show_id": 5}}
    settings.tv_provider_overrides = pins

    controller = _make_media_controller(tmp_path, settings)
    root = tmp_path / "tv_root"
    root.mkdir()

    tmdb_fake = RecordingProvider("tmdb")
    tvdb_fake = RecordingProvider("tvdb")
    controller.start_tv_batch(root, tmdb_fake, tvdb_fake)

    orchestrator = controller.batch_orchestrator
    assert orchestrator is not None
    assert orchestrator.fallback_provider is tvdb_fake
    assert orchestrator.provider_overrides == pins
    assert orchestrator.id_tag_routing is False


def test_orchestrator_without_fallback_provider(tmp_path: Path) -> None:
    settings = SettingsService(path=tmp_path / "settings.json")
    settings.tv_id_tag_routing_enabled = True

    controller = _make_media_controller(tmp_path, settings)
    root = tmp_path / "tv_root"
    root.mkdir()

    controller.start_tv_batch(root, RecordingProvider("tmdb"))

    orchestrator = controller.batch_orchestrator
    assert orchestrator is not None
    assert orchestrator.fallback_provider is None
    assert orchestrator.provider_overrides == {}
    assert orchestrator.id_tag_routing is True
