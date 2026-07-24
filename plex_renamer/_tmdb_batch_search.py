"""Batch search orchestration helpers for the TMDB client."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .metadata_types import MediaInfo


def resolve_movie_batch_query(
    query: str,
    year: str | None,
    *,
    search_with_fallback: Callable[..., list[MediaInfo]],
    search_fn: Callable[..., list[MediaInfo]],
) -> list[MediaInfo]:
    results = search_with_fallback(query, search_fn, year=year)
    if not results and year:
        return search_with_fallback(query, search_fn)
    return results


def resolve_tv_batch_query(
    query: str,
    year: str | None,
    *,
    search_with_fallback: Callable[..., list[MediaInfo]],
    search_fn: Callable[..., list[MediaInfo]],
) -> list[MediaInfo]:
    results = search_with_fallback(query, search_fn, year=year)
    if not results and year:
        return search_with_fallback(query, search_fn)
    if results and year:
        broader = search_with_fallback(query, search_fn)
        seen_ids = {result["id"] for result in results}
        for result in broader:
            if result["id"] not in seen_ids:
                results.append(result)
    return results


def run_batch_search(
    queries: list[tuple[str, str | None]],
    *,
    search_query: Callable[[str, str | None], list[MediaInfo]],
    max_workers: int = 8,
    progress_callback: Callable[..., object] | None = None,
) -> list[list[MediaInfo]]:
    total = len(queries)
    results: list[list[MediaInfo] | None] = [None] * total
    completed = [0]
    lock = threading.Lock()

    def _search(index: int, query: str, year: str | None) -> None:
        results[index] = search_query(query, year)
        with lock:
            completed[0] += 1
            count = completed[0]
        if progress_callback:
            try:
                progress_callback(count, total, query)
            except TypeError:
                progress_callback(count, total)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for index, (query, year) in enumerate(queries):
            futures.append(pool.submit(_search, index, query, year))
        for future in as_completed(futures):
            future.result()

    return [result if result is not None else [] for result in results]
