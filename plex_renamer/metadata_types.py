"""Provider-normalized scalar metadata records."""

from __future__ import annotations

from typing import TypeAlias

MediaInfoValue: TypeAlias = str | int | float | None
MediaInfo: TypeAlias = dict[str, MediaInfoValue]
ScoredMediaInfo: TypeAlias = list[tuple[MediaInfo, float]]
