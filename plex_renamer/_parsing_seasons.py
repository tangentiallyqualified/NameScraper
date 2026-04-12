"""Season-folder parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path


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

_ORDINAL_WORDS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

_ORDINAL_SUFFIX_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)", re.IGNORECASE)

_SEASON_ONLY_NAME_RE = re.compile(
    r"^(?:"
    r"specials?|extras?|bonus|OVAs?|OADs?|ONAs?|movies?|shorts?"
    r"|behind[\s._\-]*the[\s._\-]*scenes"
    r"|deleted[\s._\-]*scenes|featurettes?"
    r"|special[\s._\-]*features?"
    r"|(?:season|staffel|saison|temporada|stagione)[\s._\-]*\d{1,2}"
        r"(?:[\s._\-]+.*?)?"
    r"|S\d{1,2}(?:[\s._\-]+\-[\s._\-]+.*)?"
    r"|(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
        r"|\d{1,2}(?:st|nd|rd|th))[\s._\-]+season(?:[\s._\-]+.*)?"
    r"|\d{1,2}"
    r")$",
    re.IGNORECASE,
)


def get_season(folder: Path) -> int | None:
    """
    Extract the season number from a folder name.

    Recognizes many common formats:
      - "Season 02", "S02", "Staffel 3", "Saison 3", etc.
      - Ordinal season names: "Second Season", "3rd Season", etc.
      - Specials/extras folders -> Season 0
      - Bare number folders: "02", "2"

    Returns the season number as an int, or None if not found.
    """
    name = folder.name

    if _SPECIALS_PATTERN.match(name.strip()):
        return 0
    if _SPECIALS_SUFFIX.search(name):
        return 0

    match = re.search(r"season\s*(\d{1,2})(?!\d)", name, re.IGNORECASE)
    if match and not re.match(r"\d{1,2}\s*,\s*\d", name[match.start(1):]):
        return int(match.group(1))

    match = re.search(r"(?:^|[\s._\-])S(\d{1,2})(?:[\s._\-]|$)", name)
    if match:
        return int(match.group(1))

    match = re.search(r"(\w+)\s+Season", name, re.IGNORECASE)
    if match:
        word = match.group(1).lower()
        if word in _ORDINAL_WORDS:
            return _ORDINAL_WORDS[word]
        suffix_match = _ORDINAL_SUFFIX_RE.fullmatch(match.group(1))
        if suffix_match:
            return int(suffix_match.group(1))

    match = re.search(
        r"(?:staffel|saison|temporada|stagione)\s*(\d+)",
        name,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1))

    match = re.fullmatch(r"(\d{1,2})", name.strip())
    if match:
        return int(match.group(1))

    return None


def is_season_only_name(folder_name: str) -> bool:
    """Return True if *folder_name* is primarily a season label."""
    return _SEASON_ONLY_NAME_RE.fullmatch(folder_name.strip()) is not None
