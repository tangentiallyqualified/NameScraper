"""Image and poster cache helpers for the TMDB client."""

from __future__ import annotations

import base64
import io
import threading
from collections import OrderedDict
from typing import Any

from PIL import Image

_POSTER_CACHE_NAMESPACE = "tmdb.poster_image"
_SOURCE_IMAGE_CACHE_NAMESPACE = "tmdb.source_image"


class _LRUImageCache:
    """Bounded LRU cache for PIL images."""

    def __init__(self, max_size: int = 200):
        self._max_size = max_size
        self._cache: OrderedDict[tuple[str, int], Image.Image] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, int]) -> Image.Image | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, key: tuple[str, int], value: Image.Image) -> None:
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


class _TMDBImageCacheStore:
    """Own in-memory and persisted image caches for TMDB client images."""

    def __init__(self, *, image_cache_size: int = 200, cache_service: Any | None = None):
        self._cache_service = cache_service
        self._resized_image_cache = _LRUImageCache(max_size=image_cache_size)
        self._poster_cache: dict[tuple[str, int, int | None, str | None, int], Image.Image] = {}
        self._source_image_cache: dict[str, Image.Image] = {}

    @staticmethod
    def _poster_cache_key(
        *,
        media_id: int,
        media_type: str,
        season: int | None,
        ep_still: str | None,
        target_width: int,
    ) -> tuple[str, int, int | None, str | None, int]:
        return (media_type, media_id, season, ep_still, target_width)

    @staticmethod
    def _persistent_poster_cache_key(
        *,
        media_id: int,
        media_type: str,
        season: int | None,
        ep_still: str | None,
        target_width: int,
    ) -> str:
        variant = "default"
        if season is not None:
            variant = f"season:{season}"
        if ep_still:
            variant = f"still:{ep_still}"
        return "::".join(
            str(part).strip().replace("\\", "/")
            for part in (media_type, media_id, variant, target_width)
        )

    @staticmethod
    def _serialize_image(image: Image.Image) -> dict[str, Any]:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {"png_base64": base64.b64encode(buffer.getvalue()).decode("ascii")}

    @staticmethod
    def _deserialize_image(payload: dict[str, Any] | None) -> Image.Image | None:
        if not payload:
            return None
        encoded = payload.get("png_base64")
        if not encoded:
            return None
        try:
            raw = base64.b64decode(encoded)
            image = Image.open(io.BytesIO(raw))
            image.load()
            return image
        except (ValueError, OSError):
            return None

    @staticmethod
    def _persistent_source_image_key(image_path: str) -> str:
        return str(image_path).strip().replace("\\", "/")

    def get_image(self, image_path: str, target_width: int) -> Image.Image | None:
        return self._resized_image_cache.get((image_path, target_width))

    def store_image(self, image_path: str, target_width: int, image: Image.Image) -> None:
        self._resized_image_cache.put((image_path, target_width), image)

    def get_poster(
        self,
        *,
        media_id: int,
        media_type: str,
        season: int | None,
        ep_still: str | None,
        target_width: int,
    ) -> Image.Image | None:
        key = self._poster_cache_key(
            media_id=media_id,
            media_type=media_type,
            season=season,
            ep_still=ep_still,
            target_width=target_width,
        )
        cached = self._poster_cache.get(key)
        if cached is not None:
            return cached
        if self._cache_service is None:
            return None

        persistent_key = self._persistent_poster_cache_key(
            media_id=media_id,
            media_type=media_type,
            season=season,
            ep_still=ep_still,
            target_width=target_width,
        )
        lookup = self._cache_service.get(_POSTER_CACHE_NAMESPACE, persistent_key)
        if not lookup.is_hit or not lookup.value:
            return None

        image = self._deserialize_image(lookup.value)
        if image is None:
            self._cache_service.invalidate(_POSTER_CACHE_NAMESPACE, persistent_key)
            return None

        self._poster_cache[key] = image
        return image

    def store_poster(
        self,
        *,
        media_id: int,
        media_type: str,
        season: int | None,
        ep_still: str | None,
        target_width: int,
        image: Image.Image,
    ) -> None:
        key = self._poster_cache_key(
            media_id=media_id,
            media_type=media_type,
            season=season,
            ep_still=ep_still,
            target_width=target_width,
        )
        self._poster_cache[key] = image
        if self._cache_service is None:
            return

        persistent_key = self._persistent_poster_cache_key(
            media_id=media_id,
            media_type=media_type,
            season=season,
            ep_still=ep_still,
            target_width=target_width,
        )
        self._cache_service.put(
            _POSTER_CACHE_NAMESPACE,
            persistent_key,
            self._serialize_image(image),
            metadata={
                "kind": "tmdb_poster_image",
                "media_type": media_type,
                "media_id": media_id,
                "season": season,
                "ep_still": ep_still,
                "target_width": target_width,
            },
        )

    def get_source_image(self, image_path: str) -> Image.Image | None:
        cached = self._source_image_cache.get(image_path)
        if cached is not None:
            return cached
        if self._cache_service is None:
            return None

        persistent_key = self._persistent_source_image_key(image_path)
        lookup = self._cache_service.get(_SOURCE_IMAGE_CACHE_NAMESPACE, persistent_key)
        if not lookup.is_hit or not lookup.value:
            return None

        image = self._deserialize_image(lookup.value)
        if image is None:
            self._cache_service.invalidate(_SOURCE_IMAGE_CACHE_NAMESPACE, persistent_key)
            return None

        self._source_image_cache[image_path] = image
        return image

    def store_source_image(self, image_path: str, image: Image.Image) -> None:
        self._source_image_cache[image_path] = image
        if self._cache_service is None:
            return

        persistent_key = self._persistent_source_image_key(image_path)
        self._cache_service.put(
            _SOURCE_IMAGE_CACHE_NAMESPACE,
            persistent_key,
            self._serialize_image(image),
            metadata={
                "kind": "tmdb_source_image",
                "image_path": image_path,
            },
        )

    def clear_runtime_caches(self) -> None:
        self._resized_image_cache.clear()
        self._poster_cache.clear()