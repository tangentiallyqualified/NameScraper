"""
Filename parsing and name-building utilities.

All functions are pure (no side effects, no network, no GUI).  They operate
on strings and Paths only, making them easy to test and reuse across both
TV and movie workflows.
"""

import re
from pathlib import Path

from .constants import (
    RELEASE_NOISE, TRAILING_GROUP, UNSAFE_FILENAME_CHARS,
)


# ─── Folder / filename cleaning ──────────────────────────────────────────────

def clean_folder_name(name: str) -> str:
    """
    Extract a human-readable title from a release-group style folder name.

    Example input:
        Dragon.Ball.Super.1080p.Blu-Ray.10-Bit.Dual-Audio.TrueHD.x265-iAHD

    Strategy:
      1. Replace dots/underscores with spaces
      2. Remove bracketed tags [group] and (tags)
      3. Strip trailing release group after the last hyphen
      4. Walk tokens left-to-right; stop at the first release-noise token
      5. Everything before that noise token is the title
      6. If a 4-digit year is found, preserve it in parentheses
    """
    s = name.replace(".", " ").replace("_", " ")
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    s = TRAILING_GROUP.sub("", s)

    tokens = s.split()
    title_tokens = []
    for token in tokens:
        if RELEASE_NOISE.search(f" {token} "):
            break
        title_tokens.append(token)

    title = " ".join(title_tokens).strip()
    if len(title) < 2:
        title = re.sub(r"\s+", " ", s).strip()

    # Preserve a year from the original name as "(YYYY)"
    year_match = re.search(r"(?:^|[.\s(\-])(\d{4})(?=[.\s)\-]|$)", name)
    if year_match:
        year = year_match.group(1)
        yr = int(year)
        if 1950 <= yr <= 2030:
            title = re.sub(r"\s*\(?\b" + year + r"\b\)?\s*", " ", title).strip()
            title = f"{title} ({year})"

    return re.sub(r"\s+", " ", title).strip()


