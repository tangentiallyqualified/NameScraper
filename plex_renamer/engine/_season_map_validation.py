"""Provider season-map validation at the TV scanner boundary."""

# pyright: strict

from __future__ import annotations

from typing import Any, NoReturn, TypeAlias, cast

from ..providers import SeasonMapUnavailableError

SeasonMap: TypeAlias = dict[int, dict[str, Any]]


def _malformed(message: str = "malformed season map entry") -> NoReturn:
    raise SeasonMapUnavailableError(message)


def _require_mapping(value: object) -> dict[object, object]:
    if not isinstance(value, dict):
        _malformed()
    return cast(dict[object, object], value)


def _require_episode_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _malformed()
    return value


def _require_episode_count(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _malformed()


def _validate_episode_titles(value: object) -> None:
    for episode_number, title in _require_mapping(value).items():
        _require_episode_number(episode_number)
        if not isinstance(title, str):
            _malformed()


def _validate_episode_posters(value: object) -> None:
    for episode_number, poster in _require_mapping(value).items():
        _require_episode_number(episode_number)
        if poster is not None and not isinstance(poster, str):
            _malformed()


def _validate_episode_metadata(value: object) -> None:
    for episode_number, metadata in _require_mapping(value).items():
        _require_episode_number(episode_number)
        if not isinstance(metadata, dict):
            _malformed()


def _validate_optional_season_fields(payload: dict[object, object]) -> None:
    if "name" in payload and not isinstance(payload["name"], str):
        _malformed()
    if "season_poster_path" not in payload:
        return
    season_poster = payload["season_poster_path"]
    if season_poster is not None and not isinstance(season_poster, str):
        _malformed()


def _validate_season_payload(value: object) -> dict[str, Any]:
    payload = _require_mapping(value)
    _validate_episode_titles(payload.get("titles"))
    _validate_episode_posters(payload.get("posters"))
    _validate_episode_metadata(payload.get("episodes"))
    _require_episode_count(payload.get("count"))
    _validate_optional_season_fields(payload)
    return cast(dict[str, Any], payload)


def normalize_season_map(value: object) -> SeasonMap:
    """Validate provider output without rewriting its already-normalized payloads."""
    if not isinstance(value, dict):
        _malformed("malformed season map: expected mapping")
    raw_season_map = cast(dict[object, object], value)
    normalized: SeasonMap = {}
    for raw_season, payload in raw_season_map.items():
        season_num = _require_episode_number(raw_season)
        normalized[season_num] = _validate_season_payload(payload)
    return normalized
