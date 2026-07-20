# pyright: strict
"""Provider selection: settings toggle -> which client the TV scan gets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.gui_qt._main_window_tmdb import MainWindowTmdbCoordinator


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
