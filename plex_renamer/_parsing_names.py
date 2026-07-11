"""Name-building and fuzzy-normalization helpers."""

from __future__ import annotations

import re

from ._parsing_titles import sanitize_filename

# Trailing words trimmed from a common title base so multi-part runs collapse
# cleanly ("Sozin's Comet - The Phoenix King"/"...Part 1:..." -> "Sozin's Comet").
_BASE_TRIM_WORDS = frozenset(
    {"part", "pt", "vol", "volume", "chapter", "the", "a", "an"}
)
# A base ENDING in a conjunction ("Tigtone and") is a fragment of the episode
# titles, not a shared name — such runs keep their full joined titles.
_DANGLING_CONJUNCTIONS = frozenset({"and", "or", "&"})
_BASE_TRIM_CHARS = " -–,:;"

# Cap on a generated TV filename (including extension). Keeps full paths well
# under the 255-char component limit with headroom for the output directory.
MAX_FILENAME = 170


def _common_title_base(unique_titles: list[str]) -> str | None:
    """Return the shared leading title of a multi-part run, or None.

    Computes the longest common word-prefix across the (already de-duplicated)
    titles, then trims trailing separators, part-words, and dangling articles.
    Returns the base only when it is non-trivial and an actual shortening.
    """
    if len(unique_titles) < 2:
        return None
    word_lists = [title.split() for title in unique_titles]
    prefix: list[str] = []
    for column in zip(*word_lists):
        head = column[0]
        if all(word.casefold() == head.casefold() for word in column):
            prefix.append(head)
        else:
            break
    while prefix:
        token = prefix[-1].strip(_BASE_TRIM_CHARS).casefold()
        if token == "" or token in _BASE_TRIM_WORDS:
            prefix.pop()
        else:
            break
    if prefix and prefix[-1].strip(_BASE_TRIM_CHARS).casefold() in _DANGLING_CONJUNCTIONS:
        # "Tigtone and the Beautiful War" / "Tigtone and the Wine Crisis"
        # share "Tigtone and the" — a title fragment, not a series-within-a-
        # series name. No collapse: the caller joins the full titles.
        return None
    base = " ".join(prefix).strip(_BASE_TRIM_CHARS)
    if len(base) >= 3 and len(base) < len("-".join(unique_titles)):
        return base
    return None


def build_tv_name(
    show: str,
    year: str,
    season: int,
    episodes: list[int],
    titles: list[str] | str,
    ext: str,
) -> str:
    """
    Build a library-standard (Plex/Jellyfin) TV episode filename.

    Examples:
        Show (2004) - S01E01 - Pilot.mkv
        Show (2004) - S01E01-E02 - Title 1-Title 2.mkv
    """
    year_part = f" ({year})" if year else ""

    if len(episodes) == 1:
        ep_part = f"E{episodes[0]:02d}"
    elif episodes == list(range(episodes[0], episodes[-1] + 1)):
        # Contiguous ascending run -> first-last range (E18-E21), not E18-E19-...
        ep_part = f"E{episodes[0]:02d}-E{episodes[-1]:02d}"
    else:
        ep_part = "-".join(f"E{ep:02d}" for ep in episodes)

    if isinstance(titles, str):
        title_part = titles
    elif len(titles) == 1:
        title_part = titles[0]
    else:
        unique = list(dict.fromkeys(titles))
        base = _common_title_base(unique)
        title_part = base if base is not None else "-".join(unique)

    stem = f"{show}{year_part} - S{season:02d}{ep_part}"
    name = sanitize_filename(f"{stem} - {title_part}{ext}")
    if len(name) > MAX_FILENAME:
        # Trim the title segment word-by-word (never the marker/extension),
        # appending an ellipsis, until the whole filename fits the cap.
        words = title_part.split()
        while True:
            words = words[:-1]
            candidate = " ".join(words)
            trial = f"{stem} - {candidate}…{ext}" if candidate else f"{stem}{ext}"
            name = sanitize_filename(trial)
            if len(name) <= MAX_FILENAME or not candidate:
                break
    return name


def build_movie_name(title: str, year: str, ext: str) -> str:
    """
    Build a library-standard (Plex/Jellyfin) movie filename.

    Example:
        The Matrix (1999).mkv
    """
    year_part = f" ({year})" if year else ""
    raw = f"{title}{year_part}{ext}"
    return sanitize_filename(raw)


def build_show_folder_name(show: str, year: str) -> str:
    """
    Build a library-standard (Plex/Jellyfin) TV show root folder name.

    Example:
        Marvel's Agents of S.H.I.E.L.D. (2013)
    """
    year_part = f" ({year})" if year else ""
    return sanitize_filename(f"{show}{year_part}")


_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _fold_title_symbols(text: str) -> str:
    """Fold notation variants ('&' vs 'and', '#1' vs 'No. 1', 'H²', "I'm")
    to one spelling so title comparison is notation-blind. Applied before
    punctuation stripping so contractions still carry their apostrophes."""
    text = text.translate(_SUPERSCRIPT_DIGITS)
    text = re.sub(r"\b[Ii]['’]m\b", "I am", text)
    text = text.replace("&", " and ")
    text = re.sub(r"#\s*(?=\d)", " number ", text)
    text = re.sub(r"\bno\.?\s*(?=\d)", " number ", text, flags=re.IGNORECASE)
    return text


def normalize_for_match(text: str) -> str:
    """
    Normalize a title for fuzzy comparison.

    Strips year suffixes, punctuation, articles, and extra whitespace.
    Apostrophes are REMOVED (not spaced) so "Hell's" == "Hells".
    Returns lowercase with single spaces.  Used by both movie/TV scoring
    and specials fuzzy matching for consistency.
    """
    text = re.sub(r"\s*\(\d{4}\)\s*$", "", text)
    text = text.replace("’", "'").replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.lower().strip()
    text = re.sub(r"^(?:the|a|an)\s+", "", text)
    return re.sub(r"\s+", " ", text)


def normalize_for_specials_spaced(text: str) -> str:
    """Symbol-folded, space-tokenized normal form (for token-level fuzzy)."""
    return normalize_for_match(_fold_title_symbols(text))


def normalize_for_specials(text: str) -> str:
    """
    Normalize text for specials/extras fuzzy matching.

    Symbol folding + normalize_for_match, then strip everything except
    lowercase alphanumerics for substring matching.
    """
    text = normalize_for_specials_spaced(text)
    return re.sub(r"[^a-z0-9]", "", text)


def is_already_complete(items) -> bool:
    """
    Check if all OK items are already properly named (no rename needed).

    Args:
        items: list of PreviewItem (or any object with .status, .new_name,
               .original, .target_dir attributes).

    Returns True if every OK item already has its correct name in its
    correct location.
    """
    ok_items = [item for item in items if item.status == "OK"]
    if not ok_items:
        return False
    return all(
        item.new_name == item.original.name
        and (item.target_dir is None or item.target_dir == item.original.parent)
        for item in ok_items
    )
