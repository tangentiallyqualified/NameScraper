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
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, path: str, params: dict[str, object] | None = None) -> Any:
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


def test_tmdb_season_map_rejects_malformed_details_payload() -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport({"/tv/7": {}})  # type: ignore[assignment]

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


def test_tmdb_season_map_caches_a_valid_empty_result() -> None:
    transport = _MapTransport({"/tv/7": {"seasons": []}})
    client = TMDBClient("key")
    client._transport = transport  # type: ignore[assignment]

    assert client.get_season_map(7) == ({}, 0)
    assert client.get_season_map(7) == ({}, 0)
    assert transport.calls == ["/tv/7"]


def test_tmdb_season_map_rejects_malformed_season_payload() -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport(  # type: ignore[assignment]
        {
            "/tv/7": {"seasons": [{"season_number": 1, "episode_count": 1}]},
            "/tv/7/season/1": {},
        }
    )

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


@pytest.mark.parametrize(
    "episode_payload",
    [
        {"links": {}},
        {"data": None, "links": {}},
        {"data": {"episodes": {}}, "links": {}},
    ],
)
def test_tvdb_season_map_rejects_malformed_episode_payload(
    episode_payload: dict[str, Any],
) -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            "/series/7/episodes/default": episode_payload,
        }
    )
    client = TVDBClient("key", transport=transport)  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}


@pytest.mark.parametrize("payload", [[], 0])
def test_tmdb_season_map_rejects_non_mapping_details_payload(payload: Any) -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport({"/tv/7": payload})  # type: ignore[assignment]

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


@pytest.mark.parametrize("payload", [[], 0])
def test_tmdb_season_map_rejects_non_mapping_season_payload(payload: Any) -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport(  # type: ignore[assignment]
        {
            "/tv/7": {"seasons": [{"season_number": 1, "episode_count": 1}]},
            "/tv/7/season/1": payload,
        }
    )

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


def test_tmdb_season_map_rejects_non_mapping_episode_entry() -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport(  # type: ignore[assignment]
        {
            "/tv/7": {"seasons": [{"season_number": 1, "episode_count": 1}]},
            "/tv/7/season/1": {"episodes": [None]},
        }
    )

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


@pytest.mark.parametrize("payload", [[], 0])
def test_tvdb_season_map_rejects_non_mapping_details_payload(payload: Any) -> None:
    client = TVDBClient("key", transport=_MapTransport({"/series/7/extended": payload}))  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}


@pytest.mark.parametrize("payload", [[], 0])
def test_tvdb_season_map_rejects_non_mapping_episode_payload(payload: Any) -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            "/series/7/episodes/default": payload,
        }
    )
    client = TVDBClient("key", transport=transport)  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}


def test_tvdb_season_map_rejects_non_mapping_episode_entry() -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            "/series/7/episodes/default": {"data": {"episodes": [None]}, "links": {}},
        }
    )
    client = TVDBClient("key", transport=transport)  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}


@pytest.mark.parametrize("links", [[], "", 0])
def test_tvdb_season_map_rejects_falsy_non_mapping_links(links: Any) -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            "/series/7/episodes/default": {"data": {"episodes": []}, "links": links},
        }
    )
    client = TVDBClient("key", transport=transport)  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}
