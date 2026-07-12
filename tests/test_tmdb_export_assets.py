"""TMDB export-asset helpers: widened details params, raw image bytes,
logo selection."""

import base64

import pytest

from plex_renamer._tmdb_metadata_builder import select_logo_path
from plex_renamer.tmdb import TMDBClient


class _Lookup:
    def __init__(self, value=None):
        self.value = value
        self.is_hit = value is not None


class FakeCacheService:
    def __init__(self):
        self.store = {}

    def get(self, namespace, key):
        return _Lookup(self.store.get((namespace, key)))

    def put(self, namespace, key, value, metadata=None):
        self.store[(namespace, key)] = value

    def invalidate(self, namespace, key):
        self.store.pop((namespace, key), None)


@pytest.fixture
def client(monkeypatch):
    c = TMDBClient("fake-key", language="en-US")
    c._cache_service = FakeCacheService()
    c._image_cache_store._cache_service = None
    return c


def test_details_calls_append_credits_and_images(client, monkeypatch):
    seen = {}

    def fake_get_safe(path, params=None):
        seen["path"], seen["params"] = path, params
        return {"id": 99}

    monkeypatch.setattr(client._transport, "get_json_safe", fake_get_safe)
    client.get_tv_details(99)
    assert seen["path"] == "/tv/99"
    assert seen["params"]["append_to_response"] == "credits,images"
    assert seen["params"]["include_image_language"] == "en,null"

    seen.clear()
    client.get_movie_details(7)
    assert seen["path"] == "/movie/7"
    assert seen["params"]["append_to_response"] == "credits,images"


def test_fetch_image_bytes_downloads_and_caches(client, monkeypatch):
    calls = []

    def fake_fetch_bytes(url):
        calls.append(url)
        return b"jpegbytes"

    monkeypatch.setattr(client._transport, "fetch_bytes", fake_fetch_bytes)
    data = client.fetch_image_bytes("/abc.jpg")
    assert data == b"jpegbytes"
    assert calls == ["https://image.tmdb.org/t/p/original/abc.jpg"]

    # Second call served from the persistent cache — no new download.
    data2 = client.fetch_image_bytes("/abc.jpg")
    assert data2 == b"jpegbytes"
    assert len(calls) == 1

    cached = client._cache_service.store[
        ("tmdb.export_image", "original::/abc.jpg")]
    assert base64.b64decode(cached["bytes_base64"]) == b"jpegbytes"


def test_fetch_image_bytes_handles_missing_path(client):
    assert client.fetch_image_bytes(None) is None
    assert client.fetch_image_bytes("") is None


def test_fetch_image_bytes_404_returns_none_and_caches_nothing(
        client, monkeypatch):
    class FakeResponse:
        ok = False
        status_code = 404
        content = b"<html>not found</html>"

    def fake_get(url, timeout=10):
        return FakeResponse()

    monkeypatch.setattr(client._transport.session, "get", fake_get)
    data = client.fetch_image_bytes("/missing.jpg")
    assert data is None
    assert client._cache_service.store == {}


def test_select_logo_prefers_language_then_null():
    details = {"images": {"logos": [
        {"file_path": "/de.png", "iso_639_1": "de",
         "vote_average": 9.9, "vote_count": 50},
        {"file_path": "/en-low.png", "iso_639_1": "en",
         "vote_average": 5.0, "vote_count": 3},
        {"file_path": "/en-high.png", "iso_639_1": "en",
         "vote_average": 8.0, "vote_count": 10},
        {"file_path": "/null.png", "iso_639_1": None,
         "vote_average": 7.0, "vote_count": 4},
    ]}}
    assert select_logo_path(details, "en-US") == "/en-high.png"
    assert select_logo_path(details, "fr-FR") == "/null.png"
    assert select_logo_path({}, "en-US") is None
    assert select_logo_path(None, "en-US") is None


def test_select_logo_skips_svg_even_with_highest_votes():
    details = {"images": {"logos": [
        {"file_path": "/best.svg", "iso_639_1": "en",
         "vote_average": 99.0, "vote_count": 999},
        {"file_path": "/second.png", "iso_639_1": "en",
         "vote_average": 5.0, "vote_count": 3},
    ]}}
    assert select_logo_path(details, "en-US") == "/second.png"


def test_select_logo_all_svg_pool_returns_none():
    details = {"images": {"logos": [
        {"file_path": "/one.svg", "iso_639_1": "en",
         "vote_average": 9.0, "vote_count": 9},
        {"file_path": "/two.SVG", "iso_639_1": None,
         "vote_average": 5.0, "vote_count": 5},
    ]}}
    assert select_logo_path(details, "en-US") is None
