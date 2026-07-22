"""TheTVDB v4 API client implementing the MetadataProvider protocol.

Every public method returns the TMDB-shaped payloads documented on
``plex_renamer.providers.MetadataProvider`` — raw TVDB JSON never leaks
past this module. TVDB artwork references are absolute URLs carried in
the same poster_path/still_path fields; image helpers detect "http".
"""

from __future__ import annotations

import base64
import io
import logging
from collections.abc import Callable
from typing import Any, cast

from PIL import Image

from ._provider_errors import SeasonMapUnavailableError
from ._tmdb_batch_search import (
    resolve_tv_batch_query as _resolve_tv_batch_query,  # type: ignore
    run_batch_search as _run_batch_search,  # type: ignore
)
from ._tmdb_image_cache import _TMDBImageCacheStore  # pyright: ignore[reportPrivateUsage]
from ._tmdb_search_helpers import search_with_fallback as _run_search_with_fallback  # type: ignore
from ._tmdb_transport import TMDBError
from ._tvdb_payloads import (
    fetch_all_episodes_strict,
    fetch_series_details_strict,
    optional_series_details,
    validated_record_list,
)
from ._tvdb_transport import TVDBTransport

log = logging.getLogger(__name__)

resolve_tv_batch_query: Callable[..., list[dict[str, Any]]] = _resolve_tv_batch_query  # type: ignore
run_batch_search: Callable[..., list[list[dict[str, Any]]]] = _run_batch_search  # type: ignore
run_search_with_fallback: Callable[..., list[dict[str, Any]]] = _run_search_with_fallback  # type: ignore

# Artwork type ids per TVDB /artwork/types.
_SERIES_BACKDROP_TYPE = 3
_SEASON_POSTER_TYPE = 7
_SERIES_CLEARLOGO_TYPE = 23

# TVDB status names -> TMDB status vocabulary (show_details_from_tmdb
# treats "Planned"/"In Production" as unaired).
_STATUS_MAP = {"Continuing": "Returning Series", "Upcoming": "Planned", "Ended": "Ended"}

_LANG3_TO_ISO639_1 = {
    "eng": "en",
    "spa": "es",
    "fra": "fr",
    "deu": "de",
    "jpn": "ja",
    "kor": "ko",
    "zho": "zh",
    "por": "pt",
    "ita": "it",
    "rus": "ru",
}

_DETAILS_NAMESPACE = "tvdb.details"
_EPISODES_NAMESPACE = "tvdb.episodes"

ARTWORK_BASE_URL = "https://artworks.thetvdb.com"
_EXPORT_IMAGE_NAMESPACE = "tvdb.export_image"


def _iso639_1(lang3: str | None) -> str | None:
    return _LANG3_TO_ISO639_1.get(lang3 or "")


def normalize_episode_meta(ep: dict[str, Any]) -> dict[str, Any]:
    """TVDB episode record -> TMDB-shaped episode meta (protocol contract)."""
    return {
        "name": ep.get("name") or "",
        "overview": ep.get("overview") or "",
        "air_date": ep.get("aired") or "",
        "runtime": ep.get("runtime"),
        "vote_average": 0,
        "vote_count": 0,
        "still_path": ep.get("image") or None,
        "directors": [],
        "writers": [],
        "guest_stars": [],
    }


