# pyright: strict

"""Strict runtime and static checks for TVDB scalar search records."""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

import pytest

from plex_renamer.metadata_types import MediaInfo
from plex_renamer.providers import MetadataProvider
from plex_renamer.tvdb import TVDBClient, TVDBTransport


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


def test_search_tv_normalizes_malformed_scalars_and_rejects_unusable_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response: dict[str, object] = {
        "data": [
            {
                "tvdb_id": "81189",
                "name": {"nested": "name"},
                "year": ["2008"],
                "image_url": {"nested": "poster"},
                "overview": ["nested overview"],
            },
            {
                "tvdb_id": 42,
                "name": "Second",
                "year": "2024",
                "image_url": 404,
                "overview": None,
            },
            {"tvdb_id": True, "name": "Boolean ID"},
            {"tvdb_id": 8.5, "name": "Float ID"},
            {"tvdb_id": ["9"], "name": "Nested ID"},
        ]
    }

    def get_json_safe(
        _transport: TVDBTransport,
        path: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        assert path == "/search"
        assert params == {"query": "malformed", "type": "series"}
        return response

    monkeypatch.setattr(TVDBTransport, "get_json_safe", get_json_safe)

    assert TVDBClient("fake-key").search_tv("malformed") == [
        {
            "id": 81189,
            "name": "",
            "year": "",
            "poster_path": None,
            "overview": "",
        },
        {
            "id": 42,
            "name": "Second",
            "year": "2024",
            "poster_path": None,
            "overview": "",
        },
    ]


def test_search_with_fallback_preserves_media_info_identity() -> None:
    client = TVDBClient("fake-key")
    media_info: MediaInfo = {"id": 81189, "name": "Breaking Bad"}

    def search(_query: str, year: str | None = None) -> list[MediaInfo]:
        assert year == "2008"
        return [media_info]

    results = client.search_with_fallback("breaking bad", search, year="2008")

    assert results[0] is media_info
