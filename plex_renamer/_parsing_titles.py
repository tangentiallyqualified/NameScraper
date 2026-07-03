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

_LEADING_WEBSITE_RELEASE_PREFIX = re.compile(
    r"^\s*(?:https?://)?www\.[A-Za-z0-9][A-Za-z0-9-]*"
    r"(?:\.[A-Za-z0-9][A-Za-z0-9-]*)+\s*[-\u2013\u2014]+\s*",
    re.IGNORECASE,
)


def _is_release_noise_token(token: str) -> bool:
    if token.casefold() == "it" and token != "iT":
        return False
    return RELEASE_NOISE.search(f" {token} ") is not None


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
    name = _LEADING_WEBSITE_RELEASE_PREFIX.sub("", name)
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
        if _is_release_noise_token(token):
            break
        if re.match(r"(?i)^(?:Season|Seasons?)$", token):
            break
        if re.fullmatch(r"\d{1,3}-\d{1,3}", token):
            break
        title_tokens.append(token)

    title = " ".join(title_tokens).strip().rstrip("-").strip()

    # Drop a dangling trailing article left when a phrase like
    # "The Complete Series" is cut at its release-noise token ("Complete"),
    # e.g. "...The Devil The Complete Series" -> "...The Devil The".  Only
    # strip when more than one token remains so a bare "The" title survives.
    if len(title_tokens) > 1 and title_tokens[-1].lower() in ("the", "a", "an"):
        title = " ".join(title_tokens[:-1]).strip().rstrip("-").strip()

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


_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _strip_quality_parens(text: str) -> str:
    """Remove parenthetical groups that contain a release-noise token or a year.

    Keeps descriptive groups like ``(Pilot)``/``(Again)`` and part numbers
    like ``(1)`` while dropping ``(480p BluRay x265 ImE)``, ``(2008)``, etc.

    Noise check is done per-token (via ``_is_release_noise_token``) so the
    special case that treats "it" (the English word) as non-noise is respected.
    """
    def repl(match: re.Match) -> str:
        inner = match.group(1)
        # Check each whitespace-delimited token for release noise
        tokens = inner.split()
        if any(_is_release_noise_token(t) for t in tokens):
            return " "
        # Check for a standalone 4-digit year within the plausible range
        for m in _YEAR_RE.finditer(inner):
            year = int(m.group(1))
            if YEAR_MIN_EXTRACT <= year <= YEAR_MAX:
                return " "
        return match.group(0)

    return re.sub(r"\(([^()]*)\)", repl, text)


def clean_title_evidence(name: str) -> str:
    """Normalize a filename for episode-TITLE extraction.

    Like ``clean_name`` but PRESERVES descriptive parentheticals such as
    ``(Pilot)``/``(Again)`` (so specials match their TMDB titles) while still
    dropping quality/source parentheticals. Strips square-bracketed tags and
    turns dots/underscores into spaces.

    In dot-spaced release names a lone '_' is the boundary BETWEEN two
    segment titles (Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse);
    flattening it to a space would erase the only segment separator, so it
    becomes ' & ' instead. Names that use '_' as their word separator (no
    dot spacing) keep the plain-space behavior.
    """
    name = re.sub(r"\[.*?\]", "", name)
    name = _strip_quality_parens(name)
    if name.count(".") >= 3 and 1 <= name.count("_") <= 3:
        name = name.replace("_", " & ")
    name = name.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", name).strip()


def strip_release_junk_title(title: str | None) -> str | None:
    """Truncate an extracted episode title at the first release-noise token.

    Episode titles pulled from release filenames keep trailing junk
    ("Execution 1080p CR WEB-DL …"), downgrading exact title evidence to
    substring matches. Token-walk left-to-right and cut at the first
    release-noise token (same strategy as clean_folder_name). Returns None
    when nothing survives.
    """
    if not title:
        return None
    kept: list[str] = []
    for token in title.split():
        if _is_release_noise_token(token):
            break
        kept.append(token)
    result = " ".join(kept).strip(" -–")
    return result or None


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are illegal in filenames on
    Windows and potentially problematic on other operating systems.
    """
    name = name.replace(":", " -")
    name = name.replace("*", "\uFF0A")
    name = name.replace("/", " ")
    name = UNSAFE_FILENAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    return name


_YEAR_RANGE_RE = re.compile(r"(?<!\d)(\d{4})\s*[-–]\s*(\d{4})(?!\d)")


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

    A run range "(2001-2013)" counts as its START year: TMDB indexes shows by
    first-air date, so the range end would match the wrong entry.

    Returns the year as a string, or None if not found.
    """
    range_end_starts = {
        match.start(2)
        for match in _YEAR_RANGE_RE.finditer(text)
        if (
            YEAR_MIN_EXTRACT <= int(match.group(1)) <= YEAR_MAX
            and int(match.group(2)) >= int(match.group(1))
        )
    }
    all_years = [
        match for match in re.finditer(r"(?:^|[.\s(\-])(\d{4})(?=[.\s)\-]|$)", text)
        if YEAR_MIN_EXTRACT <= int(match.group(1)) <= YEAR_MAX
        and match.start(1) not in range_end_starts
    ]
    if not all_years:
        return None

    noise_match = RELEASE_NOISE.search(text)
    if noise_match:
        before_noise = [match for match in all_years if match.start() < noise_match.start()]
        if before_noise:
            return before_noise[-1].group(1)

    return all_years[-1].group(1)
