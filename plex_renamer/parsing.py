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
    SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS,
)


# ─── Folder / filename cleaning ──────────────────────────────────────────────

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
    # Protect dotted acronyms: sequences of single letters separated by
    # dots, e.g. "S.H.I.E.L.D." → placeholder, restored after dot-replace.
    # Matches 2+ single-letter.dot groups, optionally ending with a trailing dot.
    acronyms: list[tuple[str, str]] = []

    def _protect_acronym(m: re.Match) -> str:
        original = m.group(0)
        # Reconstruct with dots intact as a placeholder token.
        # Strip trailing dot from the acronym itself (not meaningful),
        # but if the original ended with a dot that was separating it
        # from the next content, we add a trailing space to preserve
        # that separation after dot-to-space replacement.
        clean = original.rstrip(".")
        placeholder = f"\x00ACRONYM{len(acronyms)}\x00"
        has_trailing_sep = original.endswith(".") and original != clean
        acronyms.append((placeholder, clean, has_trailing_sep))
        return placeholder + (" " if has_trailing_sep else "")

    s = re.sub(
        r"(?<![A-Za-z])(?:[A-Za-z]\.){2,}(?:[A-Za-z](?=\.|[^A-Za-z]|$)\.?)?",
        _protect_acronym,
        name,
    )

    s = s.replace(".", " ").replace("_", " ")
    # Use [^\[\]]* instead of .*? to avoid spanning across mismatched
    # brackets like [FLE} ... [Dual Audio] where the first [ has no
    # matching ] — .*? would greedily consume everything up to the ]
    # of the second tag, destroying the entire title.
    s = re.sub(r"\[[^\[\]]*\]", "", s)
    s = re.sub(r"\([^()]*\)", "", s)
    # Strip mismatched brackets: [tag} or [tag followed by space/end
    s = re.sub(r"\[[^\[\]]*[}\)]", "", s)
    s = TRAILING_GROUP.sub("", s)

    # Restore acronyms
    for placeholder, original, _ in acronyms:
        s = s.replace(placeholder, original)

    tokens = s.split()
    title_tokens = []
    for token in tokens:
        # Stop at release noise
        if RELEASE_NOISE.search(f" {token} "):
            break
        # Stop at "Season" followed by digits (not part of title)
        if re.match(r"(?i)^(?:Season|Seasons?)$", token):
            break
        title_tokens.append(token)

    title = " ".join(title_tokens).strip().rstrip("-").strip()
    if len(title) < 2:
        title = re.sub(r"\s+", " ", s).strip()

    # Preserve a year from the original name as "(YYYY)" if requested
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
    Extract a plausible release year (1920-2099) from a string.

    Prefers the *last* year that appears before the first release-noise token
    (resolution, codec, source marker).  This correctly handles filenames where
    the title itself starts with a number, e.g.:
        2001.A.Space.Odyssey.1968.2160p  →  "1968"  (not "2001")
        The.Matrix.1999.1080p            →  "1999"

    Falls back to the last year found when no noise boundary is present,
    which correctly handles Plex-format names like "2001 A Space Odyssey (1968)".

    Returns the year as a string, or None if not found.
    """
    all_years = [
        m for m in re.finditer(r"(?:^|[.\s(\-])(\d{4})(?=[.\s)\-]|$)", text)
        if 1920 <= int(m.group(1)) <= 2099
    ]
    if not all_years:
        return None

    # Prefer the last year that appears before the first release-noise token
    noise_m = RELEASE_NOISE.search(text)
    if noise_m:
        before_noise = [m for m in all_years if m.start() < noise_m.start()]
        if before_noise:
            return before_noise[-1].group(1)

    # Fallback: last year found — for Plex-format names like
    # "2001 A Space Odyssey (1968)" or "Blade Runner 2049 (2017)",
    # the parenthesized release year at the end is the correct one.
    return all_years[-1].group(1)


# ─── TV episode detection (for filtering in movie mode) ──────────────────────

# Strong indicators that a file is a TV episode, not a movie.
_TV_EPISODE_PATTERNS = [
    # S01E01, S1E5, s01e01e02, etc.
    re.compile(r"S\d{1,2}E\d{1,3}", re.IGNORECASE),
    # "1x05", "01x05" (common in some naming schemes)
    re.compile(r"\b\d{1,2}x\d{2,3}\b", re.IGNORECASE),
    # Explicit "Episode 5", "Ep05", "Ep.5", "E05" as standalone
    re.compile(r"\b(?:Episode|Ep)[\s._-]*\d{1,3}\b", re.IGNORECASE),
    # Bare-number OVA/episode naming: "01. Title Here.mkv", "13. Final Episode.mkv"
    # Common in OVA releases and anime collections numbered without S##E## tags.
    re.compile(r"^\d{1,3}\.\s+\w"),
]

# Anime/fansub pattern: [Group] Title - ## (tags)
# The combination of a [bracket group] tag AND a dash-delimited episode number
# is an extremely strong TV signal — movies essentially never use this format.
_FANSUB_EPISODE_PATTERN = re.compile(
    r"^\[.+?\]"              # starts with [FansubGroup]
    r".+"                    # title text
    r"\s+-\s+"               # dash separator with spaces
    r"\d{1,3}"               # 1-3 digit episode number
    r"(?:\s*-\s*\d{1,3})*"  # optional episode range/list suffixes
    r"(?:\s|\.|\(|\[|$)",   # followed by space, dot, bracket, paren, or end
)

# Parent folder names that strongly suggest TV content
_TV_FOLDER_PATTERNS = re.compile(
    r"(?:^|[\s._\-])(?:Season|S\d{1,2}|Staffel|Saison|Temporada|Stagione)"
    r"[\s._\-]*\d*",
    re.IGNORECASE,
)

# Folder names that indicate supplemental/extras content — not standalone movies.
# These are extras folders typically found inside a TV series directory.
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


def is_extras_folder(name: str) -> bool:
    """Check if a folder name indicates supplemental/extras content."""
    return bool(EXTRAS_FOLDER_PATTERN.match(name.strip()))


# Matches files that are release sample clips, not the main film.
# Catches bare "Sample.mkv" and embedded "Movie.Title.Sample.mkv" patterns.
_SAMPLE_FILE_RE = re.compile(r"(?i)(?:^|[\s.\-_])sample(?:[\s.\-_]|$)")


def is_sample_file(filepath: Path) -> bool:
    """Return True if the file is a release sample clip, not the main film."""
    return bool(_SAMPLE_FILE_RE.search(filepath.stem))


# Filename patterns that indicate TV content: "Season 3 - ...", "Season3 ..."
_FILENAME_SEASON_PATTERN = re.compile(
    r"(?:^|[\s._\-])(?:Season|Staffel|Saison|Temporada|Stagione)"
    r"[\s._\-]*\d+",
    re.IGNORECASE,
)

# Common anime companion-video markers that indicate OP/ED extras bundled
# with a TV series release rather than standalone movie content.
_TV_COMPANION_VIDEO_PATTERN = re.compile(
    r"(?:^|[\s._\-\[(])(?:NCOP|NCED)(?:\d+)?(?:v\d+)?(?=$|[\s._\-\])])"
    r"|\b(?:creditless|non[\s._\-]*credit(?:ed|less)?|clean)[\s._\-]*"
    r"(?:opening|ending|op|ed)\b",
    re.IGNORECASE,
)


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

    # Anime/fansub pattern: [Group] Title - 02 (tags)
    if _FANSUB_EPISODE_PATTERN.search(name):
        return True

    # "Season 3 - Bloopers" etc. in the filename itself
    if _FILENAME_SEASON_PATTERN.search(name):
        return True

    # Anime OP/ED extras like NCOP/NCED and creditless opening/ending files.
    if _TV_COMPANION_VIDEO_PATTERN.search(name):
        return True

    # Check parent folder — "Season 01", "S02", "Staffel 3", etc.
    parent = filepath.parent.name
    if _TV_FOLDER_PATTERNS.search(parent):
        return True

    # Check parent folder — "Featurettes", "Extras", "Bonus", etc.
    if is_extras_folder(parent):
        return True

    return False


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
        r"^(?:\[[^\]]+\]\s*)?(?P<title>.+?)\s+-\s+\d{1,3}(?:\s*-\s*\d{1,3})*(?=\s|\.|\(|\[|$)",
        re.IGNORECASE,
    ),
)


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
    """Infer a TV title from direct episode files only when they strongly agree.

    This is intentionally conservative: it only overrides the folder-derived
    title when at least two direct child episode files produce the same title
    prefix and that prefix accounts for at least 80% of the episodic files.
    """
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
    """Return the best available TV title for matching/search.

    Prefer a title inferred from direct episode filenames when the evidence is
    strong; otherwise fall back to the folder name parser.
    """
    inferred = _infer_tv_title_from_direct_episode_files(folder)
    if inferred is not None:
        if include_year:
            year = extract_year(folder.name)
            if year:
                return f"{inferred} ({year})"
        return inferred
    return clean_folder_name(folder.name, include_year=include_year)


# ─── Companion subtitle discovery ────────────────────────────────────────────

# Matches a trailing language tag on a subtitle stem, e.g.:
#   ".eng", ".en", ".en.forced", ".fr.sdh"
# Intentionally strict (2-3 letter code only) to avoid false-positives on
# release noise tokens like ".BluRay" or ".EXTENDED".
_LANG_TAG_RE = re.compile(
    r'(\.[a-z]{2,3}(?:\.(?:forced|sdh|cc|hi|default|full))*)$',
    re.IGNORECASE,
)


def _extract_lang_tag(stem: str) -> str:
    """Return the trailing language tag from a subtitle stem, or ""."""
    m = _LANG_TAG_RE.search(stem)
    return m.group(1) if m else ""


def find_companion_subtitles(video_path: Path) -> list[tuple[Path, str]]:
    """
    Find subtitle files in the same directory that pair with a video file.

    Returns a list of ``(subtitle_path, lang_tag)`` pairs.  ``lang_tag`` is
    the string inserted between the new video stem and the subtitle extension
    when building the renamed filename (e.g. ``.eng``, ``.en.forced``, ``""``).

    Pairing strategy
    ----------------
    1. **Exact prefix** — subtitle stem starts with the video stem
       (case-insensitive).  Handles the standard scene-release layout where
       the subtitle file shares the release name::

           The.Movie.2023.1080p.BluRay.mkv
           The.Movie.2023.1080p.BluRay.eng.srt  →  tag ".eng"

    2. **Fuzzy fallback** — if there is exactly one video file in the
       directory and there are unclaimed subtitle files, pair them regardless
       of stem.  This covers subtitles sourced from a different release::

           The.Movie.2023.1080p.BluRay.mkv
           Movie.ALTERNATE.RELEASE.eng.srt      →  tag ".eng" (extracted from stem)
    """
    parent = video_path.parent
    video_stem = video_path.stem
    video_stem_lower = video_stem.lower()

    try:
        all_entries = list(parent.iterdir())
    except OSError:
        return []

    all_subs = [
        f for f in all_entries
        if f.is_file() and f.suffix.lower() in SUBTITLE_EXTENSIONS
    ]
    if not all_subs:
        return []

    paired: list[tuple[Path, str]] = []
    unpaired: list[Path] = []

    for sub in all_subs:
        if sub.stem.lower().startswith(video_stem_lower):
            raw_tag = sub.stem[len(video_stem):]
            # Validate: accept empty (no language) or a recognised ISO 639
            # language code suffix (.eng, .en, .en.forced, etc.).
            # Non-standard values like ".UNKNOWN" or ".English" are not valid
            # Plex language codes — strip them so Plex still recognises the
            # subtitle as a language-less companion (MovieTitle.srt).
            if not raw_tag or _LANG_TAG_RE.fullmatch(raw_tag):
                tag = raw_tag
            else:
                # Try to salvage a valid code buried at the end of the tag
                # (e.g. ".release.group.eng" → ".eng"), then fall back to "".
                tag = _extract_lang_tag(raw_tag)
            paired.append((sub, tag))
        else:
            unpaired.append(sub)

    # Fuzzy fallback: pair unclaimed subtitles when this is the sole video file
    if unpaired:
        video_count = sum(
            1 for f in all_entries
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )
        if video_count == 1:
            for sub in unpaired:
                tag = _extract_lang_tag(sub.stem)
                paired.append((sub, tag))

    return paired


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
    raw_stem = Path(filename).stem
    name = clean_name(raw_stem)

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

    # Pattern 2: Dash-delimited episode numbers, with optional range and title.
    # Examples: "Show - 05", "Show - 05-06", "Show - 05 - Title"
    m = re.search(
        r"-\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?(?:\s*-\s*(.*))?$",
        name,
    )
    if m:
        start_num = int(m.group(1))
        end_num = int(m.group(2)) if m.group(2) else None
        if start_num not in (480, 720, 1080, 2160) and not (1900 <= start_num <= 2099):
            episodes = [start_num]
            if end_num is not None and end_num not in (480, 720, 1080, 2160):
                if end_num >= start_num and end_num - start_num <= 3:
                    episodes = list(range(start_num, end_num + 1))
                else:
                    episodes.append(end_num)
            title = m.group(3).strip() if m.group(3) else None
            return episodes, title, False

    # Pattern 2.5: Bare-number OVA "01. Title Here (2000).mkv"
    # Uses the raw stem (before clean_name) to detect the dot separator
    # that distinguishes this from other number-prefixed filenames.
    bare_m = re.match(r"(\d{1,3})\.\s+(.*)", raw_stem)
    if bare_m:
        num = int(bare_m.group(1))
        if num not in (480, 720, 1080, 2160) and not (1900 <= num <= 2099):
            title_text = bare_m.group(2).strip()
            # Strip trailing parenthesized year
            title_text = re.sub(r"\s*\(\d{4}\)\s*$", "", title_text).strip()
            return [num], title_text or None, False

    # Pattern 3: Episode number preceded by space/separator
    # Negative lookbehind rejects codec tags: x264, x265, h264, h265
    m = re.search(
        r"(?<![xXhH\d])(?:ep?|episode)?\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?",
        name, re.IGNORECASE,
    )
    if m:
        num = int(m.group(1))
        if num not in (480, 720, 1080, 2160) and not (1900 <= num <= 2099):
            # Double-check: reject if the digit sequence was part of a codec tag
            # by examining the characters immediately before the match
            start = m.start()
            if start > 0:
                prefix = name[max(0, start - 1):start]
                if prefix.lower() in ("x", "h"):
                    return [], None, False
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


_ORDINAL_WORDS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    # Ordinal suffix forms: "1st", "2nd", "3rd", "4th", etc.
}

_ORDINAL_SUFFIX_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)", re.IGNORECASE)


def get_season(folder: Path) -> int | None:
    """
    Extract the season number from a folder name.

    Recognizes many common formats:
      - "Season 02", "S02", "Staffel 3", "Saison 3", etc.
      - Ordinal season names: "Second Season", "3rd Season", etc.
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

    # "Season ##" anywhere (1-2 digits only — avoids matching "Season 1080p").
    # Reject if followed by a comma+digit (e.g. "Season 1,2,3" = collection).
    m = re.search(r"season\s*(\d{1,2})(?!\d)", name, re.IGNORECASE)
    if m and not re.match(r"\d{1,2}\s*,\s*\d", name[m.start(1):]):
        return int(m.group(1))

    # "S##" as a standalone token
    m = re.search(r"(?:^|[\s._\-])S(\d{1,2})(?:[\s._\-]|$)", name)
    if m:
        return int(m.group(1))

    # Ordinal word + "Season": "Second Season", "Third Season", etc.
    # Also handles "2nd Season", "3rd Season" suffix ordinals.
    m = re.search(r"(\w+)\s+Season", name, re.IGNORECASE)
    if m:
        word = m.group(1).lower()
        if word in _ORDINAL_WORDS:
            return _ORDINAL_WORDS[word]
        suffix_m = _ORDINAL_SUFFIX_RE.fullmatch(m.group(1))
        if suffix_m:
            return int(suffix_m.group(1))

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


