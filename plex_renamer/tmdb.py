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
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from PIL import Image


IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
API_BASE = "https://api.themoviedb.org/3"

log = logging.getLogger(__name__)


# ─── Error types ─────────────────────────────────────────────────────────────

class TMDBError(Exception):
    """Base class for TMDB client errors."""


class TMDBNetworkError(TMDBError):
    """Network or connection failure — transient, may be retried."""


class TMDBRateLimitError(TMDBError):
    """API rate limit hit (HTTP 429)."""


class TMDBAPIError(TMDBError):
    """Non-retryable API error (4xx other than 429)."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(f"TMDB API error {status_code}: {message}")


# ─── Rate limiter ────────────────────────────────────────────────────────────

class _TokenBucket:
    """
    Simple token-bucket rate limiter.

    Allows up to *rate* requests per second with a burst capacity
    equal to *rate*.  Thread-safe.
    """

    def __init__(self, rate: float = 35.0):
        self._rate = rate
        self._tokens = rate
        self._max_tokens = rate
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._max_tokens,
                    self._tokens + elapsed * self._rate,
                )
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # Sleep briefly and retry
            time.sleep(0.02)


# ─── LRU image cache ────────────────────────────────────────────────────────

class _LRUImageCache:
    """
    Bounded LRU cache for PIL Images.

    Evicts the least-recently-used entry when *max_size* is exceeded.
    Thread-safe.
    """

    def __init__(self, max_size: int = 200):
        self._max_size = max_size
        self._cache: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Image.Image | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, key: tuple, value: Image.Image) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
            self._cache[key] = value

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


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
                 language: str = "en-US"):
        self.api_key = api_key
        self.language = language
        self._session = requests.Session()
        self._rate_limiter = _TokenBucket(rate_limit)
        self._max_retries = max_retries

        # In-memory caches keyed by (show_id,) or (show_id, season_num)
        self._show_cache: dict[int, dict] = {}
        self._season_cache: dict[tuple[int, int], dict] = {}
        self._season_map_cache: dict[int, tuple[dict, int]] = {}
        self._movie_cache: dict[int, dict] = {}
        self._alt_titles_cache: dict[tuple[int, str], list[tuple[str, str]]] = {}

        # LRU-bounded image cache keyed by (image_path, target_width)
        self._image_cache = _LRUImageCache(max_size=image_cache_size)

    # ─── Helpers ──────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """
        Make a GET request to the TMDB API with rate limiting and retry.

        Returns JSON dict on success, None if the resource was not found
        (404).  Raises TMDBError subclasses for other failures so callers
        can distinguish transient vs permanent errors.
        """
        url = f"{API_BASE}{path}"
        all_params = {"api_key": self.api_key, "language": self.language}
        if params:
            all_params.update(params)

        last_exc: Exception | None = None

        for attempt in range(1 + self._max_retries):
            self._rate_limiter.acquire()

            try:
                r = self._session.get(url, params=all_params, timeout=10)
            except requests.RequestException as e:
                last_exc = TMDBNetworkError(str(e))
                if attempt < self._max_retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise last_exc from e

            if r.ok:
                return r.json()

            if r.status_code == 404:
                return None

            if r.status_code == 429:
                # Rate limited — wait and retry
                retry_after = float(r.headers.get("Retry-After", 1.5))
                log.warning("TMDB rate limit hit, waiting %.1fs", retry_after)
                last_exc = TMDBRateLimitError(
                    f"Rate limited (attempt {attempt + 1})")
                time.sleep(retry_after)
                continue

            if r.status_code >= 500:
                # Server error — retry with backoff
                last_exc = TMDBNetworkError(
                    f"Server error {r.status_code} (attempt {attempt + 1})")
                if attempt < self._max_retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise last_exc

            # 4xx (other than 404/429) — not retryable
            raise TMDBAPIError(r.status_code, r.text[:200])

        # Exhausted retries
        if last_exc:
            raise last_exc
        return None

    def _get_safe(self, path: str, params: dict | None = None) -> dict | None:
        """
        Like _get() but catches TMDBError and returns None.

        Use this for non-critical paths (images, supplementary data)
        where a failure shouldn't crash the operation.  For critical
        paths (search, season fetch), prefer _get() and handle errors
        explicitly.
        """
        try:
            return self._get(path, params)
        except TMDBError as e:
            log.warning("TMDB request failed for %s: %s", path, e)
            return None

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

        data = self._get_safe("/search/tv", params)
        if not data:
            return []

        results = []
        for show in data.get("results", []):
            air_date = show.get("first_air_date") or ""
            year = air_date[:4] if len(air_date) >= 4 else ""
            results.append({
                "id": show["id"],
                "name": show["name"],
                "year": year,
                "poster_path": show.get("poster_path"),
                "overview": show.get("overview", ""),
            })
        return results

    def get_tv_details(self, show_id: int) -> dict | None:
        """Fetch full show details (seasons list, etc.). Cached."""
        if show_id in self._show_cache:
            return self._show_cache[show_id]
        data = self._get_safe(f"/tv/{show_id}")
        if data:
            self._show_cache[show_id] = data
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
        if cache_key in self._season_cache:
            return self._season_cache[cache_key]

        data = self._get_safe(f"/tv/{show_id}/season/{season_num}")
        if not data:
            result = {"titles": {}, "posters": {}, "episodes": {},
                      "season_poster_path": None}
            self._season_cache[cache_key] = result
            return result

        titles = {}
        posters = {}
        episodes = {}
        for ep in data.get("episodes", []):
            num = ep["episode_number"]
            titles[num] = ep.get("name", f"Episode {num}")
            posters[num] = ep.get("still_path")
            # Store rich metadata for the detail panel
            guest_stars = ep.get("guest_stars", [])
            crew = ep.get("crew", [])
            episodes[num] = {
                "name": titles[num],
                "overview": ep.get("overview", ""),
                "air_date": ep.get("air_date", ""),
                "vote_average": ep.get("vote_average", 0),
                "vote_count": ep.get("vote_count", 0),
                "runtime": ep.get("runtime"),
                "still_path": posters[num],
                "directors": [c.get("name", "") for c in crew
                              if c.get("job") == "Director" and c.get("name")],
                "writers": [c.get("name", "") for c in crew
                            if c.get("job") in ("Writer", "Teleplay", "Story")
                            and c.get("name")],
                "guest_stars": [
                    {"name": g.get("name", ""), "character": g.get("character", "")}
                    for g in guest_stars[:5]  # Top 5 guests
                ],
            }
        result = {"titles": titles, "posters": posters, "episodes": episodes,
                  "season_poster_path": data.get("poster_path")}
        self._season_cache[cache_key] = result
        return result

    def get_season_map(self, show_id: int) -> tuple[dict, int]:
        """
        Build a complete map of TMDB's season structure for a show. Cached.

        Returns:
            tmdb_seasons: {season_num: {"titles": {...}, "posters": {...}, "episodes": {...}, "count": int}}
            total_episodes: total across non-special seasons
        """
        if show_id in self._season_map_cache:
            return self._season_map_cache[show_id]

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

        self._season_map_cache[show_id] = (tmdb_seasons, total_episodes)
        return tmdb_seasons, total_episodes

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

        data = self._get_safe("/search/movie", params)
        if not data:
            return []

        results = []
        for movie in data.get("results", []):
            release_date = movie.get("release_date") or ""
            yr = release_date[:4] if len(release_date) >= 4 else ""
            results.append({
                "id": movie["id"],
                "title": movie["title"],
                "year": yr,
                "poster_path": movie.get("poster_path"),
                "overview": movie.get("overview", ""),
            })
        return results

    def get_movie_details(self, movie_id: int) -> dict | None:
        """Fetch full movie details. Cached."""
        if movie_id in self._movie_cache:
            return self._movie_cache[movie_id]
        data = self._get_safe(f"/movie/{movie_id}")
        if data:
            self._movie_cache[movie_id] = data
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
            self._alt_titles_cache[cache_key] = []
            return []

        # Movie endpoint uses "titles", TV uses "results"
        entries = data.get("titles") or data.get("results") or []
        seen: set[str] = set()
        titles: list[tuple[str, str]] = []
        for e in entries:
            t = e.get("title", "")
            cc = e.get("iso_3166_1", "")
            if t and t not in seen:
                seen.add(t)
                titles.append((t, cc))
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
        total = len(queries)
        results: list[list[dict] | None] = [None] * total
        completed = [0]
        lock = threading.Lock()

        def _search(index: int, query: str, year: str | None) -> None:
            res = self.search_with_fallback(query, self.search_movie, year=year)
            if not res and year:
                res = self.search_with_fallback(query, self.search_movie)
            results[index] = res
            with lock:
                completed[0] += 1
                count = completed[0]
            if progress_callback:
                progress_callback(count, total)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = []
            for i, (query, year) in enumerate(queries):
                futures.append(pool.submit(_search, i, query, year))
            for future in as_completed(futures):
                future.result()

        return [r if r is not None else [] for r in results]

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
        total = len(queries)
        results: list[list[dict] | None] = [None] * total
        completed = [0]
        lock = threading.Lock()

        def _search(index: int, query: str, year: str | None) -> None:
            res = self.search_with_fallback(query, self.search_tv, year=year)
            if not res and year:
                res = self.search_with_fallback(query, self.search_tv)
            results[index] = res
            with lock:
                completed[0] += 1
                count = completed[0]
            if progress_callback:
                progress_callback(count, total)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = []
            for i, (query, year) in enumerate(queries):
                futures.append(pool.submit(_search, i, query, year))
            for future in as_completed(futures):
                future.result()

        return [r if r is not None else [] for r in results]

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
        words = query.split()
        # Try full query first, then progressively shorter
        for n in range(len(words), min_words - 1, -1):
            attempt = " ".join(words[:n])
            results = search_fn(attempt, **kwargs)
            if results:
                return results
        return []

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
        cache_key = (image_path, target_width)
        cached = self._image_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            self._rate_limiter.acquire()
            r = self._session.get(IMAGE_BASE_URL + image_path, timeout=10)
            img = Image.open(io.BytesIO(r.content))
            scale = target_width / img.width
            new_h = int(img.height * scale)
            img = img.resize((target_width, new_h), Image.LANCZOS)
            self._image_cache.put(cache_key, img)
            return img
        except (requests.RequestException, OSError, ValueError) as e:
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
        # Try episode still first
        if ep_still:
            img = self.fetch_image(ep_still, target_width)
            if img:
                return img

        # Try season poster (TV only) — read from cache, no extra API call
        if media_type == "tv" and season is not None:
            cache_key = (media_id, season)
            if cache_key not in self._season_cache:
                self.get_season(media_id, season)  # populates cache
            cached = self._season_cache.get(cache_key)
            if cached and cached.get("season_poster_path"):
                img = self.fetch_image(cached["season_poster_path"], target_width)
                if img:
                    return img

        # Fall back to show/movie poster — use cache for both TV and movies
        if media_type == "tv" and media_id in self._show_cache:
            data = self._show_cache[media_id]
        elif media_type == "movie" and media_id in self._movie_cache:
            data = self._movie_cache[media_id]
        else:
            data = self._get_safe(f"/{media_type}/{media_id}")
        if data and data.get("poster_path"):
            return self.fetch_image(data["poster_path"], target_width)

        return None

    def clear_cache(self) -> None:
        """Clear all in-memory caches. Useful when switching shows."""
        self._show_cache.clear()
        self._season_cache.clear()
        self._season_map_cache.clear()
        self._movie_cache.clear()
        self._image_cache.clear()

    def export_cache_snapshot(self) -> dict[str, dict]:
        """Return a serializable snapshot of the in-memory metadata caches."""
        return {
            "show_cache": dict(self._show_cache),
            "season_cache": {
                f"{show_id}:{season_num}": data
                for (show_id, season_num), data in self._season_cache.items()
            },
            "season_map_cache": {
                str(show_id): {
                    "seasons": season_map,
                    "total_episodes": total_episodes,
                }
                for show_id, (season_map, total_episodes) in self._season_map_cache.items()
            },
            "movie_cache": dict(self._movie_cache),
        }

    @staticmethod
    def _normalize_episode_map_keys(mapping: dict | None) -> dict[int, Any]:
        """Convert JSON-restored episode maps back to integer-keyed dictionaries."""
        if not mapping:
            return {}

        normalized: dict[int, Any] = {}
        for key, value in mapping.items():
            try:
                normalized[int(key)] = value
            except (TypeError, ValueError):
                continue
        return normalized

    @classmethod
    def _normalize_season_map_snapshot(cls, season_map: dict | None) -> dict[int, dict[str, Any]]:
        """Convert JSON-restored season maps back to the runtime integer-keyed shape."""
        if not season_map:
            return {}

        normalized: dict[int, dict[str, Any]] = {}
        for season_key, season_data in season_map.items():
            try:
                season_num = int(season_key)
            except (TypeError, ValueError):
                continue

            payload = season_data or {}
            normalized[season_num] = {
                "titles": cls._normalize_episode_map_keys(payload.get("titles", {})),
                "posters": cls._normalize_episode_map_keys(payload.get("posters", {})),
                "episodes": cls._normalize_episode_map_keys(payload.get("episodes", {})),
                "count": int(payload.get("count", 0)),
            }
            if "season_poster_path" in payload:
                normalized[season_num]["season_poster_path"] = payload.get("season_poster_path")

        return normalized

    @classmethod
    def _normalize_season_snapshot(cls, season_data: dict | None) -> dict[str, Any]:
        """Convert a cached season payload restored from JSON back to runtime shape."""
        if not season_data:
            return {
                "titles": {},
                "posters": {},
                "episodes": {},
            }

        normalized = {
            "titles": cls._normalize_episode_map_keys(season_data.get("titles", {})),
            "posters": cls._normalize_episode_map_keys(season_data.get("posters", {})),
            "episodes": cls._normalize_episode_map_keys(season_data.get("episodes", {})),
        }
        if "season_poster_path" in season_data:
            normalized["season_poster_path"] = season_data.get("season_poster_path")
        return normalized

    def import_cache_snapshot(self, snapshot: dict | None, *, clear_existing: bool = False) -> None:
        """Hydrate the in-memory metadata caches from a persisted snapshot."""
        if not snapshot:
            return
        if clear_existing:
            self.clear_cache()

        for show_id, data in snapshot.get("show_cache", {}).items():
            self._show_cache[int(show_id)] = data

        for cache_key, data in snapshot.get("season_cache", {}).items():
            show_id_str, season_num_str = str(cache_key).split(":", 1)
            self._season_cache[(int(show_id_str), int(season_num_str))] = (
                self._normalize_season_snapshot(data)
            )

        for show_id, data in snapshot.get("season_map_cache", {}).items():
            self._season_map_cache[int(show_id)] = (
                self._normalize_season_map_snapshot(data.get("seasons", {})),
                int(data.get("total_episodes", 0)),
            )

        for movie_id, data in snapshot.get("movie_cache", {}).items():
            self._movie_cache[int(movie_id)] = data
