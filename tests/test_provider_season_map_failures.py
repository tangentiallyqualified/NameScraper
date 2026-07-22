"""Provider-neutral season-map availability contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plex_renamer._tmdb_transport import TMDBNetworkError
from plex_renamer.engine._tv_scanner import TVScanner
from plex_renamer.providers import SeasonMapUnavailableError
from plex_renamer.tmdb import TMDBClient
from plex_renamer.tvdb import TVDBClient


class EmptySeasonMapProvider:
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        return {}, 0


class UnavailableSeasonMapProvider:
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}")


class _ProviderReturning:
    provider_name = "tmdb"

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def get_season_map(self, show_id: int) -> object:
        return self.payload

    def get_season(self, show_id: int, season_number: int) -> dict[str, Any]:
        return {}

    def get_alternative_titles(
        self, media_id: int, media_type: str = "tv"
    ) -> list[tuple[str, str]]:
        return []


def _scanner(tmp_path: Path, provider: _ProviderReturning) -> TVScanner:
    return TVScanner(
        provider,  # type: ignore[arg-type]
        {"id": 7, "name": "Example Show"},
        tmp_path,
    )


class _FailingTransport:
    def get_json(
        self, path: str, params: dict[str, object] | None = None
    ) -> dict[str, object] | None:
        raise TMDBNetworkError("offline")


class _MapTransport:
    def __init__(self, responses: dict[Any, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, path: str, params: dict[str, object] | None = None) -> Any:
        self.calls.append(path)
        page = (params or {}).get("page")
        if (path, page) in self.responses:
            return self.responses[(path, page)]
        return self.responses[path]

    def get_json_safe(self, path: str, params: dict[str, object] | None = None) -> Any:
        try:
            return self.get_json(path, params)
        except KeyError:
            return None


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


@pytest.mark.parametrize(
    "payload",
    [None, (None, 0), ({1: []}, 0), ({"bad": {}}, 0), ({True: {}}, 0)],
)
def test_scanner_rejects_malformed_season_maps(tmp_path: Path, payload: object) -> None:
    scanner = _scanner(tmp_path, provider=_ProviderReturning(payload))

    with pytest.raises(SeasonMapUnavailableError, match="malformed season map"):
        scanner.scan()


def test_scanner_accepts_a_valid_empty_season_map(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path, provider=_ProviderReturning(({}, 0)))

    items, _has_mismatch = scanner.scan()
    assert items == []


@pytest.mark.parametrize("episode_count", [None, True, "0", -1])
def test_scanner_rejects_malformed_total_episode_count(
    tmp_path: Path,
    episode_count: object,
) -> None:
    scanner = _scanner(tmp_path, provider=_ProviderReturning(({}, episode_count)))

    with pytest.raises(SeasonMapUnavailableError, match="malformed season map"):
        scanner.scan()


@pytest.mark.parametrize(
    "season_payload",
    [
        {"titles": [], "posters": {}, "episodes": {}, "count": 0},
        {"titles": {}, "posters": [], "episodes": {}, "count": 0},
        {"titles": {}, "posters": {}, "episodes": [], "count": 0},
        {"titles": {}, "posters": {}, "episodes": {}, "count": True},
        {"titles": {}, "posters": {}, "episodes": {}, "count": "0"},
        {"posters": {}, "episodes": {}, "count": 0},
        {"titles": {}, "episodes": {}, "count": 0},
        {"titles": {}, "posters": {}, "count": 0},
        {"titles": {}, "posters": {}, "episodes": {}},
        {"titles": {"1": "Pilot"}, "posters": {}, "episodes": {}, "count": 1},
        {"titles": {True: "Pilot"}, "posters": {}, "episodes": {}, "count": 1},
        {"titles": {1: 7}, "posters": {}, "episodes": {}, "count": 1},
        {"titles": {}, "posters": {1: 7}, "episodes": {}, "count": 1},
        {"titles": {}, "posters": {}, "episodes": {1: []}, "count": 1},
    ],
)
def test_scanner_rejects_malformed_nested_season_payloads(
    tmp_path: Path,
    season_payload: dict[str, object],
) -> None:
    scanner = _scanner(tmp_path, provider=_ProviderReturning(({1: season_payload}, 1)))

    with pytest.raises(SeasonMapUnavailableError, match="malformed season map"):
        scanner.scan()


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


@pytest.mark.parametrize(
    ("season_info", "season_path"),
    [
        ({"episode_count": 1}, "/tv/7/season/0"),
        ({"season_number": "1", "episode_count": 1}, "/tv/7/season/1"),
        ({"season_number": True, "episode_count": 1}, "/tv/7/season/True"),
    ],
)
def test_tmdb_season_map_rejects_invalid_season_identifiers(
    season_info: dict[str, object],
    season_path: str,
) -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport(  # type: ignore[assignment]
        {
            "/tv/7": {"seasons": [season_info]},
            season_path: {"episodes": []},
        }
    )

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


@pytest.mark.parametrize(
    "episode",
    [
        {},
        {"episode_number": "1", "name": "Pilot"},
        {"episode_number": True, "name": "Pilot"},
    ],
)
def test_tmdb_season_map_rejects_invalid_episode_identifiers(
    episode: dict[str, object],
) -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport(  # type: ignore[assignment]
        {
            "/tv/7": {"seasons": [{"season_number": 1, "episode_count": 1, "name": "Season 1"}]},
            "/tv/7/season/1": {"episodes": [episode]},
        }
    )

    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._metadata_cache_store.season_map_cache == {}


@pytest.mark.parametrize(
    ("season_name", "episode"),
    [
        ([], {"episode_number": 1, "name": "Pilot"}),
        ("Season 1", {"episode_number": 1, "name": 7}),
        ("Season 1", {"episode_number": 1, "name": "Pilot", "still_path": 7}),
    ],
)
def test_tmdb_season_map_rejects_invalid_nested_output_values_before_caching(
    season_name: object,
    episode: dict[str, object],
) -> None:
    client = TMDBClient("key")
    client._transport = _MapTransport(  # type: ignore[assignment]
        {
            "/tv/7": {
                "seasons": [
                    {
                        "season_number": 1,
                        "episode_count": 1,
                        "name": season_name,
                    }
                ]
            },
            "/tv/7/season/1": {"episodes": [episode]},
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


@pytest.mark.parametrize(
    "episode",
    [
        {},
        {"seasonNumber": "1", "number": 1},
        {"seasonNumber": 1, "number": "1"},
        {"seasonNumber": True, "number": 1},
        {"seasonNumber": 1, "number": False},
    ],
)
def test_tvdb_season_map_rejects_invalid_episode_identifiers(
    episode: dict[str, object],
) -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            "/series/7/episodes/default": {
                "data": {"episodes": [episode]},
                "links": {},
            },
        }
    )
    client = TVDBClient("key", transport=transport)  # type: ignore[arg-type]

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}


@pytest.mark.parametrize(
    "episode",
    [
        {"seasonNumber": 1, "number": 1, "name": 7},
        {"seasonNumber": 1, "number": 1, "name": []},
        {"seasonNumber": 1, "number": 1, "name": "Pilot", "image": 7},
        {"seasonNumber": 1, "number": 1, "name": "Pilot", "image": False},
    ],
)
def test_tvdb_season_map_rejects_invalid_nested_output_values_before_caching(
    episode: dict[str, object],
) -> None:
    client = TVDBClient(
        "key",
        transport=_MapTransport(
            {
                "/series/7/extended": {"data": {"id": 7}},
                "/series/7/episodes/default": {
                    "data": {"episodes": [episode]},
                    "links": {},
                },
            }
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}


def test_tvdb_malformed_extended_details_are_typed_uncached_and_safe() -> None:
    client = TVDBClient(
        "key",
        transport=_MapTransport(
            {
                "/series/7/extended": {"data": {"id": 7, "artworks": [None]}},
                "/series/7/episodes/default": {
                    "data": {"episodes": []},
                    "links": {},
                },
            }
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable for 7"):
        client.get_season_map(7)

    assert client._season_map_cache == {}
    assert client.get_season(7, 1) == {
        "titles": {},
        "posters": {},
        "episodes": {},
        "season_poster_path": None,
    }
    assert client.fetch_poster(7, media_type="tv", season=1) is None


def test_tvdb_season_map_rejects_mixed_valid_invalid_pages_atomically() -> None:
    transport = _MapTransport(
        {
            "/series/7/extended": {"data": {"id": 7}},
            ("/series/7/episodes/default", 0): {
                "data": {"episodes": [{"seasonNumber": 1, "number": 1, "name": "Pilot"}]},
                "links": {"next": 1},
            },
            ("/series/7/episodes/default", 1): {
                "data": {"episodes": [{}]},
                "links": {},
            },
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
