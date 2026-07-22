"""TMDB runtime-cache snapshot round trips and contract migration."""

# pyright: strict

from typing import Any, cast

from season_map_test_support import MapTransport

from plex_renamer.tmdb import TMDBClient


def _close(client: TMDBClient) -> None:
    cast(Any, client)._session.close()


def test_cache_snapshot_roundtrip_restores_runtime_metadata() -> None:
    client = TMDBClient("dummy-api-key")
    snapshot: dict[str, Any] = {
        "season_map_contract_version": 1,
        "show_cache": {"321": {"poster_path": "/andor.jpg", "name": "Andor"}},
        "season_cache": {
            "321:1": {
                "titles": {"1": "Pilot"},
                "posters": {"1": "/still.jpg"},
                "episodes": {"1": {"name": "Pilot"}},
                "season_poster_path": "/season.jpg",
            }
        },
        "season_map_cache": {
            "321": {
                "seasons": {
                    "1": {
                        "name": "Season 1",
                        "titles": {"1": "Pilot"},
                        "posters": {"1": "/still.jpg"},
                        "episodes": {"1": {"name": "Pilot"}},
                        "count": 1,
                        "season_poster_path": "/season.jpg",
                    }
                },
                "total_episodes": 1,
            }
        },
        "movie_cache": {"123": {"poster_path": "/movie.jpg", "title": "Movie"}},
    }

    client.import_cache_snapshot(snapshot, clear_existing=True)

    assert client.get_cached_poster_path(321) == "/andor.jpg"
    assert client.get_cached_poster_path(123, media_type="movie") == "/movie.jpg"
    assert client.get_season(321, 1)["titles"][1] == "Pilot"
    season_map, total = client.get_season_map(321)
    assert total == 1
    assert season_map[1]["titles"][1] == "Pilot"

    exported = client.export_cache_snapshot()
    assert exported["show_cache"][321]["poster_path"] == "/andor.jpg"
    assert "321:1" in exported["season_cache"]
    assert exported["movie_cache"][123]["poster_path"] == "/movie.jpg"
    assert exported["season_map_contract_version"] == 1
    _close(client)


def test_legacy_snapshot_discards_only_poisoned_season_maps_and_refetches() -> None:
    client = TMDBClient("dummy-api-key")
    transport = MapTransport(
        {
            "/tv/321": {"seasons": [{"season_number": 1, "episode_count": 1, "name": "Season 1"}]},
            "/tv/321/season/1": {"episodes": [{"episode_number": 1, "name": "Fresh Pilot"}]},
        }
    )
    cast(Any, client)._transport = transport
    legacy_snapshot: dict[str, Any] = {
        "show_cache": {"321": {"poster_path": "/andor.jpg", "name": "Andor"}},
        "season_cache": {
            "321:1": {
                "titles": {"1": "Cached single season"},
                "posters": {},
                "episodes": {},
            }
        },
        "season_map_cache": {
            "321": {
                "seasons": {
                    "1": {
                        "name": "Season 1",
                        "titles": {},
                        "posters": {},
                        "episodes": {},
                        "count": 12,
                    }
                },
                "total_episodes": 12,
            }
        },
        "movie_cache": {"123": {"poster_path": "/movie.jpg", "title": "Movie"}},
    }

    client.import_cache_snapshot(legacy_snapshot, clear_existing=True)

    assert client.get_cached_poster_path(321) == "/andor.jpg"
    assert client.get_cached_poster_path(123, media_type="movie") == "/movie.jpg"
    assert client.get_season(321, 1)["titles"][1] == "Cached single season"
    season_map, total = client.get_season_map(321)
    assert total == 1
    assert season_map[1]["titles"] == {1: "Fresh Pilot"}
    assert transport.calls == ["/tv/321", "/tv/321/season/1"]
    _close(client)
