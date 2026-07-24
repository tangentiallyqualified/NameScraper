"""Metadata-provider protocol and registry.

``MetadataProvider`` is the exact surface the engine, GUI, and
metadata-export planner consume from a metadata client. Payload shapes
are the TMDB-flavored dicts documented on each method; every provider
normalizes its raw API responses into these shapes at its own boundary.
Image references (``poster_path``/``still_path``/logo ``file_path``)
are either TMDB-style relative paths ("/abc.jpg") or absolute
"https://..." URLs — image helpers must accept both.

Future sources: add a ``ProviderSpec`` to ``TV_PROVIDERS``. Future
fallback logic: wrap providers in a composite that itself satisfies
``MetadataProvider`` and register it here — the engine never changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from PIL import Image

from ._provider_errors import SeasonMapUnavailableError as SeasonMapUnavailableError
from .metadata_types import MediaInfo


@runtime_checkable
class MetadataProvider(Protocol):
    """Structural port for TV metadata clients (TMDB today, TVDB, ...)."""

    provider_name: str
    language: str

    def search_tv(self, query: str, year: str | None = None) -> list[MediaInfo]:
        """[{"id": int, "name": str, "year": str, "poster_path": str|None,
        "overview": str}, ...] — best matches first."""
        ...

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., object] | None = None,
    ) -> list[list[MediaInfo]]:
        """One search_tv result list per (query, year_hint) input, same order."""
        ...

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable[..., list[MediaInfo]],
        min_words: int = 1,
        **kwargs: object,
    ) -> list[MediaInfo]:
        """Progressive word-trimming retry around *search_fn*."""
        ...

    def get_tv_details(self, show_id: int) -> dict[str, Any] | None:
        """TMDB-shaped show details or None on fetch failure. Consumed keys:
        id, name, overview, first_air_date ("YYYY-MM-DD" or ""), status
        (TMDB vocabulary: "Ended"/"Returning Series"/"Planned"/...),
        genres [{"name"}], networks [{"name"}], episode_run_time [int],
        vote_average, vote_count, poster_path, backdrop_path,
        images {"logos": [{"file_path", "iso_639_1"}]},
        credits {"cast": [{"name", "character", "order"}]},
        seasons [{"season_number", "episode_count", "name"}],
        number_of_seasons, number_of_episodes (specials excluded)."""
        ...

    def get_season(self, show_id: int, season_num: int) -> dict[str, Any]:
        """{"titles": {ep: str}, "posters": {ep: str|None},
        "episodes": {ep: meta}, "season_poster_path": str|None}.
        Episode meta keys: name, overview, air_date, runtime,
        vote_average, vote_count, still_path, directors [str],
        writers [str], guest_stars [{"name", "character"}]."""
        ...

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        """({season_num: {"name", "titles", "posters", "episodes",
        "count", "season_poster_path"}}, total_episodes_excl_specials)."""
        ...

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        """[(title, iso3166_country_or_empty), ...]."""
        ...

    def fetch_image(self, image_path: str | None, target_width: int = 300) -> Image.Image | None:
        """Scaled PIL image for UI display, or None."""
        ...

    def fetch_poster(
        self,
        media_id: int,
        media_type: str = "tv",
        season: int | None = None,
        ep_still: str | None = None,
        target_width: int = 300,
    ) -> Image.Image | None:
        """Best poster: ep_still -> season poster -> show poster."""
        ...

    def fetch_image_bytes(self, image_path: str | None, size: str = "original") -> bytes | None:
        """Raw export-size bytes, or None (= artwork unavailable)."""
        ...

    def get_cached_poster_path(self, media_id: int, media_type: str = "tv") -> str | None:
        """Cached poster ref without network I/O."""
        ...

    def clear_cache(self) -> None:
        """Drop in-memory caches (persistent cache_service data survives)."""
        ...


@dataclass(frozen=True)
class ProviderSpec:
    """Registry entry: settings value, UI label, keys.py service, factory."""

    name: str
    label: str
    key_service: str
    factory: Callable[..., MetadataProvider]


def _make_tmdb(api_key: str, **kwargs: Any) -> MetadataProvider:
    from .tmdb import TMDBClient

    return TMDBClient(api_key, **kwargs)


def _make_tvdb(api_key: str, **kwargs: Any) -> MetadataProvider:
    from .tvdb import TVDBClient

    return TVDBClient(api_key, **kwargs)


TV_PROVIDERS: dict[str, ProviderSpec] = {
    "tmdb": ProviderSpec("tmdb", "TMDB", "TMDB", _make_tmdb),
    "tvdb": ProviderSpec("tvdb", "TheTVDB", "TVDB", _make_tvdb),
}


def get_tv_provider_spec(name: str) -> ProviderSpec:
    """Spec for *name*, falling back to TMDB for unknown values."""
    return TV_PROVIDERS.get(name, TV_PROVIDERS["tmdb"])


def other_tv_provider_spec(active_name: str) -> ProviderSpec | None:
    """The non-active TV provider spec, or ``None`` when there isn't one.

    Shared by every caller that needs "the other" provider regardless of
    whether it's currently playing an active or a fallback role (e.g. the
    settings tab's fallback-availability check and the tmdb coordinator's
    non-active-provider client) — exactly two providers exist today, so
    this is just "not the active one".
    """
    active = get_tv_provider_spec(active_name).name
    return next((spec for name, spec in TV_PROVIDERS.items() if name != active), None)
