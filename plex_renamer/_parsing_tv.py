"""TV/movie classification and title inference helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import TRAILING_GROUP, VIDEO_EXTENSIONS
from ._parsing_seasons import is_season_only_name
from ._parsing_titles import clean_folder_name, extract_year


_TV_EPISODE_PATTERNS = [
    re.compile(r"S\d{1,2}E\d{1,3}", re.IGNORECASE),
    re.compile(r"\b\d{1,2}x\d{2,3}\b", re.IGNORECASE),
    re.compile(r"\b(?:Episode|Ep)[\s._-]*\d{1,3}\b", re.IGNORECASE),
    re.compile(r"^\d{1,3}\.\s+\w"),
    # Fansub layout: [Group][Show Title][NN]... where [NN] is a pure-numeric
    # episode bracket (resolution/version/hash brackets are not pure digits).
    re.compile(r"^\[[^\]]+\].*\[\d{1,3}\]"),
]

# A bracket whose entire content is a bare episode number (optional version).
_BRACKET_EPISODE_RE = re.compile(r"\[(\d{1,3})(?:v\d+)?\]")

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

# An explicit season-0 episode marker in a FILE name (S00E01). Folder-based
# episode heuristics don't count here: every file inside an extras folder
# "looks like" an episode via its parent name.
_EXPLICIT_SPECIAL_EPISODE_RE = re.compile(
    r"(?:^|[\s._\-\[(])S00E\d{1,3}(?=[\s._\-\])]|$)",
    re.IGNORECASE,
)

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

# A clean show-title prefix never contains a season/episode marker. When the
# extracted candidate still embeds one (e.g. "S03E04 - Vindicators" or
# "3x02 Money Train"), the filename led with the episode number and the match
# actually swallowed the episode title — reject it.
_PREFIX_EPISODE_MARKER_RE = re.compile(
    r"S\d{1,2}\s*E\d{1,3}|\b\d{1,2}x\d{2,3}\b",
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
    re.compile(
        r"^(?:\[[^\]]+\]\s*)?(?P<title>.+?)[ ._\-]+\d{1,3}(?:v\d+)?(?=[ ._\-\[(]|$)",
        re.IGNORECASE,
    ),
)


def is_extras_folder(name: str) -> bool:
    """Check if a folder name indicates supplemental/extras content."""
    return bool(EXTRAS_FOLDER_PATTERN.match(name.strip()))


def has_explicit_special_episode(filename: str) -> bool:
    """Return True when a file name carries an explicit S00E## marker."""
    return bool(_EXPLICIT_SPECIAL_EPISODE_RE.search(filename))


def is_sample_file(filepath: Path) -> bool:
    """Return True if a file is a release sample clip, not the main film."""
    return bool(_SAMPLE_FILE_RE.search(filepath.stem))


def is_companion_video_file(filepath: Path) -> bool:
    """Return True when a video file is a TV companion extra, not an episode."""
    return bool(_TV_COMPANION_VIDEO_PATTERN.search(filepath.name))


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

    if is_companion_video_file(filepath):
        return True

    parent = filepath.parent.name
    if _TV_FOLDER_PATTERNS.search(parent):
        return True

    if is_extras_folder(parent):
        return True

    return False


def _bracket_layout_title(stem: str) -> str | None:
    """Title from a fully-bracketed fansub name: [Group][Title][NN]...

    Returns the bracket group immediately preceding the first pure-numeric
    episode bracket (the show title in `[DBD-Raws][Wolf's Rain][01]...`).
    The folder name for such releases is often unusable (CJK), so this
    per-file English title is the only clean show-search signal.
    """
    groups = list(re.finditer(r"\[([^\[\]]+)\]", stem))
    for index, group in enumerate(groups):
        if index >= 1 and _BRACKET_EPISODE_RE.fullmatch(group.group(0)):
            candidate = clean_folder_name(groups[index - 1].group(1), include_year=False)
            candidate = re.sub(r"\s+", " ", candidate).strip(" ._-")
            if len(candidate) >= 2 and re.search(r"[A-Za-z]", candidate):
                return candidate
            return None
    return None


def extract_source_title_prefix(filename: str) -> str | None:
    """Extract a conservative show-title prefix from an episodic filename."""
    raw_stem = Path(filename).stem
    bracket_title = _bracket_layout_title(raw_stem)
    if bracket_title is not None:
        return bracket_title

    stem = TRAILING_GROUP.sub("", raw_stem)
    stem = re.sub(r"\[[^\[\]]*\]", "", stem).strip()

    for pattern in _TV_TITLE_PREFIX_PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue
        if _PREFIX_EPISODE_MARKER_RE.search(match.group("title")):
            continue
        title = clean_folder_name(match.group("title"), include_year=False)
        title = re.sub(r"\s+", " ", title).strip(" ._-")
        if len(title) >= 2 and re.search(r"[A-Za-z]", title):
            return title
    return None


def _extract_tv_title_prefix(filename: str) -> str | None:
    return extract_source_title_prefix(filename)


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


def best_tv_match_title(
    folder: Path,
    *,
    include_year: bool = True,
    name_fallback_folder: Path | None = None,
) -> str:
    """Return the best available TV title for matching/search.

    ``name_fallback_folder`` substitutes the folder whose NAME is used when
    no title can be inferred from the episode files — a generic
    "Specials (1998-2003)"/"Series" candidate inherits its parent's name.
    """
    inferred = _infer_tv_title_from_direct_episode_files(folder)
    if inferred is not None:
        if include_year:
            year = extract_year(folder.name)
            if year:
                return f"{inferred} ({year})"
        return inferred
    name_source = name_fallback_folder if name_fallback_folder is not None else folder
    return clean_folder_name(name_source.name, include_year=include_year)


# Folder names that label a collection level rather than a show ("Series",
# "Episodes"): meaningless as search queries, like bare season labels.
_GENERIC_SHOW_FOLDER_LABELS = frozenset({"series", "episodes", "collection"})


def is_generic_show_folder_name(name: str) -> bool:
    """True when *name* is only a season/collection label, not a show title.

    Catches bare season-level names once release junk and years are cleaned
    away ("Specials (1998-2003)" -> "Specials", "season 0") plus generic
    collection labels ("Series"). Names that carry a show title alongside
    the label ("Yuru Camp Specials") are NOT generic.
    """
    cleaned = clean_folder_name(name, include_year=False).strip()
    if not cleaned:
        return False
    if cleaned.casefold() in _GENERIC_SHOW_FOLDER_LABELS:
        return True
    return is_season_only_name(cleaned)
