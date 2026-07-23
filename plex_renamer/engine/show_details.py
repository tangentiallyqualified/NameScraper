"""Provider-neutral show detail payload.

The only shape resolution logic may read show-level metadata through;
provider adapters (TMDB today, TVDB later) normalize their raw payloads
into this dataclass. Keeping the raw JSON out of match policy means a
second metadata provider only needs a new ``show_details_from_*``
adapter, not resolution changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SeasonSummary:
    season_number: int
    episode_count: int
    name: str = ""


@dataclass(frozen=True)
class ShowDetails:
    id: int | None
    name: str
    overview: str
    poster_path: str | None
    number_of_episodes: int
    number_of_seasons: int
    first_air_date: str | None  # ISO YYYY-MM-DD or None
    unaired: bool  # provider-mapped "not yet airing" semantics
    seasons: tuple[SeasonSummary, ...] = ()


_TMDB_UNAIRED_STATUSES = {"Planned", "In Production"}


def _int_or_none(value: object) -> int | None:
    return value if type(value) is int else None


def _int_or_zero(value: object) -> int:
    narrowed = _int_or_none(value)
    return narrowed if narrowed is not None else 0


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _object_mapping(value: object) -> Mapping[object, object] | None:
    return value if isinstance(value, Mapping) else None


def _object_sequence(value: object) -> Sequence[object] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    return value


def _season_summaries(value: object) -> tuple[SeasonSummary, ...]:
    records = _object_sequence(value)
    if records is None:
        return ()
    summaries: list[SeasonSummary] = []
    for record in records:
        season = _object_mapping(record)
        if season is None:
            continue
        season_number = _int_or_none(season.get("season_number"))
        if season_number is None:
            continue
        summaries.append(
            SeasonSummary(
                season_number=season_number,
                episode_count=_int_or_zero(season.get("episode_count")),
                name=_string_or_empty(season.get("name")),
            )
        )
    return tuple(summaries)


def show_details_from_tmdb(raw: Mapping[str, object] | None) -> ShowDetails | None:
    """Normalize a raw TMDB TV-details payload.

    ``None`` in -> ``None`` out: a failed fetch stays distinguishable from a
    genuinely empty show, so callers can abstain instead of ranking on
    fabricated zeros.
    """
    if raw is None:
        return None
    first_air_date = _string_or_none(raw.get("first_air_date"))
    return ShowDetails(
        id=_int_or_none(raw.get("id")),
        name=_string_or_empty(raw.get("name")),
        overview=_string_or_empty(raw.get("overview")),
        poster_path=_string_or_none(raw.get("poster_path")),
        number_of_episodes=_int_or_zero(raw.get("number_of_episodes")),
        number_of_seasons=_int_or_zero(raw.get("number_of_seasons")),
        first_air_date=first_air_date,
        unaired=(
            not first_air_date or _string_or_empty(raw.get("status")) in _TMDB_UNAIRED_STATUSES
        ),
        seasons=_season_summaries(raw.get("seasons")),
    )
