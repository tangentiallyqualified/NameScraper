"""Episode-number extraction helpers."""

from __future__ import annotations

import re
from pathlib import Path

from ._parsing_parts import split_unambiguous_part_marker
from ._parsing_titles import clean_name, clean_title_evidence, strip_release_junk_title
from .constants import RESOLUTION_NUMBERS, YEAR_MAX, YEAR_MIN

_MAX_RANGE_SPAN = 12

# Words that turn an adjacent number into a quantity/volume label rather than an
# episode: "No.6" / "Number 6" / "Vol 2" / "Part 3" — not episode numbers.
_NUMBER_WORD_PREFIXES = frozenset({"no", "number", "vol", "volume", "part", "pt", "chapter", "ch"})


def _is_titleish_bare_number(name: str, digit_start: int, digit_end: int) -> bool:
    """True when a bare number is part of the title, not an episode number.

    Two cases, both observed in real filenames:
      - a digit flanked by a trailing letter ("Se7en") — embedded in a word.
      - a number-word prefix ("Blue Submarine No.6", "Vol 2") — a quantity.
    """
    if digit_end < len(name) and name[digit_end].isalpha():
        return True
    before = name[:digit_start].rstrip()
    if before.endswith("#"):
        return True
    # A release year straight after the number marks a movie-style title
    # ("Apollo 13 1995 1080p ..."): the number belongs to the title.
    if re.match(r"[\s._\-]+(?:19|20)\d{2}(?!\d)", name[digit_end:]):
        return True
    word = re.search(r"([A-Za-z]+)$", before)
    return bool(word and word.group(1).lower() in _NUMBER_WORD_PREFIXES)


def _expand_range(start: int, end: int) -> list[int]:
    """Expand an inclusive episode range, capping absurd spans."""
    if end >= start and (end - start) <= _MAX_RANGE_SPAN:
        return list(range(start, end + 1))
    return [start, end]


_EpisodeParse = tuple[list[int], str | None, bool]


def _parse_sxe(name: str) -> _EpisodeParse | None:
    """S##E## episode chains, with dash-introduced range ends.

    Range-end rules (prevents digit-leading titles from being eaten):
      -E04   or  -E04 (no spaces, E prefix)  -> range
      -04        (no spaces, bare digits)     -> range, but only if NOT followed by a letter
      ' - E04'   (spaced dash, E prefix)      -> range
      ' - 04 ...' (spaced dash, bare digits)  -> NOT a range (title)
    """
    sxe = re.search(r"S(\d+)[\s._-]*((?:E\d+)+)", name, re.IGNORECASE)
    if not sxe:
        return None
    points = [int(num) for num in re.findall(r"E(\d+)", sxe.group(2), re.IGNORECASE)]
    initial_count = len(points)
    rest = name[sxe.end() :]
    segment_re = re.compile(
        r"^(?:-E(\d+)\b|-(\d+)\b(?![a-zA-Z])|\s+-\s+E(\d+)\b)",
        re.IGNORECASE,
    )
    while True:
        seg = segment_re.match(rest)
        if not seg:
            break
        points.append(int(seg.group(1) or seg.group(2) or seg.group(3)))
        rest = rest[seg.end() :]
    # Expand only a lone *dash-introduced* gapped endpoint (e.g.
    # S01E01-E04) as a range. Concatenated explicit episodes
    # (S01E03E05 -> [3, 5]) and 3+ chained points (incl. a multi-ep
    # prefix + bare end like S01E01E02-04 -> [1, 2, 4]) are kept
    # verbatim and validated downstream.
    if initial_count == 1 and len(points) == 2 and points[1] - points[0] > 1:
        episodes = _expand_range(points[0], points[1])
    else:
        episodes = points
    title = strip_release_junk_title(re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None)
    return episodes, title, True


def _parse_nxn(name: str) -> _EpisodeParse | None:
    """N x NN episode chains (mirrors the S##E## range-end rules).

    NxNN range-end rules:
      -1x04  or  -04  (no spaces)             -> range, bare end not followed by letter
      ' - 1x04'       (spaced, NxNN prefix)   -> range
      ' - 04 ...'     (spaced, bare digits)   -> NOT a range (title)
    """
    nxn = re.search(r"\b(\d{1,2})x(\d{2,3})", name, re.IGNORECASE)
    if not nxn:
        return None
    season_prefix = nxn.group(1)
    points = [int(nxn.group(2))]
    rest = name[nxn.end() :]
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
        rest = rest[seg.end() :]
    if len(points) == 2 and points[1] - points[0] > 1:
        episodes = _expand_range(points[0], points[1])
    else:
        episodes = points
    title = strip_release_junk_title(re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None)
    return episodes, title, True


