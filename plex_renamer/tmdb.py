"""
TMDB (The Movie Database) API client.

Handles searching, metadata fetching, and image retrieval for both
TV series and movies.  No GUI dependency — returns plain data structures.
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from PIL import Image


IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
API_BASE = "https://api.themoviedb.org/3"


class TMDBClient:
    """
    TMDB client with connection pooling.

    Uses a requests.Session for HTTP keep-alive, which dramatically
    reduces latency when making many sequential API calls (avoids
    TCP+TLS handshake per request).
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session = requests.Session()

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
        """Fetch full show details (seasons list, etc.)."""
        return self._get(f"/tv/{show_id}")

    def get_season(self, show_id: int, season_num: int) -> dict:
        """
        Fetch episode list for a season.

        Returns:
            {
                "titles": {ep_num: title, ...},
                "posters": {ep_num: still_path_or_None, ...},
            }
        """
        data = self._get(f"/tv/{show_id}/season/{season_num}")
        if not data:
            return {"titles": {}, "posters": {}}

        titles = {}
        posters = {}
        for ep in data.get("episodes", []):
            num = ep["episode_number"]
            titles[num] = ep.get("name", f"Episode {num}")
            posters[num] = ep.get("still_path")
        return {"titles": titles, "posters": posters}

    def get_season_map(self, show_id: int) -> tuple[dict, int]:
        """
        Build a complete map of TMDB's season structure for a show.

        Returns:
            tmdb_seasons: {season_num: {"titles": {...}, "posters": {...}, "count": int}}
            total_episodes: total across non-special seasons
        """
        show_data = self._get(f"/tv/{show_id}")
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
                "count": count,
            }
            if sn > 0:
                total_episodes += count

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
        """Fetch full movie details."""
        return self._get(f"/movie/{movie_id}")

    def search_movies_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: callable | None = None,
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
            the input queries.  Each entry is the same format as
            search_movie() returns.
        """
        total = len(queries)
        results: list[list[dict] | None] = [None] * total
        completed = [0]  # mutable counter for the callback

        def _search(index: int, query: str, year: str | None) -> None:
            res = self.search_movie(query, year)
            if not res and year:
                # Retry without year filter
                res = self.search_movie(query)
            results[index] = res
            completed[0] += 1
            if progress_callback:
                progress_callback(completed[0], total)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = []
            for i, (query, year) in enumerate(queries):
                futures.append(pool.submit(_search, i, query, year))
            # Wait for all to complete
            for future in as_completed(futures):
                # Re-raise any exceptions from worker threads
                future.result()

        return [r if r is not None else [] for r in results]

    # ─── Images ───────────────────────────────────────────────────────

    def fetch_image(
        self,
        image_path: str | None,
        target_width: int = 300,
    ) -> Image.Image | None:
        """
        Download and scale an image from TMDB.

        Args:
            image_path: The TMDB image path (e.g. "/abc123.jpg").
                If None, returns None.
            target_width: Scale image to this pixel width.

        Returns a PIL Image or None on failure.
        """
        if not image_path:
            return None
        try:
            r = self._session.get(IMAGE_BASE_URL + image_path, timeout=10)
            img = Image.open(io.BytesIO(r.content))
            scale = target_width / img.width
            new_h = int(img.height * scale)
            img = img.resize((target_width, new_h), Image.LANCZOS)
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
        """
        # Try episode still first
        if ep_still:
            img = self.fetch_image(ep_still, target_width)
            if img:
                return img

        # Try season poster (TV only)
        if media_type == "tv" and season is not None:
            data = self._get(f"/tv/{media_id}/season/{season}")
            if data and data.get("poster_path"):
                img = self.fetch_image(data["poster_path"], target_width)
                if img:
                    return img

        # Fall back to show/movie poster
        endpoint = f"/{media_type}/{media_id}"
        data = self._get(endpoint)
        if data and data.get("poster_path"):
            return self.fetch_image(data["poster_path"], target_width)

        return None
