from __future__ import annotations

from plex_renamer.metadata_types import (
    MediaInfo,
    is_media_info,
    media_info_int,
    media_info_optional_str,
    media_info_str,
)


def test_media_info_accessors_preserve_valid_scalars() -> None:
    info: MediaInfo = {"id": 7, "title": "Movie", "year": "2024"}

    assert media_info_int(info, "id") == 7
    assert media_info_str(info, "title") == "Movie"
    assert media_info_optional_str(info, "year") == "2024"


def test_media_info_accessors_reject_wrong_scalar_kinds() -> None:
    info: MediaInfo = {"id": "7", "title": 42, "year": 2024.0}

    assert media_info_int(info, "id") is None
    assert media_info_str(info, "title") == ""
    assert media_info_str(info, "title", "fallback") == "fallback"
    assert media_info_optional_str(info, "year") is None


def test_media_info_int_rejects_boolean_ids() -> None:
    info: MediaInfo = {"id": True}

    assert media_info_int(info, "id") is None


def test_is_media_info_accepts_only_scalar_string_keyed_dicts() -> None:
    assert is_media_info({"id": 7, "title": "Movie", "year": None})
    assert not is_media_info(None)
    assert not is_media_info({1: "Movie"})
    assert not is_media_info({"title": ["Movie"]})
