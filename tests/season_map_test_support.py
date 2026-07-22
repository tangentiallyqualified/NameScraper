"""Typed transport doubles for strict provider season-map tests."""

# pyright: strict

from __future__ import annotations

from collections.abc import Mapping

from plex_renamer._tmdb_transport import TMDBNetworkError

ResponseKey = str | tuple[str, object]


class FailingTransport:
    def get_json(
        self,
        path: str,
        params: dict[str, object] | None = None,
    ) -> object:
        raise TMDBNetworkError("offline")


class MapTransport:
    def __init__(self, responses: Mapping[ResponseKey, object]) -> None:
        self.responses = dict(responses)
        self.calls: list[str] = []

    def get_json(
        self,
        path: str,
        params: dict[str, object] | None = None,
    ) -> object:
        self.calls.append(path)
        page = (params or {}).get("page")
        page_key = (path, page)
        if page_key in self.responses:
            return self.responses[page_key]
        return self.responses[path]

    def get_json_safe(
        self,
        path: str,
        params: dict[str, object] | None = None,
    ) -> object | None:
        try:
            return self.get_json(path, params)
        except KeyError:
            return None
