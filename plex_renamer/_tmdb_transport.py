"""Transport helpers for TMDB client networking and retry behavior."""

from __future__ import annotations

import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter


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


class _TokenBucket:
    """Simple token-bucket rate limiter."""

    def __init__(self, rate: float = 35.0):
        self._rate = rate
        self._tokens = rate
        self._max_tokens = rate
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
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
            time.sleep(0.02)


class TMDBTransport:
    """Own the HTTP session, token bucket, and retry policy for TMDB requests."""

    def __init__(
        self,
        *,
        api_key: str,
        language: str,
        api_base: str,
        rate_limit: float = 35.0,
        max_retries: int = 2,
        api_host: str = "https://api.themoviedb.org",
        image_host: str = "https://image.tmdb.org",
        pool_connections: int = 16,
        pool_maxsize: int = 32,
        logger: logging.Logger | None = None,
    ) -> None:
        self.api_key = api_key
        self.language = language
        self._api_base = api_base
        self._max_retries = max_retries
        self._log = logger or logging.getLogger(__name__)
        self._session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
        )
        self._session.mount(api_host, adapter)
        self._session.mount(image_host, adapter)
        self._rate_limiter = _TokenBucket(rate_limit)

    @property
    def session(self) -> requests.Session:
        return self._session

    @property
    def rate_limiter(self) -> _TokenBucket:
        return self._rate_limiter

    def get_json(self, path: str, params: dict | None = None) -> dict | None:
        url = f"{self._api_base}{path}"
        all_params = {"api_key": self.api_key, "language": self.language}
        if params:
            all_params.update(params)

        last_exc: Exception | None = None

        for attempt in range(1 + self._max_retries):
            self._rate_limiter.acquire()

            try:
                response = self._session.get(url, params=all_params, timeout=10)
            except requests.RequestException as exc:
                last_exc = TMDBNetworkError(str(exc))
                if attempt < self._max_retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise last_exc from exc

            if response.ok:
                return response.json()

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 1.5))
                self._log.warning("TMDB rate limit hit, waiting %.1fs", retry_after)
                last_exc = TMDBRateLimitError(f"Rate limited (attempt {attempt + 1})")
                time.sleep(retry_after)
                continue

            if response.status_code >= 500:
                last_exc = TMDBNetworkError(
                    f"Server error {response.status_code} (attempt {attempt + 1})"
                )
                if attempt < self._max_retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise last_exc

            raise TMDBAPIError(response.status_code, response.text[:200])

        if last_exc:
            raise last_exc
        return None

    def get_json_safe(self, path: str, params: dict | None = None) -> dict | None:
        try:
            return self.get_json(path, params)
        except TMDBError as exc:
            self._log.warning("TMDB request failed for %s: %s", path, exc)
            return None

    def fetch_bytes(self, url: str, *, timeout: int = 10) -> bytes:
        self._rate_limiter.acquire()
        try:
            response = self._session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            raise TMDBNetworkError(str(exc)) from exc
        return response.content