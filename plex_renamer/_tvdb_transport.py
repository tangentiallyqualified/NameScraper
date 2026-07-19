"""HTTP transport for TheTVDB v4 API: bearer auth, JSON GETs, image bytes.

Raises the shared TMDBError family so existing callers' error handling
covers TVDB without new channels.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, cast

import requests

from ._tmdb_transport import TMDBError, TMDBNetworkError

API_BASE = "https://api4.thetvdb.com/v4"

log = logging.getLogger(__name__)


class TVDBTransport:
    """Logs in lazily on first request; re-logs-in once on 401 (token expiry)."""

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str = API_BASE,
        timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_base = api_base
        self._timeout = timeout
        self._session = session or requests.Session()
        self._token: str | None = None
        self._lock = threading.Lock()

    def _login(self) -> str:
        try:
            resp = self._session.post(
                f"{self._api_base}/login",
                json={"apikey": self._api_key},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise TMDBNetworkError(f"TVDB login failed: {e}") from e
        if resp.status_code != 200:
            raise TMDBError(f"TVDB login failed: HTTP {resp.status_code}")
        data = cast(dict[str, Any], resp.json().get("data") or {})
        token = data.get("token")
        if not token:
            raise TMDBError("TVDB login response had no token")
        return str(token)

    def _ensure_token(self) -> str:
        with self._lock:
            if self._token is None:
                self._token = self._login()
            return self._token

    def _drop_token(self) -> None:
        with self._lock:
            self._token = None

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """GET *path* → parsed JSON. None on 404. Raises TMDBError family."""
        for attempt in (1, 2):
            token = self._ensure_token()
            try:
                resp = self._session.get(
                    f"{self._api_base}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=self._timeout,
                )
            except requests.RequestException as e:
                raise TMDBNetworkError(f"TVDB request failed: {e}") from e
            if resp.status_code == 401 and attempt == 1:
                self._drop_token()
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                raise TMDBError(f"TVDB HTTP {resp.status_code} for {path}")
            return resp.json()
        return None

    def get_json_safe(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        try:
            return self.get_json(path, params)
        except TMDBError as e:
            log.warning("TVDB request %s failed: %s", path, e)
            return None

    def fetch_bytes(self, url: str, *, timeout: int = 10) -> bytes:
        """Raw bytes from an absolute artwork URL (no auth required)."""
        try:
            resp = self._session.get(url, timeout=timeout)
        except requests.RequestException as e:
            raise TMDBNetworkError(f"TVDB image fetch failed: {e}") from e
        if resp.status_code != 200:
            raise TMDBNetworkError(f"TVDB image HTTP {resp.status_code}")
        return resp.content
