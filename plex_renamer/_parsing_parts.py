"""Part-marker extraction for multi-file (split) episodes.

A part marker is trailing sequence evidence on a filename stem:
``(2)``, ``Part 2``, ``pt.2``, ``CD2``, ``Disc 2``, or a single letter
directly on the episode token (``S01E05b``). Markers are stripped before
episode parsing (see ``extract_episode``) so they never read as episode
numbers, and recorded as evidence for part-set detection
(spec: docs/superpowers/specs/2026-07-20-multi-file-episode-merge-design.md).
"""

from __future__ import annotations

import re

# Parts are small ordinals. Anything above the cap ("(13)") is far more
# likely a stray counter or track number than a 13-part episode.
_MAX_PART = 12

_TRAILING_MARKER_RE = re.compile(
    r"""[\s._\-]*(?:
        \((?P<paren>\d{1,2})\)
        | (?:part|pt)[\s._\-]*(?P<part>\d{1,2})
        | (?:cd|disc|disk)[\s._\-]*(?P<disc>\d{1,2})
    )\s*$""",
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


def split_part_marker(stem: str) -> tuple[str, int | None]:
    """Return ``(base_stem, part_number)``; ``(stem, None)`` when unmarked.

    The base stem is the marker-free remainder used both for grouping
    (identical base = same episode candidate) and for episode parsing.
    """
    match = _TRAILING_MARKER_RE.search(stem)
    if match is not None:
        raw = match.group("paren") or match.group("part") or match.group("disc")
        part = int(raw)
        if 1 <= part <= _MAX_PART:
            return stem[: match.start()].rstrip(), part
    letter = _EPISODE_LETTER_RE.search(stem)
    if letter is not None:
        part = ord(letter.group("letter").lower()) - ord("a") + 1
        base = stem[: letter.end("token")] + stem[letter.end("letter") :]
        return base.rstrip(), part
    return stem, None
