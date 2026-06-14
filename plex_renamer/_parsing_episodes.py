"""Episode-number extraction helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import RESOLUTION_NUMBERS, YEAR_MAX, YEAR_MIN
from ._parsing_titles import clean_name, clean_title_evidence

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
    name = clean_title_evidence(raw_stem)

    # Range-end rules (prevents digit-leading titles from being eaten):
    #   -E04   or  -E04 (no spaces, E prefix)  → range
    #   -04        (no spaces, bare digits)     → range, but only if NOT followed by a letter
    #   ' - E04'   (spaced dash, E prefix)      → range
    #   ' - 04 …'  (spaced dash, bare digits)   → NOT a range (title)
    sxe = re.search(r"S(\d+)((?:E\d+)+)", name, re.IGNORECASE)
    if sxe:
        points = [int(num) for num in re.findall(r"E(\d+)", sxe.group(2), re.IGNORECASE)]
        initial_count = len(points)
        rest = name[sxe.end():]
        segment_re = re.compile(
            r"^(?:-E(\d+)\b|-(\d+)\b(?![a-zA-Z])|\s+-\s+E(\d+)\b)",
            re.IGNORECASE,
        )
        while True:
            seg = segment_re.match(rest)
            if not seg:
                break
            points.append(int(seg.group(1) or seg.group(2) or seg.group(3)))
            rest = rest[seg.end():]
        # Expand only a lone *dash-introduced* gapped endpoint (e.g.
        # S01E01-E04) as a range. Concatenated explicit episodes
        # (S01E03E05 -> [3, 5]) and 3+ chained points (incl. a multi-ep
        # prefix + bare end like S01E01E02-04 -> [1, 2, 4]) are kept
        # verbatim and validated downstream.
        if initial_count == 1 and len(points) == 2 and points[1] - points[0] > 1:
            episodes = _expand_range(points[0], points[1])
        else:
            episodes = points
        title = re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None
        return episodes, title, True

    # NxNN range-end rules (mirrors S##E## logic):
    #   -1x04  or  -04  (no spaces)             → range, bare end not followed by letter
    #   ' - 1x04'       (spaced, N×NN prefix)   → range
    #   ' - 04 …'       (spaced, bare digits)   → NOT a range (title)
    nxn = re.search(r"\b(\d{1,2})x(\d{2,3})", name, re.IGNORECASE)
    if nxn:
        season_prefix = nxn.group(1)
        points = [int(nxn.group(2))]
        rest = name[nxn.end():]
        segment_re = re.compile(
            rf"^(?:-(?:{season_prefix}x)?(\d{{2,3}})(?![a-zA-Z])"
            rf"|\s+-\s+{season_prefix}x(\d{{2,3}})(?![a-zA-Z]))",
            re.IGNORECASE,
        )
        while True:
            seg = segment_re.match(rest)
            if not seg:
                break
            points.append(int(seg.group(1) or seg.group(2)))
            rest = rest[seg.end():]
        if len(points) == 2 and points[1] - points[0] > 1:
            episodes = _expand_range(points[0], points[1])
        else:
            episodes = points
        title = re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None
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
