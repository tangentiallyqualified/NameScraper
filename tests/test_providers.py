"""Protocol conformance and registry behavior for metadata providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

from plex_renamer.metadata_types import MediaInfo
from plex_renamer.providers import (
    TV_PROVIDERS,
    MetadataProvider,
    ProviderSpec,
    get_tv_provider_spec,
)
from plex_renamer.tmdb import TMDBClient
from plex_renamer.tvdb import TVDBClient


def test_tvdb_search_contract_annotations() -> None:
    client = TVDBClient("fake-key")
    provider: MetadataProvider = client
    if TYPE_CHECKING:
        assert_type(provider.search_tv("show"), list[MediaInfo])
        assert_type(
            provider.search_tv_batch([("show", None)]),
            list[list[MediaInfo]],
        )
        assert_type(
            provider.search_with_fallback("show", client.search_tv),
            list[MediaInfo],
        )


def test_tmdb_client_satisfies_protocol() -> None:
    client = TMDBClient("fake-key")
    assert isinstance(client, MetadataProvider)
    assert client.provider_name == "tmdb"


def test_registry_has_tmdb_and_tvdb() -> None:
    assert set(TV_PROVIDERS) == {"tmdb", "tvdb"}
    for spec in TV_PROVIDERS.values():
        assert isinstance(spec, ProviderSpec)
        assert spec.key_service


def test_unknown_source_falls_back_to_tmdb() -> None:
    assert get_tv_provider_spec("garbage").name == "tmdb"
    assert get_tv_provider_spec("tvdb").name == "tvdb"


def test_tvdb_client_satisfies_protocol() -> None:
    client = TVDBClient("fake-key")
    assert isinstance(client, MetadataProvider)
    assert client.provider_name == "tvdb"
