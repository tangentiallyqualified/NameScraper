"""Specials and extras matching helpers for TVScanner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import build_tv_name, extract_episode, normalize_for_specials
from .models import PreviewItem


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


def match_special(
    *,
    file_path: Path,
    episode_numbers: list[int],
    raw_title: str | None,
    titles: dict,
    tmdb_title_lookup: dict,
    specials_target: Path,
    media_fields: dict,
    show_info: dict,
    root: Path,
    from_extras_folder: bool = False,
) -> PreviewItem:
    """Try to match a specials/extras file to a TMDB Season 0 episode."""
    matched_ep = None
    matched_title = None

    # Title match first — specials numbering varies across sources, so the
    # episode title embedded in the filename is a more reliable signal than
    # the S00E## number when both are present.
    if raw_title:
        matched_ep, matched_title = fuzzy_match_special(raw_title, tmdb_title_lookup)

    if not matched_ep and not from_extras_folder and episode_numbers:
        for episode_num in episode_numbers:
            if episode_num in titles:
                matched_ep = episode_num
                matched_title = titles[episode_num]
                break

    if not matched_ep:
        stem = file_path.stem
        cleaned_stem = re.sub(
            r"^(?:Season|S)\s*\d+\s*[-._]\s*",
            "",
            stem,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned_stem:
            matched_ep, matched_title = fuzzy_match_special(
                cleaned_stem,
                tmdb_title_lookup,
            )

    if matched_ep is not None:
        new_name = build_tv_name(
            show_info["name"],
            show_info["year"],
            0,
            [matched_ep],
            [matched_title],
            file_path.suffix,
        )
        return PreviewItem(
            original=file_path,
            new_name=new_name,
            target_dir=specials_target,
            season=0,
            episodes=[matched_ep],
            status="OK",
            **media_fields,
        )

    if from_extras_folder:
        unmatched_target = root / "Unmatched" / file_path.parent.name
        return PreviewItem(
            original=file_path,
            new_name=file_path.name,
            target_dir=unmatched_target,
            season=0,
            episodes=episode_numbers,
            status="UNMATCHED: no TMDB special found - moving to Unmatched",
            **media_fields,
        )

    return PreviewItem(
        original=file_path,
        new_name=file_path.name,
        target_dir=specials_target,
        season=0,
        episodes=episode_numbers,
        status="OK",
        **media_fields,
    )


def scan_nested_extras(
    *,
    extras_dir: Path,
    titles: dict,
    tmdb_title_lookup: dict,
    specials_target: Path,
    media_fields: dict,
    show_info: dict,
    root: Path,
) -> list[PreviewItem]:
    """Scan a nested extras folder and match its files against Season 0."""
    items: list[PreviewItem] = []
    for file_path in sorted(extras_dir.iterdir()):
        if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        episode_numbers, raw_title, _is_season_relative = extract_episode(file_path.name)
        items.append(
            match_special(
                file_path=file_path,
                episode_numbers=episode_numbers,
                raw_title=raw_title,
                titles=titles,
                tmdb_title_lookup=tmdb_title_lookup,
                specials_target=specials_target,
                media_fields=media_fields,
                show_info=show_info,
                root=root,
                from_extras_folder=True,
            )
        )
    return items