"""Failed provider maps remain retryable instead of poisoning caches."""

# pyright: strict

from typing import Any, cast

import pytest
from season_map_test_support import MapTransport

from plex_renamer.providers import SeasonMapUnavailableError
from plex_renamer.tmdb import TMDBClient
from plex_renamer.tvdb import TVDBClient


def _tvdb_client(transport: object) -> TVDBClient:
    return TVDBClient("key", transport=cast(Any, transport))


def test_tmdb_failed_season_map_is_retried() -> None:
    transport = MapTransport({"/tv/7": {}})
    client = TMDBClient("key")
    cast(Any, client)._transport = transport

    with pytest.raises(SeasonMapUnavailableError):
        client.get_season_map(7)
    transport.responses["/tv/7"] = {"seasons": []}

    assert client.get_season_map(7) == ({}, 0)
    assert transport.calls == ["/tv/7", "/tv/7"]


def test_tvdb_failed_season_map_is_retried() -> None:
    episode_path = "/series/7/episodes/default"
    transport = MapTransport({"/series/7/extended": {"data": {"id": 7}}, episode_path: []})
    client = _tvdb_client(transport)

    with pytest.raises(SeasonMapUnavailableError):
        client.get_season_map(7)
    transport.responses[episode_path] = {"data": {"episodes": []}, "links": {}}

    assert client.get_season_map(7) == ({}, 0)
