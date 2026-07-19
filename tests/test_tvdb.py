"""TVDB v4 transport and client normalization tests. All synthetic — no network."""

from __future__ import annotations

from typing import Any

import pytest

from plex_renamer._tmdb_transport import TMDBError
from plex_renamer._tvdb_transport import TVDBTransport
from plex_renamer.tvdb import TVDBClient


class _Resp:
    def __init__(
        self, status_code: int, payload: dict[str, Any] | None = None, content: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[tuple[str, dict[str, Any] | None, dict[str, str] | None]] = []
        self.post_queue: list[_Resp] = []
        self.get_queue: list[_Resp] = []

    def post(self, url: str, json: dict[str, Any] | None = None, timeout: Any = None) -> _Resp:
        self.posts.append(json or {})
        return self.post_queue.pop(0)

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: Any = None,
    ) -> _Resp:
        self.gets.append((url, params, headers))
        return self.get_queue.pop(0)


def _transport(session: _FakeSession) -> TVDBTransport:
    return TVDBTransport("k123", session=session)  # type: ignore[arg-type]


def test_logs_in_lazily_and_sends_bearer_token() -> None:
    session = _FakeSession()
    session.post_queue = [_Resp(200, {"data": {"token": "tok-1"}})]
    session.get_queue = [_Resp(200, {"data": []})]
    transport = _transport(session)
    assert transport.get_json("/search", {"query": "x"}) == {"data": []}
    assert session.posts == [{"apikey": "k123"}]
    _, _, headers = session.gets[0]
    assert headers == {"Authorization": "Bearer tok-1"}


def test_relogs_in_once_on_401() -> None:
    session = _FakeSession()
    session.post_queue = [
        _Resp(200, {"data": {"token": "stale"}}),
        _Resp(200, {"data": {"token": "fresh"}}),
    ]
    session.get_queue = [_Resp(401), _Resp(200, {"data": {"ok": True}})]
    transport = _transport(session)
    assert transport.get_json("/series/1/extended") == {"data": {"ok": True}}
    assert len(session.posts) == 2


def test_404_returns_none_and_500_raises() -> None:
    session = _FakeSession()
    session.post_queue = [_Resp(200, {"data": {"token": "t"}})]
    session.get_queue = [_Resp(404)]
    assert _transport(session).get_json("/series/999") is None

    session2 = _FakeSession()
    session2.post_queue = [_Resp(200, {"data": {"token": "t"}})]
    session2.get_queue = [_Resp(500)]
    with pytest.raises(TMDBError):
        _transport(session2).get_json("/series/1")


def test_get_json_safe_swallows_errors() -> None:
    session = _FakeSession()
    session.post_queue = [_Resp(500)]
    assert _transport(session).get_json_safe("/search") is None


def test_login_without_token_raises() -> None:
    session = _FakeSession()
    session.post_queue = [_Resp(200, {"data": {}})]
    with pytest.raises(TMDBError):
        _transport(session).get_json("/search")


