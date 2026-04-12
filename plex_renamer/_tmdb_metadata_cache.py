"""Persistent metadata cache helpers for the TMDB client."""

from __future__ import annotations

from typing import Any

_TV_DETAILS_NAMESPACE = "tmdb.tv_details"
_SEASON_NAMESPACE = "tmdb.season"
_MOVIE_DETAILS_NAMESPACE = "tmdb.movie_details"


class _TMDBMetadataCacheStore:
    """Coordinate persisted metadata caching and JSON snapshot normalization."""

    def __init__(self, *, cache_service: Any | None = None, refresh_policy: Any | None = None):
        self._cache_service = cache_service
        self._refresh_policy = refresh_policy
        self._show_cache: dict[int, dict] = {}
        self._season_cache: dict[tuple[int, int], dict] = {}
        self._season_map_cache: dict[int, tuple[dict, int]] = {}
        self._movie_cache: dict[int, dict] = {}

    @property
    def show_cache(self) -> dict[int, dict]:
        return self._show_cache

    @property
    def season_cache(self) -> dict[tuple[int, int], dict]:
        return self._season_cache

    @property
    def season_map_cache(self) -> dict[int, tuple[dict, int]]:
        return self._season_map_cache

    @property
    def movie_cache(self) -> dict[int, dict]:
        return self._movie_cache

    def get_tv_details(self, show_id: int) -> dict | None:
        return self._persistent_get(_TV_DETAILS_NAMESPACE, str(show_id))

    def put_tv_details(self, show_id: int, value: dict, *, show_status: str | None = None) -> None:
        self._persistent_put(
            _TV_DETAILS_NAMESPACE,
            str(show_id),
            value,
            media_type="tv",
            show_status=show_status,
        )

    def get_movie_details(self, movie_id: int) -> dict | None:
        return self._persistent_get(_MOVIE_DETAILS_NAMESPACE, str(movie_id))

    def put_movie_details(self, movie_id: int, value: dict) -> None:
        self._persistent_put(
            _MOVIE_DETAILS_NAMESPACE,
            str(movie_id),
            value,
            media_type="movie",
        )

    def get_season(self, show_id: int, season_num: int) -> dict[str, Any] | None:
        persistent_key = self._season_cache_key(show_id, season_num)
        persisted = self._persistent_get(_SEASON_NAMESPACE, persistent_key)
        if persisted is None:
            return None
        return self.normalize_season_snapshot(persisted)

    def put_season(self, show_id: int, season_num: int, value: dict[str, Any]) -> None:
        self._persistent_put(
            _SEASON_NAMESPACE,
            self._season_cache_key(show_id, season_num),
            value,
            media_type="tv",
        )

    def get_cached_poster_path(self, media_id: int, media_type: str = "tv") -> str | None:
        if media_type == "tv":
            data = self._show_cache.get(media_id)
        else:
            data = self._movie_cache.get(media_id)
        if not data:
            return None
        poster_path = data.get("poster_path")
        return str(poster_path) if poster_path else None

    def clear_runtime_caches(self) -> None:
        self._show_cache.clear()
        self._season_cache.clear()
        self._season_map_cache.clear()
        self._movie_cache.clear()

    def export_snapshot(self) -> dict[str, dict]:
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

    def import_snapshot(self, snapshot: dict | None, *, clear_existing: bool = False) -> None:
        if not snapshot:
            return
        if clear_existing:
            self.clear_runtime_caches()

        for show_id, data in snapshot.get("show_cache", {}).items():
            self._show_cache[int(show_id)] = data

        for cache_key, data in snapshot.get("season_cache", {}).items():
            show_id_str, season_num_str = str(cache_key).split(":", 1)
            self._season_cache[(int(show_id_str), int(season_num_str))] = (
                self.normalize_season_snapshot(data)
            )

        for show_id, data in snapshot.get("season_map_cache", {}).items():
            self._season_map_cache[int(show_id)] = (
                self.normalize_season_map_snapshot(data.get("seasons", {})),
                int(data.get("total_episodes", 0)),
            )

        for movie_id, data in snapshot.get("movie_cache", {}).items():
            self._movie_cache[int(movie_id)] = data

    @staticmethod
    def _season_cache_key(show_id: int, season_num: int) -> str:
        return f"{show_id}::{season_num}"

    def _persistent_get(self, namespace: str, key: str) -> Any | None:
        if self._cache_service is None:
            return None
        lookup = self._cache_service.get(namespace, key, allow_stale=False)
        if not lookup.is_hit:
            return None
        return lookup.value

    def _persistent_put(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        media_type: str,
        show_status: str | None = None,
    ) -> None:
        if self._cache_service is None or self._refresh_policy is None:
            return
        expires_at = self._refresh_policy.build_expiry(
            refreshed_at=None,
            media_type=media_type,
            show_status=show_status,
        )
        self._cache_service.put(namespace, key, value, expires_at=expires_at)

    @staticmethod
    def normalize_episode_map_keys(mapping: dict | None) -> dict[int, Any]:
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
    def normalize_season_map_snapshot(cls, season_map: dict | None) -> dict[int, dict[str, Any]]:
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
                "titles": cls.normalize_episode_map_keys(payload.get("titles", {})),
                "posters": cls.normalize_episode_map_keys(payload.get("posters", {})),
                "episodes": cls.normalize_episode_map_keys(payload.get("episodes", {})),
                "count": int(payload.get("count", 0)),
            }
            if "season_poster_path" in payload:
                normalized[season_num]["season_poster_path"] = payload.get("season_poster_path")

        return normalized

    @classmethod
    def normalize_season_snapshot(cls, season_data: dict | None) -> dict[str, Any]:
        if not season_data:
            return {
                "titles": {},
                "posters": {},
                "episodes": {},
            }

        normalized = {
            "titles": cls.normalize_episode_map_keys(season_data.get("titles", {})),
            "posters": cls.normalize_episode_map_keys(season_data.get("posters", {})),
            "episodes": cls.normalize_episode_map_keys(season_data.get("episodes", {})),
        }
        if "season_poster_path" in season_data:
            normalized["season_poster_path"] = season_data.get("season_poster_path")
        return normalized