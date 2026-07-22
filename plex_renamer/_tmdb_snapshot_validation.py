"""Strict normalization helpers for persisted TMDB season-map snapshots."""

# pyright: strict

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal, TypeAlias, cast

SeasonMap: TypeAlias = dict[int, dict[str, Any]]
SeasonMapCacheEntry: TypeAlias = tuple[int, tuple[SeasonMap, int]]
_EpisodeValueKind: TypeAlias = Literal["titles", "posters", "episodes"]


def _require_mapping(value: object, message: str) -> dict[object, object]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return cast(dict[object, object], value)


def _normalize_snapshot_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("identifier must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("identifier must be an integer") from exc


def _normalize_non_negative_int(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(message)
    return value


def _validate_episode_value(value: object, value_kind: _EpisodeValueKind) -> None:
    if value_kind == "titles" and not isinstance(value, str):
        raise ValueError("episode title must be text")
    if value_kind == "posters" and value is not None and not isinstance(value, str):
        raise ValueError("episode poster must be text or null")
    if value_kind == "episodes" and not isinstance(value, dict):
        raise ValueError("episode metadata must be a mapping")


def _normalize_snapshot_episode_map(
    mapping: object,
    *,
    value_kind: _EpisodeValueKind,
) -> dict[int, Any]:
    raw_mapping = _require_mapping(mapping, f"{value_kind} must be a mapping")
    normalized: dict[int, Any] = {}
    for key, value in raw_mapping.items():
        episode_num = _normalize_snapshot_int(key)
        _validate_episode_value(value, value_kind)
        normalized[episode_num] = value
    return normalized


def _copy_optional_season_poster(
    normalized: dict[str, Any],
    season_data: dict[object, object],
) -> None:
    if "season_poster_path" not in season_data:
        return
    season_poster_path = season_data.get("season_poster_path")
    if season_poster_path is not None and not isinstance(season_poster_path, str):
        raise ValueError("season poster must be text or null")
    normalized["season_poster_path"] = season_poster_path


def _normalize_season_snapshot_payload(season_data: object) -> dict[str, Any]:
    raw_season = _require_mapping(season_data, "season-map payload must be a mapping")
    name = raw_season.get("name")
    if not isinstance(name, str):
        raise ValueError("season name must be text")
    count = _normalize_non_negative_int(
        raw_season.get("count"),
        "season count must be a non-negative integer",
    )
    normalized: dict[str, Any] = {
        "name": name,
        "titles": _normalize_snapshot_episode_map(raw_season.get("titles"), value_kind="titles"),
        "posters": _normalize_snapshot_episode_map(raw_season.get("posters"), value_kind="posters"),
        "episodes": _normalize_snapshot_episode_map(
            raw_season.get("episodes"), value_kind="episodes"
        ),
        "count": count,
    }
    _copy_optional_season_poster(normalized, raw_season)
    return normalized


def normalize_season_map_snapshot(season_map: object) -> SeasonMap:
    """Validate and normalize one persisted season map."""
    raw_season_map = _require_mapping(season_map, "season map must be a mapping")
    normalized: SeasonMap = {}
    for season_key, season_data in raw_season_map.items():
        season_num = _normalize_snapshot_int(season_key)
        normalized[season_num] = _normalize_season_snapshot_payload(season_data)
    return normalized


def _normalize_season_map_cache_entry(show_id: object, data: object) -> SeasonMapCacheEntry:
    normalized_show_id = _normalize_snapshot_int(show_id)
    raw_entry = _require_mapping(data, "season-map entry must be a mapping")
    total_episodes = _normalize_non_negative_int(
        raw_entry.get("total_episodes"),
        "invalid total episode count",
    )
    normalized_map = normalize_season_map_snapshot(raw_entry.get("seasons"))
    return normalized_show_id, (normalized_map, total_episodes)


def iter_valid_season_map_snapshots(value: object) -> Iterator[SeasonMapCacheEntry]:
    """Yield valid cache entries while skipping malformed entries independently."""
    raw_cache = _require_mapping(value, "season-map cache must be a mapping")
    for show_id, data in raw_cache.items():
        try:
            normalized = _normalize_season_map_cache_entry(show_id, data)
        except (TypeError, ValueError):
            continue
        yield normalized
