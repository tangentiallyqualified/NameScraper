"""
TMDB (The Movie Database) API client.

Handles searching, metadata fetching, and image retrieval for both
TV series and movies.  No GUI dependency — returns plain data structures.

Performance features:
  - requests.Session for HTTP keep-alive (connection pooling)
  - In-memory caching for season data and show details to eliminate
    redundant API calls within a session
  - Parallel batch searching for movies via ThreadPoolExecutor
"""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from PIL import Image


IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
API_BASE = "https://api.themoviedb.org/3"


class TMDBClient:
    """
    TMDB client with connection pooling and response caching.

    Uses a requests.Session for HTTP keep-alive, which dramatically
    reduces latency when making many sequential API calls (avoids
    TCP+TLS handshake per request).

    Caches show details and season data in memory so repeated calls
    (e.g. scan → mismatch check → consolidated scan) don't hit the
    network again.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session = requests.Session()
        # In-memory caches keyed by (show_id,) or (show_id, season_num)
        self._show_cache: dict[int, dict] = {}
        self._season_cache: dict[tuple[int, int], dict] = {}
        self._season_map_cache: dict[int, tuple[dict, int]] = {}
        self._movie_cache: dict[int, dict] = {}
        # Image cache keyed by (image_path, target_width)
        self._image_cache: dict[tuple[str, int], Image.Image] = {}

    # ─── Helpers ──────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Make a GET request to the TMDB API. Returns JSON or None."""
        url = f"{API_BASE}{path}"
        all_params = {"api_key": self.api_key}
        if params:
            all_params.update(params)
        try:
            r = self._session.get(url, params=all_params, timeout=10)
            if r.ok:
                return r.json()
        except requests.RequestException:
            pass
        return None

    # ─── TV Series ────────────────────────────────────────────────────

    def search_tv(self, query: str) -> list[dict]:
        """
        Search TMDB for TV series matching *query*.

        Returns a list of dicts with keys:
            id, name, year, poster_path, overview
        """
        data = self._get("/search/tv", {"query": query})
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
        data = self._get(f"/tv/{show_id}")
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

        data = self._get(f"/tv/{show_id}/season/{season_num}")
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
                "directors": [c["name"] for c in crew
                              if c.get("job") == "Director"],
                "writers": [c["name"] for c in crew
                            if c.get("job") in ("Writer", "Teleplay", "Story")],
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

        data = self._get("/search/movie", params)
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
        data = self._get(f"/movie/{movie_id}")
        if data:
            self._movie_cache[movie_id] = data
        return data

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
            max_workers: Thread pool size (TMDB allows ~40 req/s).
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
        Download and scale an image from TMDB. Cached by (path, width).

        Args:
            image_path: The TMDB image path (e.g. "/abc123.jpg").
                If None, returns None.
            target_width: Scale image to this pixel width.

        Returns a PIL Image or None on failure.
        """
        if not image_path:
            return None
        cache_key = (image_path, target_width)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]
        try:
            r = self._session.get(IMAGE_BASE_URL + image_path, timeout=10)
            img = Image.open(io.BytesIO(r.content))
            scale = target_width / img.width
            new_h = int(img.height * scale)
            img = img.resize((target_width, new_h), Image.LANCZOS)
            self._image_cache[cache_key] = img
            return img
        except Exception:
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

        # Fall back to show/movie poster — use cache for TV
        if media_type == "tv" and media_id in self._show_cache:
            data = self._show_cache[media_id]
        else:
            data = self._get(f"/{media_type}/{media_id}")
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