def _parse_air_date(name: str) -> _EpisodeParse | None:
    """Air-date naming (daily/talk shows): YYYY.MM.DD / YYYY-MM-DD.

    The month/day digits must never be read as episode numbers, and the dash
    branch would otherwise eat a dashed date as a range. There is no
    air-date episode matching downstream yet, so the file carries no
    episode evidence. S##E##/NxNN branches run first, so a name with both
    keeps its explicit episode parse.
    """
    date_match = re.search(
        r"(?<!\d)(?:19|20)\d{2}[.\-_ ](?:0?[1-9]|1[0-2])[.\-_ ](?:0?[1-9]|[12]\d|3[01])(?!\d)",
        name,
    )
    if date_match:
        return [], None, False
    return None


def _parse_episode_chain(name: str) -> _EpisodeParse | None:
    """Episode-marker chain WITHOUT a season prefix: E01E02, E01-E02, EP01-EP02, E01 - E02.

    Two or more E-points are required - a lone "Ep 05 - Title" keeps its
    dedicated branch (title extraction). No season evidence, so
    is_season_relative stays False like the other season-less branches.
    """
    echain = re.search(
        r"\b(EP?\d{1,3}(?:(?:\s*-\s*|-)?EP?\d{1,3})+)(?![A-Za-z0-9])",
        name,
        re.IGNORECASE,
    )
    if not echain:
        return None
    points = [int(num) for num in re.findall(r"EP?(\d{1,3})", echain.group(1), re.IGNORECASE)]
    if len(points) == 2 and points[1] - points[0] > 1:
        episodes = _expand_range(points[0], points[1])
    else:
        episodes = points
    rest = name[echain.end() :]
    title = strip_release_junk_title(re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None)
    return episodes, title, False


def _parse_adjacent_range(name: str) -> _EpisodeParse | None:
    """Adjacent NN-NN range at a token boundary ("Show 01-02").

    The negative lookbehind keeps spaced-dash forms ("Anime - 01-03") on the
    dash branch, which owns their title extraction.
    """
    adjacent = re.search(
        r"(?:^|(?<![-\s])[\s._(])(\d{1,3})-(\d{1,3})(?![A-Za-z0-9])",
        name,
    )
    if not adjacent:
        return None
    start_num = int(adjacent.group(1))
    end_num = int(adjacent.group(2))
    if (
        start_num not in RESOLUTION_NUMBERS
        and end_num not in RESOLUTION_NUMBERS
        and not (YEAR_MIN <= start_num <= YEAR_MAX)
        and end_num > start_num
        and end_num - start_num <= 3
    ):
        return list(range(start_num, end_num + 1)), None, False
    return None


def _parse_dash_number(name: str) -> _EpisodeParse | None:
    """Dash-delimited bare numbers ("Anime - 05", "Anime - 05 - Title").

    Resolution values (480/720/1080/2160) are NOT rejected here: the regex
    already refuses a p/i suffix (the "$"/"- title" structure fails), so a
    clean dash-delimited bare number is an episode even when it collides
    with a resolution value - long-running anime reach 720/1080 (P-H2).
    The 4-digit widening covers 1000+ absolute numbering; the year guard
    still rejects 1900-2099. A zero-padded 4-digit number (0083, 0080) is a
    Gundam-style title designation, never a 1000+ absolute episode.
    """
    match = re.search(
        r"-\s*(?!0\d{3}(?!\d))(\d{1,4})(?:v\d+)?['\u2032]?(?:\s*-\s*(?!0\d{3}(?!\d))(\d{1,4})(?:v\d+)?['\u2032]?)?(?:\s*-\s*(.*))?$",
        name,
    )
    if not match:
        return None
    start_num = int(match.group(1))
    end_num = int(match.group(2)) if match.group(2) else None
    if YEAR_MIN <= start_num <= YEAR_MAX:
        return None
    episodes = [start_num]
    if end_num is not None and not (YEAR_MIN <= end_num <= YEAR_MAX):
        if end_num >= start_num and end_num - start_num <= 3:
            episodes = list(range(start_num, end_num + 1))
        else:
            episodes.append(end_num)
    title = strip_release_junk_title(match.group(3).strip()) if match.group(3) else None
    return episodes, title, False


def _parse_leading_number_dot(raw_stem: str) -> _EpisodeParse | None:
    """Leading "NN. Title" numbering; reads the RAW stem on purpose."""
    bare_match = re.match(r"(\d{1,3})\.\s*(.*)", raw_stem)
    if not bare_match:
        return None
    num = int(bare_match.group(1))
    # A bare (unparenthesized) release year in the remainder marks a
    # scene-style movie name whose title leads with a number
    # ("300.2006.1080p..."); "01. Pilot (2005)" keeps its episode.
    scene_year_follows = re.search(r"(?<![\d(])(?:19|20)\d{2}(?![\d)])", bare_match.group(2))
    if (
        num not in RESOLUTION_NUMBERS
        and not (YEAR_MIN <= num <= YEAR_MAX)
        and not scene_year_follows
    ):
        title_text = bare_match.group(2).strip()
        title_text = re.sub(r"\s*\(\d{4}\)\s*$", "", title_text).strip()
        return [num], strip_release_junk_title(title_text or None), False
    return None


