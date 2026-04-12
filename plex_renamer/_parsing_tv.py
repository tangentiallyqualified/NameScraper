"""TV/movie classification and title inference helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import TRAILING_GROUP, VIDEO_EXTENSIONS
from ._parsing_titles import clean_folder_name, extract_year


_TV_EPISODE_PATTERNS = [
    re.compile(r"S\d{1,2}E\d{1,3}", re.IGNORECASE),
    re.compile(r"\b\d{1,2}x\d{2,3}\b", re.IGNORECASE),
    re.compile(r"\b(?:Episode|Ep)[\s._-]*\d{1,3}\b", re.IGNORECASE),
    re.compile(r"^\d{1,3}\.\s+\w"),
]

_FANSUB_EPISODE_PATTERN = re.compile(
    r"^\[.+?\]"
    r".+"
    r"\s+-\s+"
    r"\d{1,3}"
    r"['\u2032]?"
    r"(?:\s*-\s*\d{1,3}['\u2032]?)*"
    r"(?:\s|\.|\(|\[|$)",
)

_TV_FOLDER_PATTERNS = re.compile(
    r"(?:^|[\s._\-])(?:Season|S\d{1,2}|Staffel|Saison|Temporada|Stagione)"
    r"[\s._\-]*\d*",
    re.IGNORECASE,
)

EXTRAS_FOLDER_PATTERN = re.compile(
    r"^(?:"
    r"specials?|extras?|bonus|featurettes?"
    r"|behind[\s._\-]*the[\s._\-]*scenes"
    r"|deleted[\s._\-]*scenes|shorts?"
    r"|special[\s._\-]*features?"
    r"|OVAs?|OADs?|ONAs?"
    r")$",
    re.IGNORECASE,
)

_SAMPLE_FILE_RE = re.compile(r"(?i)(?:^|[\s.\-_])sample(?:[\s.\-_]|$)")

_FILENAME_SEASON_PATTERN = re.compile(
    r"(?:^|[\s._\-])(?:Season|Staffel|Saison|Temporada|Stagione)"
    r"[\s._\-]*\d+",
    re.IGNORECASE,
)

_TV_COMPANION_VIDEO_PATTERN = re.compile(
    r"(?:^|[\s._\-\[(])(?:NCOP|NCED)(?:\d+)?(?:v\d+)?(?=$|[\s._\-\])])"
    r"|\b(?:creditless|non[\s._\-]*credit(?:ed|less)?|clean)[\s._\-]*"
    r"(?:opening|ending|op|ed)\b",
    re.IGNORECASE,
)

_TV_TITLE_PREFIX_PATTERNS = (
    re.compile(
        r"^(?P<title>.+?)[ ._\-]+S\d{1,2}E\d{1,3}(?:[E\-]?E?\d{1,3})?(?=[ ._\-]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<title>.+?)[ ._\-]+\d{1,2}x\d{2,3}(?=[ ._\-]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:\[[^\]]+\]\s*)?(?P<title>.+?)\s+-\s+\d{1,3}['\u2032]?(?:\s*-\s*\d{1,3}['\u2032]?)*(?=\s|\.|\(|\[|$)",
        re.IGNORECASE,
    ),
)


def is_extras_folder(name: str) -> bool:
    """Check if a folder name indicates supplemental/extras content."""
    return bool(EXTRAS_FOLDER_PATTERN.match(name.strip()))


def is_sample_file(filepath: Path) -> bool:
    """Return True if a file is a release sample clip, not the main film."""
    return bool(_SAMPLE_FILE_RE.search(filepath.stem))


def looks_like_tv_episode(filepath: Path) -> bool:
    """
    Quick heuristic check for whether a file is likely a TV episode.

    Checks the filename for S##E## patterns, episode markers, anime/fansub
    naming conventions, "Season N" in the filename, and the parent folder
    name for season indicators or extras/featurettes folders.
    Uses only strong signals to avoid false-positiving on movies with
    numbers in the title.
    """
    name = filepath.name

    for pattern in _TV_EPISODE_PATTERNS:
        if pattern.search(name):
            return True

    if _FANSUB_EPISODE_PATTERN.search(name):
        return True

    if _FILENAME_SEASON_PATTERN.search(name):
        return True

    if _TV_COMPANION_VIDEO_PATTERN.search(name):
        return True

    parent = filepath.parent.name
    if _TV_FOLDER_PATTERNS.search(parent):
        return True

    if is_extras_folder(parent):
        return True

    return False


def _extract_tv_title_prefix(filename: str) -> str | None:
    """Extract a conservative show-title prefix from an episodic filename."""
    stem = TRAILING_GROUP.sub("", Path(filename).stem)
    stem = re.sub(r"\[[^\[\]]*\]", "", stem).strip()

    for pattern in _TV_TITLE_PREFIX_PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue
        title = clean_folder_name(match.group("title"), include_year=False)
        title = re.sub(r"\s+", " ", title).strip(" ._-")
        if len(title) >= 2 and re.search(r"[A-Za-z]", title):
            return title
    return None


def _infer_tv_title_from_direct_episode_files(folder: Path) -> str | None:
    """Infer a TV title from direct episode files only when they strongly agree."""
    episode_file_count = 0
    title_counts: dict[str, int] = {}
    title_examples: dict[str, str] = {}

    try:
        entries = list(folder.iterdir())
    except OSError:
        return None

    for child in entries:
        if not child.is_file() or child.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if not looks_like_tv_episode(child):
            continue

        episode_file_count += 1
        title = _extract_tv_title_prefix(child.name)
        if not title:
            continue

        key = title.casefold()
        title_counts[key] = title_counts.get(key, 0) + 1
        title_examples.setdefault(key, title)

    if episode_file_count < 2 or not title_counts:
        return None

    best_key, best_count = max(title_counts.items(), key=lambda item: (item[1], len(item[0])))
    if best_count < 2 or (best_count * 5) < (episode_file_count * 4):
        return None
    return title_examples[best_key]


def best_tv_match_title(folder: Path, *, include_year: bool = True) -> str:
    """Return the best available TV title for matching/search."""
    inferred = _infer_tv_title_from_direct_episode_files(folder)
    if inferred is not None:
        if include_year:
            year = extract_year(folder.name)
            if year:
                return f"{inferred} ({year})"
        return inferred
    return clean_folder_name(folder.name, include_year=include_year)
