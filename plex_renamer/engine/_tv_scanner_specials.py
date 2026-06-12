"""Specials and extras matching helpers for TVScanner."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..parsing import normalize_for_specials


@dataclass(slots=True)
class SpecialsContext:
    titles: dict
    posters: dict
    episodes: dict
    title_lookup: dict


def load_specials_context(
    *,
    tmdb,
    show_info: dict,
    tmdb_seasons: dict,
    store_tmdb_data,
) -> SpecialsContext:
    if 0 in tmdb_seasons:
        s0_titles = tmdb_seasons[0]["titles"]
        s0_posters = tmdb_seasons[0]["posters"]
        s0_episodes = tmdb_seasons[0].get("episodes", {})
    else:
        s0_data = tmdb.get_season(show_info["id"], 0)
        s0_titles = s0_data["titles"]
        s0_posters = s0_data["posters"]
        s0_episodes = s0_data.get("episodes", {})

    if s0_titles:
        store_tmdb_data(0, s0_titles, s0_posters, s0_episodes)

    return SpecialsContext(
        titles=s0_titles,
        posters=s0_posters,
        episodes=s0_episodes,
        title_lookup=build_title_lookup(s0_titles),
    )


def build_title_lookup(titles: dict) -> dict:
    """Build a normalized-title → (episode_num, original_title) lookup."""
    return {
        normalize_for_specials(title): (episode_num, title)
        for episode_num, title in titles.items()
    }


_PART_NUMBER_RE = re.compile(r"\d{1,2}")


def _strip_part_number(normalized: str) -> tuple[str, str]:
    """Strip an embedded 1-2 digit number from a normalized string.

    Returns (base_without_digits, digit_string).  Used to compare titles
    whose part numbers appear in different positions, e.g.
    "inauguration2overthere" vs "inaugurationoverthere2".
    """
    m = _PART_NUMBER_RE.search(normalized)
    if m:
        return normalized[: m.start()] + normalized[m.end() :], m.group()
    return normalized, ""


def fuzzy_match_special(
    text: str,
    tmdb_title_lookup: dict,
) -> tuple[int | None, str | None]:
    """Try to fuzzy-match a text string against TMDB season titles."""
    normalized = normalize_for_specials(text)
    if not normalized:
        return None, None

    # 1. Exact normalized match.
    if normalized in tmdb_title_lookup:
        episode_num, title = tmdb_title_lookup[normalized]
        return episode_num, title

    # 2. Unique substring match.
    matches = [
        (episode_num, original_title)
        for norm_key, (episode_num, original_title) in tmdb_title_lookup.items()
        if norm_key and (normalized in norm_key or norm_key in normalized)
    ]
    if len(matches) == 1:
        return matches[0]

    # 3. Part-number-aware fallback: strip embedded digits from both sides,
    #    match on the base title, then disambiguate by part number.
    input_base, input_part = _strip_part_number(normalized)
    if input_base:
        base_matches = [
            (ep, title, key_part)
            for norm_key, (ep, title) in tmdb_title_lookup.items()
            if norm_key
            for key_base, key_part in [_strip_part_number(norm_key)]
            if key_base == input_base
        ]
        if len(base_matches) == 1:
            return base_matches[0][0], base_matches[0][1]
        if input_part and len(base_matches) > 1:
            by_part = [
                (ep, title) for ep, title, kp in base_matches if kp == input_part
            ]
            if len(by_part) == 1:
                return by_part[0]

    return None, None