def _parse_ep_prefix(name: str) -> _EpisodeParse | None:
    """Explicit Ep/Episode prefix - unambiguous, so no resolution-value
    rejection is needed ("Episode 720" is an episode); the year guard stays."""
    match = re.search(
        r"\b(?:ep?|episode)\s*(\d{1,4})(?!\d)(?:(?:\s*[-._]+\s*|\s+)(.*))?",
        name,
        re.IGNORECASE,
    )
    if not match:
        return None
    num = int(match.group(1))
    if YEAR_MIN <= num <= YEAR_MAX:
        return None
    title = strip_release_junk_title(match.group(2).strip()) if match.group(2) else None
    return [num], title, False


def _parse_bare_number(name: str) -> _EpisodeParse | None:
    """Bare episode numbers with title/quantity/year/codec guards.

    The s/S in the lookbehind rejects season-pack markers ("S01" with no
    E##) that would otherwise read as episode 1.
    """
    match = re.search(
        r"(?<![xXhHsS\d])(?:ep?|episode)?\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?",
        name,
        re.IGNORECASE,
    )
    if not match:
        return None
    num = int(match.group(1))
    if num in RESOLUTION_NUMBERS or (YEAR_MIN <= num <= YEAR_MAX):
        return None
    start = match.start()
    if start > 0:
        prefix = name[max(0, start - 1) : start]
        if prefix.lower() in ("x", "h"):
            return [], None, False
    if _is_titleish_bare_number(name, match.start(1), match.end(1)):
        return [], None, False
    # A NAME-LEADING number with a release year later in the name is
    # a movie-style title ("21 Jump Street 2012 ..."), not an
    # episode; episode-first files ("100 - Title") carry no year.
    if match.start(1) == 0 and re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", name[match.end(1) :]):
        return [], None, False
    title = strip_release_junk_title(match.group(2).strip()) if match.group(2) else None
    return [num], title, False


def _parse_bracketed_absolute(raw_stem: str) -> _EpisodeParse | None:
    """Bracketed absolute episode numbers in fansub names, e.g.
    [DBD-Raws][Wolf's Rain][01][1080P][BDRip][HEVC-10bit][FLACx2].mkv

    Only a bracket whose entire content is a bare episode number (optionally a
    version suffix) qualifies; resolution/quality/version/hash/year brackets
    are excluded because their content is not pure 1-3 digits. Runs last so it
    never overrides an S##E##, NxNN, Ep##, or dash-delimited parse. Requires a
    leading bracket so plain titles like "Apollo 13" are never affected. The
    number is absolute (anime convention) -> is_season_relative is False.
    """
    if not raw_stem.lstrip().startswith("["):
        return None
    for bracket in re.finditer(r"\[(?!0\d{3}(?!\d))(\d{1,4})(?:v\d+)?\]", raw_stem):
        num = int(bracket.group(1))
        if num in RESOLUTION_NUMBERS or YEAR_MIN <= num <= YEAR_MAX:
            continue
        return [num], None, False
    return None


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
    # Only UNAMBIGUOUS part markers ("(2)", "CD1"/"Disc 2", "S01E05b") are
    # stripped before parsing: they are sequence evidence, not episode
    # evidence, and never legitimate title text. "Part n"/"pt n" is left
    # alone here - it is frequently genuine title text ("...Part 2"), and
    # stripping it would corrupt title evidence the confidence engine
    # depends on; it is not needed for episode-number correctness because
    # _parse_bare_number's quantity-word guard already keeps "Part 1" from
    # being read as episode 1 (spec: multi-file-episode-merge).
    raw_stem, _part = split_unambiguous_part_marker(raw_stem)
    name = clean_title_evidence(raw_stem)

    # Branch priority is behavior: each parser either claims the name
    # (returns a final parse, possibly empty) or defers to the next.
    for branch, arg in (
        (_parse_sxe, name),
        (_parse_nxn, name),
        (_parse_air_date, name),
        (_parse_episode_chain, name),
        (_parse_adjacent_range, name),
        (_parse_dash_number, name),
        (_parse_leading_number_dot, raw_stem),
        (_parse_ep_prefix, name),
        (_parse_bare_number, name),
        (_parse_bracketed_absolute, raw_stem),
    ):
        parsed = branch(arg)
        if parsed is not None:
            return parsed

    return [], None, False


def extract_season_number(filename: str) -> int | None:
    """Extract the explicit season number from a season/episode filename pattern."""
    name = clean_name(Path(filename).stem)
    match = re.search(r"S(\d+)[\s._-]*(?:E\d+)+", name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.search(
        r"\b(\d{1,2})x\d{2,3}(?:\s*-\s*(?:\d{1,2}x)?\d{2,3})?(?!\d)", name, re.IGNORECASE
    )
    if match:
        return int(match.group(1))

    # Spelled-out season marker in the FILE name ("Season 1 Episode 2");
    # mirrors the folder-level get_season fallback.
    match = re.search(r"\bseason[\s._\-]*(\d{1,2})\b", name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return None
