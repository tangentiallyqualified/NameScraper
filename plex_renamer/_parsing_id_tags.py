"""Bracketed provider-ID tags: {tmdb-123}, [tvdb-81189], {tvdbid=55}, ...

Plex/Sonarr-style tags embedded in folder or file names. Recognized
providers are exactly the TV_PROVIDERS registry names (tmdb, tvdb);
`id` suffix and `-`/`=`/`:`/space separators are tolerated, case-blind.
"""

from __future__ import annotations

import re

_ID_TAG_RE = re.compile(
    r"[\[{]\s*(?P<provider>tmdb|tvdb)(?:id)?\s*[-=: ]\s*(?P<id>\d+)\s*[\]}]",
    re.IGNORECASE,
)


def extract_provider_id_tag(name: str) -> tuple[str, int] | None:
    """First provider-ID tag in *name*, or None."""
    match = _ID_TAG_RE.search(name)
    if match is None:
        return None
    return (match.group("provider").lower(), int(match.group("id")))


def strip_provider_id_tags(name: str) -> str:
    """*name* with every provider-ID tag removed and whitespace collapsed."""
    stripped = _ID_TAG_RE.sub(" ", name)
    return re.sub(r"\s{2,}", " ", stripped).strip()
