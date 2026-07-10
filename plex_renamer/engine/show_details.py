"""Provider-neutral show detail payload.

The only shape resolution logic may read show-level metadata through;
provider adapters (TMDB today, TVDB later) normalize their raw payloads
into this dataclass. Keeping the raw JSON out of match policy means a
second metadata provider only needs a new ``show_details_from_*``
adapter, not resolution changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeasonSummary:
    season_number: int
    episode_count: int


@dataclass(frozen=True)
class ShowDetails:
    id: object
    number_of_episodes: int
    number_of_seasons: int
    first_air_date: str | None  # ISO YYYY-MM-DD or None
    unaired: bool  # provider-mapped "not yet airing" semantics
    seasons: tuple[SeasonSummary, ...] = ()


_TMDB_UNAIRED_STATUSES = {"Planned", "In Production"}


def show_details_from_tmdb(raw: dict | None) -> ShowDetails | None:
    """Normalize a raw TMDB TV-details payload.

    ``None`` in -> ``None`` out: a failed fetch stays distinguishable from a
    genuinely empty show, so callers can abstain instead of ranking on
    fabricated zeros.
    """
    if raw is None:
        return None
    return ShowDetails(
        id=raw.get("id"),
        number_of_episodes=raw.get("number_of_episodes") or 0,
        number_of_seasons=raw.get("number_of_seasons") or 0,
        first_air_date=raw.get("first_air_date") or None,
        unaired=(
            not raw.get("first_air_date")
            or raw.get("status") in _TMDB_UNAIRED_STATUSES
        ),
        seasons=tuple(
            SeasonSummary(
                season_number=season.get("season_number", -1),
                episode_count=season.get("episode_count") or 0,
            )
            for season in (raw.get("seasons") or [])
        ),
    )