def build_show_folder_name(show: str, year: str) -> str:
    """
    Build a Plex-compatible TV show root folder name.

    Example:
        Marvel's Agents of S.H.I.E.L.D. (2013)
    """
    year_part = f" ({year})" if year else ""
    return sanitize_filename(f"{show}{year_part}")


# ─── Fuzzy matching ─────────────────────────────────────────────────────────

def normalize_for_match(text: str) -> str:
    """
    Normalize a title for fuzzy comparison.

    Strips year suffixes, punctuation, articles, and extra whitespace.
    Returns lowercase with single spaces.  Used by both movie/TV scoring
    and specials fuzzy matching for consistency.
    """
    t = re.sub(r"\s*\(\d{4}\)\s*$", "", text)  # strip trailing (YYYY)
    t = re.sub(r"[^\w\s]", " ", t)  # punctuation → spaces
    t = t.lower().strip()
    # Remove leading articles for matching ("the matrix" == "matrix")
    t = re.sub(r"^(?:the|a|an)\s+", "", t)
    return re.sub(r"\s+", " ", t)


def normalize_for_specials(text: str) -> str:
    """
    Normalize text for specials/extras fuzzy matching.

    Strips everything except lowercase alphanumerics. Delegates to
    normalize_for_match first to get article stripping etc., then
    removes remaining whitespace for substring matching.
    """
    t = normalize_for_match(text)
    return re.sub(r"[^a-z0-9]", "", t)


# ─── Completeness check ────────────────────────────────────────────────────

def is_already_complete(items) -> bool:
    """
    Check if all OK items are already properly named (no rename needed).

    Args:
        items: list of PreviewItem (or any object with .status, .new_name,
               .original, .target_dir attributes).

    Returns True if every OK item already has its correct name in its
    correct location.
    """
    ok_items = [it for it in items if it.status == "OK"]
    if not ok_items:
        return False
    return all(
        it.new_name == it.original.name
        and (it.target_dir is None or it.target_dir == it.original.parent)
        for it in ok_items
    )
