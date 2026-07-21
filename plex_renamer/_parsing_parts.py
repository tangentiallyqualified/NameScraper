"""Part-marker extraction for multi-file (split) episodes.

A part marker is trailing sequence evidence on a filename stem:
``(2)``, ``Part 2``, ``pt.2``, ``CD2``, ``Disc 2``, or a single letter
directly on the episode token (``S01E05b``).

The forms split into two precision tiers, and callers pick the tier that
matches their risk tolerance:

- UNAMBIGUOUS forms (trailing ``(n)``, ``CD n``/``Disc n``/``Disk n``, and
  the episode-token letter suffix) are almost never genuine title text, so
  they are safe to strip before episode parsing (``extract_episode`` uses
  ``split_unambiguous_part_marker`` for this).
- AMBIGUOUS forms (``Part n`` / ``pt n``) are frequently real title text
  ("The Big Game Part 2" is a title, not a two-part file). Stripping them
  at parse time would corrupt title evidence the confidence engine relies
  on, and it is not needed for episode-number correctness anyway:
  ``_parse_bare_number``'s ``_NUMBER_WORD_PREFIXES`` guard already keeps
  "Part 1" from being misread as episode 1. Only part-set *detection*
  (``split_part_marker``, used by
  ``engine/_episode_resolution.py::detect_part_groups``) needs to recognize
  "Part n" as sequence evidence, since that is a real (if ambiguous) signal
  that two files are parts of the same episode.
  Supported trailing part-marker forms include parenthesized numbers,
  ``Part``/``pt.`` numbers, ``CD``/``Disc`` numbers, and single-letter
  episode-token suffixes.
"""

from __future__ import annotations

import re

# Parts are small ordinals. Anything above the cap ("(13)") is far more
# likely a stray counter or track number than a 13-part episode.
_MAX_PART = 12

# Shared trailing pieces: a marker must sit at the end of the stem (only
# trailing whitespace allowed) to distinguish it from mid-title text.
_UNAMBIGUOUS_MARKER_RE = re.compile(
    r"""[\s._\-]*(?:
        \((?P<paren>\d{1,2})\)
        | (?:cd|disc|disk)[\s._\-]*(?P<disc>\d{1,2})
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

_AMBIGUOUS_MARKER_RE = re.compile(
    r"""[\s._\-]*(?:part|pt)[\s._\-]*(?P<part>\d{1,2})\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Letter suffix directly on an S##E## token: "S01E05a" -> part 1.
# Range guard a-d: beyond four parts, letter naming is unheard of, and a
# wider class would eat codec/quality letters. Must be at end of stem (only
# trailing whitespace allowed) to distinguish from title text.
_EPISODE_LETTER_RE = re.compile(
    r"(?P<token>\bS\d{1,2}[\s._-]*E\d{1,3})(?P<letter>[a-d])(?:\s*$)",
    re.IGNORECASE,
)


def _split_letter_marker(stem: str) -> tuple[str, int | None]:
    """Strip a trailing episode-token letter suffix; unambiguous either way."""
    letter = _EPISODE_LETTER_RE.search(stem)
    if letter is not None:
        part = ord(letter.group("letter").lower()) - ord("a") + 1
        base = stem[: letter.end("token")] + stem[letter.end("letter") :]
        return base.rstrip(), part
    return stem, None


def split_unambiguous_part_marker(stem: str) -> tuple[str, int | None]:
    """Return ``(base_stem, part_number)`` for HIGH-precision markers only.

    Recognizes trailing ``(n)``, ``CD n``/``Disc n``/``Disk n``, and the
    episode-token letter suffix - forms that are almost never genuine title
    text. ``Part n``/``pt n`` pass through unstripped (see module docstring).
    Safe to call before episode parsing.
    """
    match = _UNAMBIGUOUS_MARKER_RE.search(stem)
    if match is not None:
        raw = match.group("paren") or match.group("disc")
        part = int(raw)
        if 1 <= part <= _MAX_PART:
            return stem[: match.start()].rstrip(), part
    return _split_letter_marker(stem)


def split_part_marker(stem: str) -> tuple[str, int | None]:
    """Return ``(base_stem, part_number)``; ``(stem, None)`` when unmarked.

    Recognizes ALL marker forms, including the ambiguous ``Part n``/``pt n``
    forms. The base stem is the marker-free remainder used for grouping
    (identical base = same episode candidate) in part-set detection. Not
    safe to use before episode parsing - see module docstring.
    """
    match = _UNAMBIGUOUS_MARKER_RE.search(stem)
    if match is not None:
        raw = match.group("paren") or match.group("disc")
        part = int(raw)
        if 1 <= part <= _MAX_PART:
            return stem[: match.start()].rstrip(), part
    match = _AMBIGUOUS_MARKER_RE.search(stem)
    if match is not None:
        part = int(match.group("part"))
        if 1 <= part <= _MAX_PART:
            return stem[: match.start()].rstrip(), part
    return _split_letter_marker(stem)
