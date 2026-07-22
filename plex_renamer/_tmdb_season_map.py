"""Strict TMDB season-map loading and payload validation."""

# pyright: strict

from __future__ import annotations

from typing import Any, Protocol, TypeAlias, TypeGuard, cast

from ._provider_errors import SeasonMapUnavailableError
from ._tmdb_transport import TMDBError

SeasonMap: TypeAlias = dict[int, dict[str, Any]]


class _JsonTransport(Protocol):
    def get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> object: ...


def _unavailable(show_id: int, reason: str) -> SeasonMapUnavailableError:
    return SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}: {reason}")


def _required_json(
    transport: _JsonTransport,
    path: str,
    params: dict[str, str] | None,
    show_id: int,
) -> dict[str, Any]:
    try:
        value = transport.get_json(path, params)
    except TMDBError as exc:
        raise _unavailable(show_id, str(exc)) from exc
    if value is None:
        raise _unavailable(show_id, "not found")
    if not isinstance(value, dict):
        raise _unavailable(show_id, "invalid response")
    return cast(dict[str, Any], value)


def _record_list(value: object, show_id: int, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _unavailable(show_id, f"invalid {label}")
    items = cast(list[object], value)
    if not all(isinstance(item, dict) for item in items):
        raise _unavailable(show_id, f"invalid {label}")
    return cast(list[dict[str, Any]], items)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_record_list(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return all(isinstance(item, dict) for item in cast(list[object], value))


def _valid_episode_identity(episode: dict[str, Any]) -> bool:
    number = episode.get("episode_number")
    name = episode.get("name", f"Episode {number}")
    still = episode.get("still_path")
    return _is_int(number) and isinstance(name, str) and (still is None or isinstance(still, str))


def _valid_episode_credits(episode: dict[str, Any]) -> bool:
    return _is_record_list(episode.get("guest_stars", [])) and _is_record_list(
        episode.get("crew", [])
    )


def _validate_episode(episode: dict[str, Any], show_id: int) -> None:
    if not _valid_episode_identity(episode):
        raise _unavailable(show_id, "invalid episode data")
    if not _valid_episode_credits(episode):
        raise _unavailable(show_id, "invalid episode data")


def _crew_names(crew: list[dict[str, Any]], jobs: tuple[str, ...]) -> list[str]:
    return [
        cast(str, member.get("name"))
        for member in crew
        if member.get("job") in jobs and member.get("name")
    ]


def _guest_star_metadata(guest_stars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": guest_star.get("name", ""),
            "character": guest_star.get("character", ""),
        }
        for guest_star in guest_stars[:5]
    ]


def _episode_metadata(
    episode: dict[str, Any],
    name: str,
    poster: str | None,
) -> dict[str, Any]:
    crew = cast(list[dict[str, Any]], episode.get("crew", []))
    guest_stars = cast(list[dict[str, Any]], episode.get("guest_stars", []))
    return {
        "name": name,
        "overview": episode.get("overview", ""),
        "air_date": episode.get("air_date", ""),
        "vote_average": episode.get("vote_average", 0),
        "vote_count": episode.get("vote_count", 0),
        "runtime": episode.get("runtime"),
        "still_path": poster,
        "directors": _crew_names(crew, ("Director",)),
        "writers": _crew_names(crew, ("Writer", "Teleplay", "Story")),
        "guest_stars": _guest_star_metadata(guest_stars),
    }


def _build_season_payload(
    raw: dict[str, Any],
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    titles: dict[int, str] = {}
    posters: dict[int, str | None] = {}
    metadata: dict[int, dict[str, Any]] = {}
    for episode in episodes:
        number = cast(int, episode.get("episode_number"))
        name = cast(str, episode.get("name", f"Episode {number}"))
        poster = cast(str | None, episode.get("still_path"))
        titles[number] = name
        posters[number] = poster
        metadata[number] = _episode_metadata(episode, name, poster)
    return {
        "titles": titles,
        "posters": posters,
        "episodes": metadata,
        "season_poster_path": raw.get("poster_path"),
    }


def _season_payload(
    transport: _JsonTransport,
    show_id: int,
    season_number: int,
) -> dict[str, Any]:
    raw = _required_json(
        transport,
        f"/tv/{show_id}/season/{season_number}",
        None,
        show_id,
    )
    episodes = _record_list(raw.get("episodes"), show_id, "season data")
    for episode in episodes:
        _validate_episode(episode, show_id)
    return _build_season_payload(raw, episodes)


def _season_identity(
    season: dict[str, Any],
    show_id: int,
) -> tuple[int, int, str]:
    number = season.get("season_number")
    episode_count = season.get("episode_count")
    name = season.get("name", "")
    if not _is_int(number) or not _is_int(episode_count):
        raise _unavailable(show_id, "invalid season details")
    if episode_count < 0 or not isinstance(name, str):
        raise _unavailable(show_id, "invalid season details")
    return number, episode_count, name


def _season_map_entry(
    transport: _JsonTransport,
    show_id: int,
    season: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    number, episode_count, name = _season_identity(season, show_id)
    payload = _season_payload(transport, show_id, number)
    titles = payload["titles"]
    count = max(titles) if titles else episode_count
    return number, {
        "name": name,
        "titles": titles,
        "posters": payload["posters"],
        "episodes": payload.get("episodes", {}),
        "count": count,
    }


def fetch_tmdb_season_map(
    transport: _JsonTransport,
    show_id: int,
    details_params: dict[str, str],
) -> tuple[SeasonMap, int]:
    """Fetch and validate a complete map without exposing partial results."""
    details = _required_json(transport, f"/tv/{show_id}", details_params, show_id)
    seasons = _record_list(details.get("seasons"), show_id, "details")
    season_map = dict(_season_map_entry(transport, show_id, item) for item in seasons)
    total = sum(payload["count"] for number, payload in season_map.items() if number > 0)
    return season_map, total