def clean_name(name: str) -> str:
    """
    Normalize a filename for pattern matching.

    Strips square-bracketed tags (fansub groups, quality tags) but preserves
    parenthesized years like (2023).  Dots and underscores become spaces.
    """
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\((?!\d{4}\))[^)]*\)", "", name)
    name = name.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", name).strip()


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are illegal in filenames on
    Windows and potentially problematic on other operating systems.
    """
    name = name.replace(":", " -")
    name = UNSAFE_FILENAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    return name


# ─── Year extraction ─────────────────────────────────────────────────────────

def extract_year(text: str) -> str | None:
    """
    Extract a plausible release year (1920-2030) from a string.

    Returns the year as a string, or None if not found.
    """
    m = re.search(r"(?:^|[.\s(\-])(\d{4})(?=[.\s)\-]|$)", text)
    if m:
        yr = int(m.group(1))
        if 1920 <= yr <= 2030:
            return m.group(1)
    return None


# ─── TV episode detection (for filtering in movie mode) ──────────────────────

# Strong indicators that a file is a TV episode, not a movie.
_TV_EPISODE_PATTERNS = [
    # S01E01, S1E5, s01e01e02, etc.
    re.compile(r"S\d{1,2}E\d{1,3}", re.IGNORECASE),
    # "1x05", "01x05" (common in some naming schemes)
    re.compile(r"\b\d{1,2}x\d{2,3}\b", re.IGNORECASE),
    # Explicit "Episode 5", "Ep05", "Ep.5", "E05" as standalone
    re.compile(r"\b(?:Episode|Ep)[\s._-]*\d{1,3}\b", re.IGNORECASE),
]

# Anime/fansub pattern: [Group] Title - ## (tags)
# The combination of a [bracket group] tag AND a dash-delimited episode number
# is an extremely strong TV signal — movies essentially never use this format.
_FANSUB_EPISODE_PATTERN = re.compile(
    r"^\[.+?\]"              # starts with [FansubGroup]
    r".+"                    # title text
    r"\s+-\s+"               # dash separator with spaces
    r"\d{1,3}"               # 1-3 digit episode number
    r"(?:\s|\.|\(|$)",       # followed by space, dot, paren, or end
)

# Parent folder names that strongly suggest TV content
_TV_FOLDER_PATTERNS = re.compile(
    r"(?:^|[\s._\-])(?:Season|S\d{1,2}|Staffel|Saison|Temporada|Stagione)"
    r"[\s._\-]*\d*",
    re.IGNORECASE,
)


def looks_like_tv_episode(filepath: Path) -> bool:
    """
    Quick heuristic check for whether a file is likely a TV episode.

    Checks the filename for S##E## patterns, episode markers, anime/fansub
    naming conventions, and the parent folder name for season indicators.
    Uses only strong signals to avoid false-positiving on movies with
    numbers in the title.
    """
    name = filepath.name

    for pattern in _TV_EPISODE_PATTERNS:
        if pattern.search(name):
            return True

    # Anime/fansub pattern: [Group] Title - 02 (tags)
    if _FANSUB_EPISODE_PATTERN.search(name):
        return True

    # Check parent folder — "Season 01", "S02", "Staffel 3", etc.
    parent = filepath.parent.name
    if _TV_FOLDER_PATTERNS.search(parent):
        return True

    return False


# ─── Episode extraction (TV-specific) ────────────────────────────────────────

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
    name = clean_name(Path(filename).stem)

    # Pattern 1 (BEST): S##E## with optional multi-episode
    m = re.search(
        r"S(\d+)E(\d+)(?:[E-]?E?(\d+))?\s*[-.]?\s*(.*)",
        name, re.IGNORECASE,
    )
    if m:
        eps = [int(m.group(2))]
        if m.group(3):
            eps.append(int(m.group(3)))
        title = m.group(4).strip() if m.group(4) else None
        return eps, title, True

    # Pattern 2: Dash-delimited " - 05 - Title" (common in organized releases)
    m = re.search(r"-\s*(\d{1,3})\s*-\s*(.*)", name)
    if m:
        return [int(m.group(1))], m.group(2).strip(), False

    # Pattern 3: Episode number preceded by space/separator
    m = re.search(
        r"(?<!\d)(?:ep?|episode)?\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?",
        name, re.IGNORECASE,
    )
    if m:
        num = int(m.group(1))
        if num not in (480, 720, 1080, 2160) and not (1900 <= num <= 2099):
            title = m.group(2).strip() if m.group(2) else None
            return [num], title, False

    return [], None, False


# ─── Season detection ────────────────────────────────────────────────────────

_SPECIALS_PATTERN = re.compile(
    r"^(?:"
    r"specials?|extras?|bonus|behind[\s._\-]*the[\s._\-]*scenes"
    r"|deleted[\s._\-]*scenes|featurettes?|shorts?"
    r"|OVAs?|OADs?|ONAs?|movies?"
    r"|special[\s._\-]*features?"
    r"|Season[\s._\-]*0+(?:[\s._\-]|$)"
    r")$",
    re.IGNORECASE,
)

_SPECIALS_SUFFIX = re.compile(
    r"[\s._\-](?:specials?|extras?|bonus|OVAs?|OADs?|ONAs?|"
    r"special[\s._\-]*features?|featurettes?|shorts?)$",
    re.IGNORECASE,
)


def get_season(folder: Path) -> int | None:
    """
    Extract the season number from a folder name.

    Recognizes many common formats:
      - "Season 02", "S02", "Staffel 3", "Saison 3", etc.
      - Specials/extras folders → Season 0
      - Bare number folders: "02", "2"

    Returns the season number as an int, or None if not found.
    """
    name = folder.name

    # Specials folders → 0
    if _SPECIALS_PATTERN.match(name.strip()):
        return 0
    if _SPECIALS_SUFFIX.search(name):
        return 0

    # "Season ##" anywhere
    m = re.search(r"season\s*(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # "S##" as a standalone token
    m = re.search(r"(?:^|[\s._\-])S(\d{1,2})(?:[\s._\-]|$)", name)
    if m:
        return int(m.group(1))

    # International variants
    m = re.search(
        r"(?:staffel|saison|temporada|stagione)\s*(\d+)",
        name, re.IGNORECASE,
    )
    if m:
        return int(m.group(1))

    # Bare number folder
    m = re.fullmatch(r"(\d{1,2})", name.strip())
    if m:
        return int(m.group(1))

    return None


# ─── Name builders ───────────────────────────────────────────────────────────

def build_tv_name(
    show: str,
    year: str,
    season: int,
    episodes: list[int],
    titles: list[str] | str,
    ext: str,
) -> str:
    """
    Build a Plex-compatible TV episode filename.

    Examples:
        Show (2004) - S01E01 - Pilot.mkv
        Show (2004) - S01E01-E02 - Title 1-Title 2.mkv
    """
    year_part = f" ({year})" if year else ""

    if len(episodes) == 1:
        ep_part = f"E{episodes[0]:02d}"
    else:
        ep_part = "-".join(f"E{ep:02d}" for ep in episodes)

    if isinstance(titles, str):
        title_part = titles
    elif len(titles) == 1:
        title_part = titles[0]
    else:
        unique = list(dict.fromkeys(titles))
        title_part = "-".join(unique)

    raw = f"{show}{year_part} - S{season:02d}{ep_part} - {title_part}{ext}"
    return sanitize_filename(raw)


def build_movie_name(title: str, year: str, ext: str) -> str:
    """
    Build a Plex-compatible movie filename.

    Example:
        The Matrix (1999).mkv
    """
    year_part = f" ({year})" if year else ""
    raw = f"{title}{year_part}{ext}"
    return sanitize_filename(raw)
