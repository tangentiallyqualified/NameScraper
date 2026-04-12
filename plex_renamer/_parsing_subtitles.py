"""Companion subtitle pairing helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS


_LANG_TAG_RE = re.compile(
    r"(\.[a-z]{2,3}(?:\.(?:forced|sdh|cc|hi|default|full))*)$",
    re.IGNORECASE,
)


def _extract_lang_tag(stem: str) -> str:
    """Return the trailing language tag from a subtitle stem, or ""."""
    match = _LANG_TAG_RE.search(stem)
    return match.group(1) if match else ""


def find_companion_subtitles(video_path: Path) -> list[tuple[Path, str]]:
    """
    Find subtitle files in the same directory that pair with a video file.

    Returns a list of ``(subtitle_path, lang_tag)`` pairs.  ``lang_tag`` is
    the string inserted between the new video stem and the subtitle extension
    when building the renamed filename (e.g. ``.eng``, ``.en.forced``, ``""``).

    Pairing strategy
    ----------------
    1. **Exact prefix** — subtitle stem starts with the video stem
       (case-insensitive).
    2. **Fuzzy fallback** — if there is exactly one video file in the
       directory and there are unclaimed subtitle files, pair them regardless
       of stem.
    """
    parent = video_path.parent
    video_stem = video_path.stem
    video_stem_lower = video_stem.lower()

    try:
        all_entries = list(parent.iterdir())
    except OSError:
        return []

    all_subs = [
        entry for entry in all_entries
        if entry.is_file() and entry.suffix.lower() in SUBTITLE_EXTENSIONS
    ]
    if not all_subs:
        return []

    paired: list[tuple[Path, str]] = []
    unpaired: list[Path] = []

    for sub in all_subs:
        if sub.stem.lower().startswith(video_stem_lower):
            raw_tag = sub.stem[len(video_stem):]
            if not raw_tag or _LANG_TAG_RE.fullmatch(raw_tag):
                tag = raw_tag
            else:
                tag = _extract_lang_tag(raw_tag)
            paired.append((sub, tag))
        else:
            unpaired.append(sub)

    if unpaired:
        video_count = sum(
            1 for entry in all_entries
            if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS
        )
        if video_count == 1:
            for sub in unpaired:
                tag = _extract_lang_tag(sub.stem)
                paired.append((sub, tag))

    return paired
