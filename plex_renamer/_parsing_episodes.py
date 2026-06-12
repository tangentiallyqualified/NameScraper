"""Episode-number extraction helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import RESOLUTION_NUMBERS, YEAR_MAX, YEAR_MIN
from ._parsing_titles import clean_name

_MAX_RANGE_SPAN = 12


def _expand_range(start: int, end: int) -> list[int]:
    """Expand an inclusive episode range, capping absurd spans."""
    if end >= start and (end - start) <= _MAX_RANGE_SPAN:
        return list(range(start, end + 1))
    return [start, end]


def extract_episode(filename: str) -> tuple[list[int], str | None, bool]:
    """
    Extract episode number(s) and title text from a filename.

    Returns:
        episode_numbers: list of ints (supports multi-episode files)
        title: str or None
        is_season_relative: True if the number came from an S##E## or
            N x NN pattern (guaranteed season-relative), False if it came
            from a bare number or dash-delimited pattern (likely absolute
            for anime).
    """
    raw_stem = Path(filename).stem
    name = clean_name(raw_stem)

    # Range-end rules (prevents digit-leading titles from being eaten):
    #   -E04   or  -E04 (no spaces, E prefix)  → range
    #   -04        (no spaces, bare digits)     → range, but only if NOT followed by a letter
    #   ' - E04'   (spaced dash, E prefix)      → range
    #   ' - 04 …'  (spaced dash, bare digits)   → NOT a range (title)
    match = re.search(
        r"S(\d+)((?:E\d+)+)"
        r"(?:-E(\d+)\b|-(\d+)\b(?![a-zA-Z])|\s+-\s+E(\d+)\b)?"
        r"\s*[-.]?\s*(.*)",
        name,
        re.IGNORECASE,
    )
    if match:
        episodes = [int(num) for num in re.findall(r"E(\d+)", match.group(2), re.IGNORECASE)]
        range_end_str = match.group(3) or match.group(4) or match.group(5)
        if range_end_str:
            episodes = _expand_range(episodes[0], int(range_end_str))
        title = match.group(6).strip() if match.group(6) else None
        return episodes, title, True

    # NxNN range-end rules (mirrors S##E## logic):
    #   -1x04  or  -04  (no spaces)             → range, bare end not followed by letter
    #   ' - 1x04'       (spaced, N×NN prefix)   → range
    #   ' - 04 …'       (spaced, bare digits)   → NOT a range (title)
    match = re.search(
        r"\b(\d{1,2})x(\d{2,3})"
        r"(?:-(?:\1x)?(\d{2,3})(?![a-zA-Z])|\s+-\s+\1x(\d{2,3})(?![a-zA-Z]))?"
        r"(?!\d)\s*[-.]?\s*(.*)",
        name,
        re.IGNORECASE,
    )
    if match:
        start_num = int(match.group(2))
        range_end_str = match.group(3) or match.group(4)
        if range_end_str:
            episodes = _expand_range(start_num, int(range_end_str))
        else:
            episodes = [start_num]
        title = match.group(5).strip() if match.group(5) else None
        return episodes, title, True

    match = re.search(
        r"-\s*(\d{1,3})(?:v\d+)?['\u2032]?(?:\s*-\s*(\d{1,3})(?:v\d+)?['\u2032]?)?(?:\s*-\s*(.*))?$",
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
        r"\b(?:ep?|episode)\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?",
        name,
        re.IGNORECASE,
    )
    if match:
        num = int(match.group(1))
        if num not in RESOLUTION_NUMBERS and not (YEAR_MIN <= num <= YEAR_MAX):
            title = match.group(2).strip() if match.group(2) else None
            return [num], title, False

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
    """Extract the explicit season number from a season/episode filename pattern."""
    name = clean_name(Path(filename).stem)
    match = re.search(r"S(\d+)(?:E\d+)+", name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.search(r"\b(\d{1,2})x\d{2,3}(?:\s*-\s*(?:\d{1,2}x)?\d{2,3})?(?!\d)", name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return None
