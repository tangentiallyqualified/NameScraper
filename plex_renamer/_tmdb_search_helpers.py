"""Search and alternate-title helpers for the TMDB client."""

from __future__ import annotations

from collections.abc import Callable


def extract_alternative_titles(data: dict | None) -> list[tuple[str, str]]:
    if not data:
        return []

    entries = data.get("titles") or data.get("results") or []
    seen: set[str] = set()
    titles: list[tuple[str, str]] = []
    for entry in entries:
        title = entry.get("title", "")
        country_code = entry.get("iso_3166_1", "")
        if title and title not in seen:
            seen.add(title)
            titles.append((title, country_code))
    return titles


def search_with_fallback(
    query: str,
    search_fn: Callable[..., list[dict]],
    min_words: int = 1,
    **kwargs,
) -> list[dict]:
    words = query.split()
    for word_count in range(len(words), min_words - 1, -1):
        attempt = " ".join(words[:word_count])
        results = search_fn(attempt, **kwargs)
        if results:
            return results
    return []