def normalize_series_details(
    payload: dict[str, Any], episodes: list[dict[str, Any]]
) -> dict[str, Any]:
    """TVDB /series/{id}/extended + full episode list -> TMDB-shaped details."""
    by_season: dict[int, int] = {}
    for ep in episodes:
        sn = ep.get("seasonNumber")
        if isinstance(sn, int):
            by_season[sn] = by_season.get(sn, 0) + 1
    seasons: list[dict[str, Any]] = [
        {
            "season_number": sn,
            "episode_count": count,
            "name": "Specials" if sn == 0 else f"Season {sn}",
        }
        for sn, count in sorted(by_season.items())
    ]

    artworks: list[dict[str, Any]] = payload.get("artworks") or []
    payload_seasons: list[dict[str, Any]] = payload.get("seasons") or []
    season_ids: dict[Any, Any] = {}
    for s in payload_seasons:
        s_type: dict[str, Any] = s.get("type") or {}
        if s_type.get("type") == "official":
            season_ids[s.get("id")] = s.get("number")
    season_posters: dict[int, str] = {}
    backdrop: str | None = None
    logos: list[dict[str, Any]] = []
    for art in artworks:
        image = art.get("image")
        if not image:
            continue
        art_type = art.get("type")
        if art_type == _SERIES_BACKDROP_TYPE and backdrop is None:
            backdrop = image
        elif art_type == _SERIES_CLEARLOGO_TYPE:
            logos.append({"file_path": image, "iso_639_1": _iso639_1(art.get("language"))})
        elif art_type == _SEASON_POSTER_TYPE:
            sn = season_ids.get(art.get("seasonId"))
            if isinstance(sn, int):
                season_posters.setdefault(sn, image)

    status_obj: dict[str, Any] = payload.get("status") or {}
    status_name = str(status_obj.get("name") or "")
    payload_characters: list[dict[str, Any]] = payload.get("characters") or []
    cast = [
        {
            "name": ch.get("personName") or "",
            "character": ch.get("name") or "",
            "order": ch.get("sort") if ch.get("sort") is not None else idx,
        }
        for idx, ch in enumerate(payload_characters)
    ]
    payload_genres: list[dict[str, Any]] = payload.get("genres") or []
    payload_companies: list[dict[str, Any]] = payload.get("companies") or []
    payload_aliases: list[dict[str, Any]] = payload.get("aliases") or []
    networks: list[dict[str, Any]] = []
    for c in payload_companies:
        company_type: dict[str, Any] = c.get("companyType") or {}
        if company_type.get("companyTypeId") == 1:
            networks.append({"name": c.get("name") or ""})
    return {
        "id": payload.get("id"),
        "name": payload.get("name") or "",
        "overview": payload.get("overview") or "",
        "first_air_date": payload.get("firstAired") or "",
        "status": _STATUS_MAP.get(status_name, status_name),
        "genres": [{"name": g.get("name") or ""} for g in payload_genres],
        "networks": networks,
        "episode_run_time": ([payload["averageRuntime"]] if payload.get("averageRuntime") else []),
        "vote_average": payload.get("score") or 0,
        "vote_count": 0,
        "poster_path": payload.get("image") or None,
        "backdrop_path": backdrop,
        "images": {"logos": logos},
        "credits": {"cast": cast},
        "seasons": seasons,
        "number_of_seasons": sum(1 for s in seasons if s["season_number"] > 0),
        "number_of_episodes": sum(s["episode_count"] for s in seasons if s["season_number"] > 0),
        "_aliases": [a.get("name") for a in payload_aliases if a.get("name")],
        "_season_posters": season_posters,
    }


