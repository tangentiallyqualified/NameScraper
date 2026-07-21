"""Provider-neutral season-map availability contract."""

from __future__ import annotations

from typing import Any

import pytest

from plex_renamer._tmdb_transport import TMDBNetworkError
from plex_renamer.providers import SeasonMapUnavailableError
from plex_renamer.tmdb import TMDBClient
from plex_renamer.tvdb import TVDBClient


class EmptySeasonMapProvider:
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        return {}, 0


class UnavailableSeasonMapProvider:
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}")


class _FailingTransport:
    def get_json(
        self, path: str, params: dict[str, object] | None = None
    ) -> dict[str, object] | None:
        raise TMDBNetworkError("offline")


class _MapTransport:
    def __init__(self, responses: dict[str, dict[str, Any] | None]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, path: str, params: dict[str, object] | None = None) -> dict[str, Any] | None:
        self.calls.append(path)
        return self.responses[path]


@pytest.fixture
def empty_provider() -> EmptySeasonMapProvider:
    return EmptySeasonMapProvider()


@pytest.fixture
def failing_provider() -> UnavailableSeasonMapProvider:
    return UnavailableSeasonMapProvider()


def test_valid_empty_map_is_a_success(empty_provider: EmptySeasonMapProvider) -> None:
    assert empty_provider.get_season_map(7) == ({}, 0)


def test_unavailable_map_raises_typed_error(failing_provider: UnavailableSeasonMapProvider) -> None:
    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        failing_provider.get_season_map(7)


def test_tmdb_season_map_wraps_transport_failure() -> None:
    client = TMDBClient("key")
    client._transport = _FailingTransport()  # type: ignore[assignment]

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable"):
        client.get_season_map(7)


def test_tvdb_season_map_wraps_transport_failure() -> None:
    client = TVDBClient("key", transport=_FailingTransport())  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable"):
        client.get_season_map(7)


def test_tvdb_season_map_caches_a_valid_empty_result() -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            "/series/7/episodes/default": {"data": {"episodes": []}, "links": {}},
        }
    )
    client = TVDBClient("key", transport=transport)  # type: ignore[arg-type]

    assert client.get_season_map(7) == ({}, 0)
    assert client.get_season_map(7) == ({}, 0)
    assert transport.calls == ["/series/7/extended", "/series/7/episodes/default"]
