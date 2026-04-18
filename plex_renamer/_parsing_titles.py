"""Title cleaning and year-extraction helpers."""

from __future__ import annotations

import re

from .constants import (
    RELEASE_NOISE,
    TRAILING_GROUP,
    UNSAFE_FILENAME_CHARS,
    YEAR_MAX,
    YEAR_MIN_EXTRACT,
)


def clean_folder_name(name: str, *, include_year: bool = True) -> str:
    """
    Extract a human-readable title from a release-group style folder name.

    Example input:
        Dragon.Ball.Super.1080p.Blu-Ray.10-Bit.Dual-Audio.TrueHD.x265-iAHD

    Args:
        include_year: If True (default), appends "(YYYY)" to the title
            when a year is found.  Set to False when the caller needs
            only the bare title (e.g. for TMDB search queries).

    Strategy:
      1. Protect dotted acronyms (e.g. S.H.I.E.L.D.) from being split
      2. Replace dots/underscores with spaces
      3. Remove bracketed tags [group] and (tags)
      4. Strip trailing release group after the last hyphen
      5. Walk tokens left-to-right; stop at the first release-noise token
         or a "Season" indicator
      6. Everything before that noise token is the title
      7. If a 4-digit year is found and include_year is True, preserve it
         in parentheses
    """
    acronyms: list[tuple[str, str, bool]] = []

    def _protect_acronym(match: re.Match) -> str:
        original = match.group(0)
        clean = original.rstrip(".")
        placeholder = f"\x00ACRONYM{len(acronyms)}\x00"
        has_trailing_sep = original.endswith(".") and original != clean
        acronyms.append((placeholder, clean, has_trailing_sep))
        return placeholder + (" " if has_trailing_sep else "")

    text = re.sub(
        r"(?<![A-Za-z])(?:[A-Za-z]\.){2,}(?:[A-Za-z](?=\.|[^A-Za-z]|$)\.?)?",
        _protect_acronym,
        name,
    )

    text = text.replace(".", " ").replace("_", " ")
    text = re.sub(r"\[[^\[\]]*\]", "", text)
    text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\[[^\[\]]*[}\)]", "", text)
    text = TRAILING_GROUP.sub("", text)

    for placeholder, original, _has_trailing_sep in acronyms:
        text = text.replace(placeholder, original)

    tokens = text.split()
    title_tokens = []
    for token in tokens:
        if RELEASE_NOISE.search(f" {token} "):
            break
        if re.match(r"(?i)^(?:Season|Seasons?)$", token):
            break
        if re.fullmatch(r"\d{1,3}-\d{1,3}", token):
            break
        title_tokens.append(token)

    title = " ".join(title_tokens).strip().rstrip("-").strip()
    if len(title) < 2:
        title = re.sub(r"\s+", " ", text).strip()

    year = extract_year(name)
    if year:
        title = re.sub(r"\s*\(?\b" + year + r"\b\)?\s*", " ", title).strip()
        if include_year:
            title = f"{title} ({year})"

    return re.sub(r"\s+", " ", title).strip()


def clean_name(name: str) -> str:
    """
    Normalize a filename for pattern matching.

    Strips square-bracketed tags (fansub groups, quality tags) but preserves
    parenthesized years like (2023) and part numbers like (1), (2).
    Dots and underscores become spaces.
    """
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\((?!(?:\d{4}|\d{1,2})\))[^)]*\)", "", name)
    name = name.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", name).strip()


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are illegal in filenames on
    Windows and potentially problematic on other operating systems.
    """
    name = name.replace(":", " -")
    name = name.replace("*", "\uFF0A")
    name = UNSAFE_FILENAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    return name


def extract_year(text: str) -> str | None:
    """
    Extract a plausible release year (1920-2099) from a string.

    Prefers the *last* year that appears before the first release-noise token
    (resolution, codec, source marker).  This correctly handles filenames where
    the title itself starts with a number, e.g.:
        2001.A.Space.Odyssey.1968.2160p  ->  "1968"  (not "2001")
        The.Matrix.1999.1080p            ->  "1999"

    Falls back to the last year found when no noise boundary is present,
    which correctly handles Plex-format names like "2001 A Space Odyssey (1968)".

    Returns the year as a string, or None if not found.
    """
    all_years = [
        match for match in re.finditer(r"(?:^|[.\s(\-])(\d{4})(?=[.\s)\-]|$)", text)
        if YEAR_MIN_EXTRACT <= int(match.group(1)) <= YEAR_MAX
    ]
    if not all_years:
        return None

    noise_match = RELEASE_NOISE.search(text)
    if noise_match:
        before_noise = [match for match in all_years if match.start() < noise_match.start()]
        if before_noise:
            return before_noise[-1].group(1)

    return all_years[-1].group(1)
