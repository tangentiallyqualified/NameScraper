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
