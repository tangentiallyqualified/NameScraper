"""Episode-number extraction helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import RESOLUTION_NUMBERS, YEAR_MAX, YEAR_MIN
from ._parsing_titles import clean_name


def extract_episode(filename: str) -> tuple[list[int], str | None, bool]:
    """
    Extract episode number(s) and title text from a filename.

    Returns:
        episode_numbers: list of ints (supports multi-episode files)
        title: str or None
        is_season_relative: True if the number came from an S##E## pattern
            (guaranteed season-relative), False if it came from a bare number
            or dash-delimited pattern (likely absolute for anime).
    """
    raw_stem = Path(filename).stem
    name = clean_name(raw_stem)

    match = re.search(
        r"S(\d+)E(\d+)(?:[E-]?E?(\d+))?\s*[-.]?\s*(.*)",
        name,
        re.IGNORECASE,
    )
    if match:
        episodes = [int(match.group(2))]
        if match.group(3):
            episodes.append(int(match.group(3)))
        title = match.group(4).strip() if match.group(4) else None
        return episodes, title, True

    match = re.search(
        r"-\s*(\d{1,3})['\u2032]?(?:\s*-\s*(\d{1,3})['\u2032]?)?(?:\s*-\s*(.*))?$",
        name,
    )
    if match:
        start_num = int(match.group(1))
        end_num = int(match.group(2)) if match.group(2) else None
        if start_num not in RESOLUTION_NUMBERS and not (YEAR_MIN <= start_num <= YEAR_MAX):
            episodes = [start_num]
            if end_num is not None and end_num not in RESOLUTION_NUMBERS:
                if end_num >= start_num and end_num - start_num <= 3:
                    episodes = list(range(start_num, end_num + 1))
                else:
                    episodes.append(end_num)
            title = match.group(3).strip() if match.group(3) else None
            return episodes, title, False

    bare_match = re.match(r"(\d{1,3})\.\s+(.*)", raw_stem)
    if bare_match:
        num = int(bare_match.group(1))
        if num not in RESOLUTION_NUMBERS and not (YEAR_MIN <= num <= YEAR_MAX):
            title_text = bare_match.group(2).strip()
            title_text = re.sub(r"\s*\(\d{4}\)\s*$", "", title_text).strip()
            return [num], title_text or None, False

    match = re.search(
        r"(?<![xXhH\d])(?:ep?|episode)?\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?",
        name,
        re.IGNORECASE,
    )
    if match:
        num = int(match.group(1))
        if num not in RESOLUTION_NUMBERS and not (YEAR_MIN <= num <= YEAR_MAX):
            start = match.start()
            if start > 0:
                prefix = name[max(0, start - 1):start]
                if prefix.lower() in ("x", "h"):
                    return [], None, False
            title = match.group(2).strip() if match.group(2) else None
            return [num], title, False

    return [], None, False


def extract_season_number(filename: str) -> int | None:
    """Extract the explicit season number from an ``S##E##`` filename pattern."""
    name = clean_name(Path(filename).stem)
    match = re.search(r"S(\d+)E\d+(?:[E-]?E?\d+)?", name, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))
