"""Provider-normalized scalar metadata records."""

from __future__ import annotations

from typing import TypeAlias, TypeGuard

MediaInfoValue: TypeAlias = str | int | float | None
MediaInfo: TypeAlias = dict[str, MediaInfoValue]
ScoredMediaInfo: TypeAlias = list[tuple[MediaInfo, float]]


def media_info_str(info: MediaInfo, key: str, default: str = "") -> str:
    """Return a string metadata field or its exact fallback."""
    value = info.get(key, default)
    return value if isinstance(value, str) else default


def media_info_optional_str(info: MediaInfo, key: str) -> str | None:
    """Return a string metadata field, excluding wrong scalar kinds."""
    value = info.get(key)
    return value if isinstance(value, str) else None


def media_info_int(info: MediaInfo, key: str) -> int | None:
    """Return a true integer metadata field, excluding bool and other scalars."""
    value = info.get(key)
    return value if type(value) is int else None


def is_media_info(value: object) -> TypeGuard[MediaInfo]:
    """Return whether *value* is a mutable scalar metadata record."""
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(key, str) and (item is None or isinstance(item, (str, int, float)))
        for key, item in value.items()
    )
