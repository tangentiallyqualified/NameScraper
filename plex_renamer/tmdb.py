"""
TMDB (The Movie Database) API client.

Handles searching, metadata fetching, and image retrieval for both
TV series and movies.  No GUI dependency — returns plain data structures.

Performance features:
  - requests.Session for HTTP keep-alive (connection pooling)
  - In-memory caching for season data and show details to eliminate
    redundant API calls within a session
  - Parallel batch searching for movies and TV via ThreadPoolExecutor
  - Token-bucket rate limiter (~35 req/s, below TMDB's 40/s limit)
  - Retry with exponential backoff for transient errors (429, 5xx)
  - LRU-bounded image cache to prevent unbounded memory growth
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from typing import Any

from PIL import Image

from ._tmdb_transport import (
    TMDBAPIError,
    TMDBError,
    TMDBNetworkError,
    TMDBRateLimitError,
    TMDBTransport,
)
from ._tmdb_batch_search import (
    resolve_movie_batch_query,
    resolve_tv_batch_query,
    run_batch_search,
)
from ._tmdb_image_cache import _TMDBImageCacheStore
from ._tmdb_metadata_builder import (
    build_empty_season_payload,
    build_movie_search_results,
    build_season_payload,
    build_tv_search_results,
)
from ._tmdb_metadata_cache import _TMDBMetadataCacheStore
from ._tmdb_search_helpers import extract_alternative_titles, search_with_fallback as run_search_with_fallback


IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
API_BASE = "https://api.themoviedb.org/3"
_HTTP_POOL_CONNECTIONS = 16
_HTTP_POOL_MAXSIZE = 32

log = logging.getLogger(__name__)
# ─── Client ──────────────────────────────────────────────────────────────────

class TMDBClient:
    """
    TMDB client with connection pooling, response caching, rate limiting,
    and retry logic.

    Uses a requests.Session for HTTP keep-alive, which dramatically
    reduces latency when making many sequential API calls (avoids
    TCP+TLS handshake per request).

    Caches show details and season data in memory so repeated calls
    (e.g. scan → mismatch check → consolidated scan) don't hit the
    network again.
    """

    def __init__(self, api_key: str, rate_limit: float = 35.0,
                 max_retries: int = 2, image_cache_size: int = 200,
                 language: str = "en-US",
                 cache_service: Any | None = None,
                 refresh_policy: Any | None = None):
        self.api_key = api_key
        self.language = language
        self._cache_service = cache_service
        self._refresh_policy = refresh_policy
        self._transport = TMDBTransport(
            api_key=api_key,
            language=language,
            api_base=API_BASE,
            rate_limit=rate_limit,
            max_retries=max_retries,
            pool_connections=_HTTP_POOL_CONNECTIONS,
            pool_maxsize=_HTTP_POOL_MAXSIZE,
            logger=log,
        )
        self._session = self._transport.session
        self._rate_limiter = self._transport.rate_limiter
        self._max_retries = max_retries

        self._alt_titles_cache: dict[tuple[int, str], list[tuple[str, str]]] = {}

        self._metadata_cache_store = _TMDBMetadataCacheStore(
            cache_service=cache_service,
            refresh_policy=refresh_policy,
        )
        self._image_cache_store = _TMDBImageCacheStore(
            image_cache_size=image_cache_size,
            cache_service=cache_service,
        )

    # ─── Helpers ──────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Make a GET request to the TMDB API with rate limiting and retry."""
        return self._transport.get_json(path, params)

    def _get_safe(self, path: str, params: dict | None = None) -> dict | None:
        """Like _get() but catches TMDBError and returns None."""
        return self._transport.get_json_safe(path, params)

    # ─── TV Series ────────────────────────────────────────────────────

    def search_tv(self, query: str, year: str | None = None) -> list[dict]:
        """
        Search TMDB for TV series matching *query*.

        Returns a list of dicts with keys:
            id, name, year, poster_path, overview
        """
        params: dict[str, Any] = {"query": query}
        if year:
            params["first_air_date_year"] = year

        return build_tv_search_results(self._get_safe("/search/tv", params))

    def get_tv_details(self, show_id: int) -> dict | None:
        """Fetch full show details (seasons list, etc.). Cached."""
        cached = self._metadata_cache_store.show_cache.get(show_id)
        if cached is not None:
            return cached
        persisted = self._metadata_cache_store.get_tv_details(show_id)
        if persisted is not None:
            self._metadata_cache_store.show_cache[show_id] = persisted
            return persisted
        data = self._get_safe(f"/tv/{show_id}")
        if data:
            self._metadata_cache_store.show_cache[show_id] = data
            self._metadata_cache_store.put_tv_details(
                show_id,
                data,
                show_status=data.get("status"),
            )
        return data

    def get_season(self, show_id: int, season_num: int) -> dict:
        """
        Fetch episode list for a season. Cached.

        Returns:
            {
                "titles": {ep_num: title, ...},
                "posters": {ep_num: still_path_or_None, ...},
                "episodes": {ep_num: {full episode metadata}, ...},
            }
        """
        cache_key = (show_id, season_num)
        cached = self._metadata_cache_store.season_cache.get(cache_key)
        if cached is not None:
            return cached

        persisted = self._metadata_cache_store.get_season(show_id, season_num)
        if persisted is not None:
            self._metadata_cache_store.season_cache[cache_key] = persisted
            return persisted

        data = self._get_safe(f"/tv/{show_id}/season/{season_num}")
        if not data:
            result = build_empty_season_payload()
            self._metadata_cache_store.season_cache[cache_key] = result
            return result

        result = build_season_payload(data)
        self._metadata_cache_store.season_cache[cache_key] = result
        self._metadata_cache_store.put_season(show_id, season_num, result)
        return result

    def get_season_map(self, show_id: int) -> tuple[dict, int]:
        """
        Build a complete map of TMDB's season structure for a show. Cached.

        Returns:
            tmdb_seasons: {season_num: {"titles": {...}, "posters": {...}, "episodes": {...}, "count": int}}
            total_episodes: total across non-special seasons
        """
        cached = self._metadata_cache_store.season_map_cache.get(show_id)
        if cached is not None:
            return cached

        show_data = self.get_tv_details(show_id)
        if not show_data:
            return {}, 0

        tmdb_seasons = {}
        total_episodes = 0

        for season_info in show_data.get("seasons", []):
            sn = season_info.get("season_number", 0)
            season_data = self.get_season(show_id, sn)
            titles = season_data["titles"]
            count = max(titles.keys()) if titles else season_info.get("episode_count", 0)
            tmdb_seasons[sn] = {
                "titles": titles,
                "posters": season_data["posters"],
                "episodes": season_data.get("episodes", {}),
                "count": count,
            }
            if sn > 0:
                total_episodes += count

        cached = (tmdb_seasons, total_episodes)
        self._metadata_cache_store.season_map_cache[show_id] = cached
        return cached

    # ─── Movies ───────────────────────────────────────────────────────

    def search_movie(self, query: str, year: str | None = None) -> list[dict]:
        """
        Search TMDB for movies matching *query*.

        Returns a list of dicts with keys:
            id, title, year, poster_path, overview
        """
        params: dict[str, Any] = {"query": query}
        if year:
            params["year"] = year

        return build_movie_search_results(self._get_safe("/search/movie", params))

    def get_movie_details(self, movie_id: int) -> dict | None:
        """Fetch full movie details. Cached."""
        cached = self._metadata_cache_store.movie_cache.get(movie_id)
        if cached is not None:
            return cached
        persisted = self._metadata_cache_store.get_movie_details(movie_id)
        if persisted is not None:
            self._metadata_cache_store.movie_cache[movie_id] = persisted
            return persisted
        data = self._get_safe(f"/movie/{movie_id}")
        if data:
            self._metadata_cache_store.movie_cache[movie_id] = data
            self._metadata_cache_store.put_movie_details(movie_id, data)
        return data

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie",
    ) -> list[tuple[str, str]]:
        """
        Fetch alternative/AKA titles for a movie or TV show. Cached.

        Args:
            media_id: TMDB ID.
            media_type: ``"movie"`` or ``"tv"``.

        Returns:
            List of ``(title, country_code)`` tuples where *country_code*
            is the ISO 3166-1 alpha-2 code (e.g. ``"US"``, ``"FR"``).
        """
        cache_key = (media_id, media_type)
        if cache_key in self._alt_titles_cache:
            return self._alt_titles_cache[cache_key]

        data = self._get_safe(f"/{media_type}/{media_id}/alternative_titles")
        if not data:
            log.warning(
                "Alt titles: no data returned for %s/%s", media_type, media_id)
            self._alt_titles_cache[cache_key] = []
            return []

        entries = data.get("titles") or data.get("results") or []
        log.debug(
            "Alt titles for %s/%s: %d entries in response",
            media_type, media_id, len(entries),
        )
        titles = extract_alternative_titles(data)
        log.info(
            "Alt titles for %s/%s: %d unique titles — %s",
            media_type, media_id, len(titles),
            [(t, c) for t, c in titles[:5]],
        )
        self._alt_titles_cache[cache_key] = titles
        return titles

    def search_movies_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable | None = None,
    ) -> list[list[dict]]:
        """
        Search TMDB for multiple movies in parallel.

        Args:
            queries: List of (search_query, year_hint_or_None) tuples.
            max_workers: Thread pool size (rate limiter handles throughput).
            progress_callback: Called with (completed_count, total) after
                each search finishes.  Runs from worker threads — must be
                thread-safe (e.g. just updating a counter).

        Returns:
            A list of result lists, one per query, in the same order as
            the input queries.
        """
        return run_batch_search(
            queries,
            search_query=lambda query, year: resolve_movie_batch_query(
                query,
                year,
                search_with_fallback=self.search_with_fallback,
                search_fn=self.search_movie,
            ),
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable | None = None,
    ) -> list[list[dict]]:
        """
        Search TMDB for multiple TV shows in parallel.

        Args:
            queries: List of (search_query, year_hint_or_None) tuples.
            max_workers: Thread pool size (rate limiter handles throughput).
            progress_callback: Called with (completed_count, total) after
                each search finishes.  Thread-safe.

        Returns:
            A list of result lists, one per query, in the same order as
            the input queries.
        """
        return run_batch_search(
            queries,
            search_query=lambda query, year: resolve_tv_batch_query(
                query,
                year,
                search_with_fallback=self.search_with_fallback,
                search_fn=self.search_tv,
            ),
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

    # ─── Fallback search ─────────────────────────────────────────────

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable,
        min_words: int = 1,
        **kwargs,
    ) -> list[dict]:
        """
        Search TMDB with progressive query trimming.

        If the full query returns no results, trims one word at a time
        from the end and retries.  Handles filenames with trailing junk
        that doesn't match any known release-noise pattern.

        Args:
            query: The full search query string.
            search_fn: Bound method like self.search_tv or self.search_movie.
            min_words: Stop trimming when the query has fewer words than this.
            **kwargs: Extra arguments passed to search_fn (e.g. year=).

        Returns the first non-empty result list, or [].
        """
        return run_search_with_fallback(
            query,
            search_fn,
            min_words=min_words,
            **kwargs,
        )

    # ─── Images ───────────────────────────────────────────────────────

    def fetch_image(
        self,
        image_path: str | None,
        target_width: int = 300,
    ) -> Image.Image | None:
        """
        Download and scale an image from TMDB. Cached with LRU eviction.

        Args:
            image_path: The TMDB image path (e.g. "/abc123.jpg").
                If None, returns None.
            target_width: Scale image to this pixel width.

        Returns a PIL Image or None on failure.
        """
        if not image_path:
            return None
        cached = self._image_cache_store.get_image(image_path, target_width)
        if cached is not None:
            return cached
        source = self._image_cache_store.get_source_image(image_path)
        if source is None:
            try:
                payload = self._transport.fetch_bytes(IMAGE_BASE_URL + image_path)
                source = Image.open(io.BytesIO(payload))
                source.load()
                self._image_cache_store.store_source_image(image_path, source)
            except (TMDBNetworkError, OSError, ValueError) as e:
                log.debug("Failed to fetch image %s: %s", image_path, e)
                return None

        try:
            scale = target_width / source.width
            new_h = int(source.height * scale)
            img = source.resize((target_width, new_h), Image.LANCZOS)
            self._image_cache_store.store_image(image_path, target_width, img)
            return img
        except (OSError, ValueError) as e:
            log.debug("Failed to fetch image %s: %s", image_path, e)
            return None

    def fetch_poster(
        self,
        media_id: int,
        media_type: str = "tv",
        season: int | None = None,
        ep_still: str | None = None,
        target_width: int = 300,
    ) -> Image.Image | None:
        """
        Fetch the best available poster/still for a media item.

        Priority: ep_still → season poster → show/movie poster.
        Uses cached data where available to avoid extra API calls.
        """
        cached = self._image_cache_store.get_poster(
            media_id=media_id,
            media_type=media_type,
            season=season,
            ep_still=ep_still,
            target_width=target_width,
        )
        if cached is not None:
            return cached

        # Try episode still first
        if ep_still:
            img = self.fetch_image(ep_still, target_width)
            if img:
                self._image_cache_store.store_poster(
                    media_id=media_id,
                    media_type=media_type,
                    season=season,
                    ep_still=ep_still,
                    target_width=target_width,
                    image=img,
                )
                return img

        # Try season poster (TV only) — read from cache, no extra API call
        if media_type == "tv" and season is not None:
            cache_key = (media_id, season)
            if cache_key not in self._metadata_cache_store.season_cache:
                self.get_season(media_id, season)  # populates cache
            cached = self._metadata_cache_store.season_cache.get(cache_key)
            if cached and cached.get("season_poster_path"):
                img = self.fetch_image(cached["season_poster_path"], target_width)
                if img:
                    self._image_cache_store.store_poster(
                        media_id=media_id,
                        media_type=media_type,
                        season=season,
                        ep_still=ep_still,
                        target_width=target_width,
                        image=img,
                    )
                    return img

        # Fall back to show/movie poster — use cache for both TV and movies
        if media_type == "tv" and media_id in self._metadata_cache_store.show_cache:
            data = self._metadata_cache_store.show_cache[media_id]
        elif media_type == "movie" and media_id in self._metadata_cache_store.movie_cache:
            data = self._metadata_cache_store.movie_cache[media_id]
        else:
            data = self._get_safe(f"/{media_type}/{media_id}")
        if data and data.get("poster_path"):
            img = self.fetch_image(data["poster_path"], target_width)
            if img:
                self._image_cache_store.store_poster(
                    media_id=media_id,
                    media_type=media_type,
                    season=season,
                    ep_still=ep_still,
                    target_width=target_width,
                    image=img,
                )
            return img

        return None

    def get_cached_poster_path(self, media_id: int, media_type: str = "tv") -> str | None:
        """Return a cached poster path for a media item without making network calls."""
        return self._metadata_cache_store.get_cached_poster_path(media_id, media_type)

    def clear_cache(self) -> None:
        """Clear all in-memory caches. Useful when switching shows."""
        self._metadata_cache_store.clear_runtime_caches()
        self._image_cache_store.clear_runtime_caches()

    def export_cache_snapshot(self) -> dict[str, dict]:
        """Return a serializable snapshot of the in-memory metadata caches."""
        return self._metadata_cache_store.export_snapshot()

    def import_cache_snapshot(self, snapshot: dict | None, *, clear_existing: bool = False) -> None:
        """Hydrate the in-memory metadata caches from a persisted snapshot."""
        if not snapshot:
            return
        if clear_existing:
            self._image_cache_store.clear_runtime_caches()
        self._metadata_cache_store.import_snapshot(snapshot, clear_existing=clear_existing)
