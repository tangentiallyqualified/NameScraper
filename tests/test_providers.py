"""Protocol conformance and registry behavior for metadata providers."""

from __future__ import annotations

from plex_renamer.providers import (
    TV_PROVIDERS,
    MetadataProvider,
    ProviderSpec,
    get_tv_provider_spec,
)
from plex_renamer.tmdb import TMDBClient


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
    from plex_renamer.tvdb import TVDBClient

    client = TVDBClient("fake-key")
    assert isinstance(client, MetadataProvider)
    assert client.provider_name == "tvdb"