class _FakeTVDBTransport:
    """Keyed by (path, page) with a plain-path fallback."""

    def __init__(self, responses: dict[Any, dict[str, Any] | None]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.fetched_urls: list[str] = []

    def get_json_safe(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        self.calls.append((path, params))
        page = (params or {}).get("page")
        if (path, page) in self.responses:
            return self.responses[(path, page)]
        return self.responses.get(path)

    def fetch_bytes(self, url: str, *, timeout: int = 10) -> bytes:
        self.fetched_urls.append(url)
        return b"image-bytes"


_SEARCH_RESPONSE: dict[str, Any] = {
    "data": [
        {
            "objectID": "series-81189",
            "tvdb_id": "81189",
            "name": "Breaking Bad",
            "year": "2008",
            "image_url": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
            "overview": "A chemistry teacher turns to crime.",
        },
        {"objectID": "series-x", "tvdb_id": "not-a-number", "name": "Bad Entry"},
    ]
}


def _client(responses: dict[Any, dict[str, Any] | None]) -> TVDBClient:
    return TVDBClient("k", transport=_FakeTVDBTransport(responses))  # type: ignore[arg-type]


def test_search_tv_normalizes_results_and_skips_bad_ids() -> None:
    client = _client({"/search": _SEARCH_RESPONSE})
    results = client.search_tv("breaking bad", year="2008")
    assert results == [
        {
            "id": 81189,
            "name": "Breaking Bad",
            "year": "2008",
            "poster_path": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
            "overview": "A chemistry teacher turns to crime.",
        }
    ]
    transport: Any = client._transport  # type: ignore[attr-defined]
    path, params = transport.calls[0]
    assert path == "/search"
    assert params == {"query": "breaking bad", "type": "series", "year": "2008"}


def test_search_tv_batch_preserves_order() -> None:
    client = _client({"/search": _SEARCH_RESPONSE})
    batches = client.search_tv_batch([("breaking bad", None), ("breaking bad", "2008")])
    assert len(batches) == 2
    assert all(batch and batch[0]["id"] == 81189 for batch in batches)


def test_provider_name() -> None:
    assert _client({}).provider_name == "tvdb"


_EXTENDED_RESPONSE: dict[str, Any] = {
    "data": {
        "id": 81189,
        "name": "Breaking Bad",
        "overview": "Crime drama.",
        "firstAired": "2008-01-20",
        "image": "https://artworks.thetvdb.com/banners/posters/81189-10.jpg",
        "status": {"id": 2, "name": "Ended"},
        "averageRuntime": 47,
        "score": 8.9,
        "genres": [{"id": 1, "name": "Drama"}],
        "companies": [
            {"name": "AMC", "companyType": {"companyTypeId": 1, "companyTypeName": "Network"}},
            {"name": "Sony", "companyType": {"companyTypeId": 3, "companyTypeName": "Studio"}},
        ],
        "aliases": [{"language": "eng", "name": "BrBa"}],
        "characters": [
            {"name": "Walter White", "personName": "Bryan Cranston", "sort": 1},
        ],
        "seasons": [
            {"id": 5001, "number": 1, "type": {"type": "official"}},
            {"id": 5002, "number": 2, "type": {"type": "official"}},
            {"id": 6001, "number": 1, "type": {"type": "dvd"}},
        ],
        "artworks": [
            {"image": "https://artworks.thetvdb.com/banners/fanart/bb.jpg", "type": 3},
            {
                "image": "https://artworks.thetvdb.com/banners/logos/bb.png",
                "type": 23,
                "language": "eng",
            },
            {
                "image": "https://artworks.thetvdb.com/banners/seasons/s1.jpg",
                "type": 7,
                "seasonId": 5001,
            },
        ],
    }
}

_EPISODES_PAGE_0: dict[str, Any] = {
    "data": {
        "episodes": [
            {
                "seasonNumber": 0,
                "number": 1,
                "name": "Pilot outtakes",
                "aired": "2009-01-01",
                "runtime": 5,
                "image": None,
                "overview": "Special.",
            },
            {
                "seasonNumber": 1,
                "number": 1,
                "name": "Pilot",
                "aired": "2008-01-20",
                "runtime": 58,
                "image": "https://artworks.thetvdb.com/banners/ep/1.jpg",
                "overview": "It begins.",
            },
            {
                "seasonNumber": 1,
                "number": 2,
                "name": "Cat's in the Bag...",
                "aired": "2008-01-27",
                "runtime": 48,
                "image": None,
                "overview": "Cleanup.",
            },
            {
                "seasonNumber": 2,
                "number": 1,
                "name": "Seven Thirty-Seven",
                "aired": "2009-03-08",
                "runtime": 47,
                "image": None,
                "overview": "Money.",
            },
        ]
    },
    "links": {"next": None},
}


def _detail_client() -> TVDBClient:
    return _client(
        {
            "/series/81189/extended": _EXTENDED_RESPONSE,
            ("/series/81189/episodes/default", 0): _EPISODES_PAGE_0,
        }
    )


def test_get_tv_details_normalizes_to_tmdb_shape() -> None:
    details = _detail_client().get_tv_details(81189)
    assert details is not None
    assert details["name"] == "Breaking Bad"
    assert details["first_air_date"] == "2008-01-20"
    assert details["status"] == "Ended"
    assert details["genres"] == [{"name": "Drama"}]
    assert details["networks"] == [{"name": "AMC"}]
    assert details["episode_run_time"] == [47]
    assert details["poster_path"] == "https://artworks.thetvdb.com/banners/posters/81189-10.jpg"
    assert details["backdrop_path"] == "https://artworks.thetvdb.com/banners/fanart/bb.jpg"
    assert details["images"]["logos"] == [
        {"file_path": "https://artworks.thetvdb.com/banners/logos/bb.png", "iso_639_1": "en"}
    ]
    assert details["credits"]["cast"] == [
        {"name": "Bryan Cranston", "character": "Walter White", "order": 1}
    ]
    assert {(s["season_number"], s["episode_count"]) for s in details["seasons"]} == {
        (0, 1),
        (1, 2),
        (2, 1),
    }
    assert details["number_of_seasons"] == 2
    assert details["number_of_episodes"] == 3
    assert details["_aliases"] == ["BrBa"]
    assert details["_season_posters"] == {1: "https://artworks.thetvdb.com/banners/seasons/s1.jpg"}


def test_get_tv_details_works_with_show_details_adapter() -> None:
    from plex_renamer.engine.show_details import (
        show_details_from_tmdb,  # type: ignore[reportUnknownVariableType]
    )

    details = _detail_client().get_tv_details(81189)
    adapted = show_details_from_tmdb(details)
    assert adapted is not None
    assert adapted.number_of_episodes == 3
    assert adapted.unaired is False


def test_get_season_map_builds_payloads_and_total() -> None:
    seasons, total = _detail_client().get_season_map(81189)
    assert total == 3  # specials excluded
    assert seasons[1]["titles"] == {1: "Pilot", 2: "Cat's in the Bag..."}
    assert seasons[1]["count"] == 2
    assert seasons[1]["season_poster_path"] == (
        "https://artworks.thetvdb.com/banners/seasons/s1.jpg"
    )
    assert seasons[1]["posters"][1] == "https://artworks.thetvdb.com/banners/ep/1.jpg"
    meta = seasons[1]["episodes"][1]
    assert meta["name"] == "Pilot"
    assert meta["air_date"] == "2008-01-20"
    assert meta["still_path"] == "https://artworks.thetvdb.com/banners/ep/1.jpg"
    assert meta["directors"] == [] and meta["writers"] == [] and meta["guest_stars"] == []


def test_get_season_returns_empty_payload_for_unknown_season() -> None:
    payload = _detail_client().get_season(81189, 9)
    assert payload == {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}


def test_get_alternative_titles_uses_aliases() -> None:
    client = _detail_client()
    assert client.get_alternative_titles(81189, media_type="tv") == [("BrBa", "")]
    assert client.get_alternative_titles(81189, media_type="movie") == []


def test_details_are_cached_in_memory() -> None:
    client = _detail_client()
    client.get_tv_details(81189)
    calls_before = len(client._transport.calls)  # type: ignore[attr-defined]
    client.get_tv_details(81189)
    assert len(client._transport.calls) == calls_before  # type: ignore[attr-defined]


def test_fetch_image_bytes_fetches_absolute_url() -> None:
    client = _client({})
    payload = client.fetch_image_bytes("https://artworks.thetvdb.com/banners/x.jpg")
    assert payload == b"image-bytes"
    assert client._transport.fetched_urls == [  # type: ignore[attr-defined]
        "https://artworks.thetvdb.com/banners/x.jpg"
    ]


def test_fetch_image_bytes_prefixes_relative_banner_path() -> None:
    client = _client({})
    client.fetch_image_bytes("/banners/x.jpg")
    assert client._transport.fetched_urls == [  # type: ignore[attr-defined]
        "https://artworks.thetvdb.com/banners/x.jpg"
    ]


def test_fetch_image_bytes_none_for_missing_path() -> None:
    assert _client({}).fetch_image_bytes(None) is None


def test_get_cached_poster_path_reads_details_cache() -> None:
    client = _detail_client()
    assert client.get_cached_poster_path(81189) is None  # nothing fetched yet
    client.get_tv_details(81189)
    assert client.get_cached_poster_path(81189) == (
        "https://artworks.thetvdb.com/banners/posters/81189-10.jpg"
    )
    assert client.get_cached_poster_path(81189, media_type="movie") is None