class TVDBClient:
    provider_name = "tvdb"

    def __init__(
        self,
        api_key: str,
        language: str = "en-US",
        cache_service: Any | None = None,
        refresh_policy: Any | None = None,
        transport: TVDBTransport | None = None,
    ) -> None:
        self.api_key = api_key
        # TVDB v4 responses are currently fetched in the default translation;
        # `language` is kept for protocol parity and image-cache keys but is
        # not yet sent to TVDB endpoints — wiring translations is deferred.
        self.language = language
        self._cache_service = cache_service
        self._refresh_policy = refresh_policy
        self._transport = transport or TVDBTransport(api_key)
        self._details_cache: dict[int, dict[str, Any]] = {}
        self._episodes_cache: dict[int, list[dict[str, Any]]] = {}
        self._season_map_cache: dict[int, tuple[dict[int, dict[str, Any]], int]] = {}
        self._alt_titles_cache: dict[tuple[int, str], list[tuple[str, str]]] = {}
        self._image_cache_store = _TMDBImageCacheStore(
            image_cache_size=200, cache_service=cache_service
        )

    # ─── Search ───────────────────────────────────────────────────────

    def search_tv(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query, "type": "series"}
        if year:
            params["year"] = year
        # Deliberately single-page: TVDB's /search results are already
        # ranked and callers only need the top matches, unlike
        # `_fetch_all_episodes` below, which must walk every page to build
        # a complete season map.
        data = self._transport.get_json_safe("/search", params) or {}
        results: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = data.get("data") or []
        for entry in entries:
            try:
                show_id = int(entry.get("tvdb_id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "id": show_id,
                    "name": entry.get("name") or "",
                    "year": str(entry.get("year") or ""),
                    "poster_path": entry.get("image_url") or None,
                    "overview": entry.get("overview") or "",
                }
            )
        return results

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        def _search_query(query: str, year: str | None) -> list[dict[str, Any]]:
            return resolve_tv_batch_query(
                query,
                year,
                search_with_fallback=self.search_with_fallback,
                search_fn=self.search_tv,
            )

        return run_batch_search(
            queries,
            search_query=_search_query,
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable[..., Any],
        min_words: int = 1,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return run_search_with_fallback(query, search_fn, min_words=min_words, **kwargs)

    # ─── Details and seasons ──────────────────────────────────────────

    def _cache_get(self, namespace: str, key: str) -> Any | None:
        if self._cache_service is None:
            return None
        lookup = self._cache_service.get(namespace, key)
        return lookup.value if lookup.is_hit else None

    def _cache_put(self, namespace: str, key: str, value: Any) -> None:
        if self._cache_service is not None:
            self._cache_service.put(namespace, key, value)

    def get_tv_details(self, show_id: int) -> dict[str, Any] | None:
        cached = self._details_cache.get(show_id)
        if cached is not None:
            return cached
        persisted = self._cache_get(_DETAILS_NAMESPACE, str(show_id))
        if persisted is not None:
            self._details_cache[show_id] = persisted
            return persisted
        raw = cast(object, self._transport.get_json_safe(f"/series/{show_id}/extended"))
        payload = optional_series_details(raw)
        if payload is None:
            return None
        episodes = validated_record_list(cast(object, self._fetch_all_episodes(show_id)))
        if episodes is None:
            return None
        details = normalize_series_details(payload, episodes)
        self._details_cache[show_id] = details
        self._cache_put(_DETAILS_NAMESPACE, str(show_id), details)
        return details

    def _fetch_all_episodes(self, show_id: int) -> list[dict[str, Any]]:
        cached = self._episodes_cache.get(show_id)
        if cached is not None:
            return cached
        persisted = self._cache_get(_EPISODES_NAMESPACE, str(show_id))
        if persisted is not None:
            self._episodes_cache[show_id] = persisted
            return persisted
        episodes: list[dict[str, Any]] = []
        page = 0
        while True:
            raw = self._transport.get_json_safe(
                f"/series/{show_id}/episodes/default", {"page": page}
            )
            if not raw:
                break
            data: dict[str, Any] = raw.get("data") or {}
            page_episodes: list[dict[str, Any]] = data.get("episodes") or []
            episodes.extend(page_episodes)
            links: dict[str, Any] = raw.get("links") or {}
            if not links.get("next"):
                break
            page += 1
        self._episodes_cache[show_id] = episodes
        self._cache_put(_EPISODES_NAMESPACE, str(show_id), episodes)
        return episodes

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        cached = self._season_map_cache.get(show_id)
        if cached is not None:
            return cached
        raw_details = fetch_series_details_strict(self._transport, show_id)
        episodes = fetch_all_episodes_strict(self._transport, show_id)
        details = normalize_series_details(raw_details, episodes)
        season_posters: dict[int, str] = details.get("_season_posters") or {}
        seasons: dict[int, dict[str, Any]] = {}
        for ep in episodes:
            sn, num = ep.get("seasonNumber"), ep.get("number")
            if not isinstance(sn, int) or not isinstance(num, int):
                continue
            payload = seasons.setdefault(
                sn,
                {
                    "name": "Specials" if sn == 0 else f"Season {sn}",
                    "titles": {},
                    "posters": {},
                    "episodes": {},
                    "season_poster_path": season_posters.get(sn),
                },
            )
            payload["titles"][num] = ep.get("name") or ""
            payload["posters"][num] = ep.get("image") or None
            payload["episodes"][num] = normalize_episode_meta(ep)
        total = 0
        for sn, payload in seasons.items():
            payload["count"] = max(payload["titles"].keys()) if payload["titles"] else 0
            if sn > 0:
                total += payload["count"]
        result = (seasons, total)
        self._season_map_cache[show_id] = result
        return result

    def get_season(self, show_id: int, season_num: int) -> dict[str, Any]:
        try:
            seasons, _ = self.get_season_map(show_id)
        except SeasonMapUnavailableError:
            log.debug("TVDB season map unavailable for %s", show_id, exc_info=True)
            return {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}
        payload = seasons.get(season_num)
        if payload is None:
            return {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}
        return payload

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        """TVDB aliases carry no country info — empty country means no
        country boost during rescoring, which matching handles fine."""
        if media_type != "tv":
            return []
        cache_key = (media_id, media_type)
        if cache_key in self._alt_titles_cache:
            return self._alt_titles_cache[cache_key]
        details: dict[str, Any] = self.get_tv_details(media_id) or {}
        aliases: list[str] = details.get("_aliases") or []
        titles: list[tuple[str, str]] = [(alias, "") for alias in aliases]
        self._alt_titles_cache[cache_key] = titles
        return titles

    def clear_cache(self) -> None:
        self._details_cache.clear()
        self._episodes_cache.clear()
        self._season_map_cache.clear()
        self._alt_titles_cache.clear()
        self._image_cache_store.clear_runtime_caches()

    # ─── Images ───────────────────────────────────────────────────────

    @staticmethod
    def _absolute_url(image_path: str) -> str:
        path = str(image_path).strip()
        return path if path.startswith("http") else ARTWORK_BASE_URL + path

    def fetch_image(self, image_path: str | None, target_width: int = 300) -> Image.Image | None:
        if not image_path:
            return None
        cached = self._image_cache_store.get_image(image_path, target_width)
        if cached is not None:
            return cached
        source = self._image_cache_store.get_source_image(image_path)
        if source is None:
            try:
                payload = self._transport.fetch_bytes(self._absolute_url(image_path))
                source = Image.open(io.BytesIO(payload))
                source.load()
                self._image_cache_store.store_source_image(image_path, source)
            except (TMDBError, OSError, ValueError) as e:
                log.debug("Failed to fetch TVDB image %s: %s", image_path, e)
                return None
        try:
            scale = target_width / source.width
            img = source.resize(  # pyright: ignore[reportUnknownMemberType]
                (target_width, int(source.height * scale)), Image.Resampling.LANCZOS
            )
            self._image_cache_store.store_image(image_path, target_width, img)
            return img
        except (OSError, ValueError) as e:
            log.debug("Failed to scale TVDB image %s: %s", image_path, e)
            return None

    def fetch_poster(
        self,
        media_id: int,
        media_type: str = "tv",
        season: int | None = None,
        ep_still: str | None = None,
        target_width: int = 300,
    ) -> Image.Image | None:
        if ep_still:
            img = self.fetch_image(ep_still, target_width)
            if img is not None:
                return img
        if media_type == "tv" and season is not None:
            season_poster = self.get_season(media_id, season).get("season_poster_path")
            if season_poster:
                img = self.fetch_image(season_poster, target_width)
                if img is not None:
                    return img
        poster = self.get_cached_poster_path(media_id, media_type)
        if poster is None and media_type == "tv":
            poster = (self.get_tv_details(media_id) or {}).get("poster_path")
        return self.fetch_image(poster, target_width) if poster else None

    def fetch_image_bytes(self, image_path: str | None, size: str = "original") -> bytes | None:
        if not image_path:
            return None
        url = self._absolute_url(image_path)
        cache_key = f"{size}::{url}"
        if self._cache_service is not None:
            lookup = self._cache_service.get(_EXPORT_IMAGE_NAMESPACE, cache_key)
            if lookup.is_hit and lookup.value:
                encoded = lookup.value.get("bytes_base64")
                if encoded:
                    try:
                        return base64.b64decode(encoded)
                    except (ValueError, TypeError):
                        self._cache_service.invalidate(_EXPORT_IMAGE_NAMESPACE, cache_key)
        try:
            payload = self._transport.fetch_bytes(url)
        except (TMDBError, OSError) as e:
            log.debug("Failed to fetch TVDB export image %s: %s", url, e)
            return None
        if self._cache_service is not None and payload:
            self._cache_service.put(
                _EXPORT_IMAGE_NAMESPACE,
                cache_key,
                {"bytes_base64": base64.b64encode(payload).decode("ascii")},
                metadata={"kind": "tvdb_export_image", "image_path": url, "size": size},
            )
        return payload or None

    def get_cached_poster_path(self, media_id: int, media_type: str = "tv") -> str | None:
        if media_type != "tv":
            return None
        details = self._details_cache.get(media_id)
        if details is None:
            details = self._cache_get(_DETAILS_NAMESPACE, str(media_id))
        return (details or {}).get("poster_path")
