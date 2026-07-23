"""Shared type contracts for batch orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeAlias, TypedDict

from ._discovery_ports import MovieDiscoveryCandidateLike, TVDiscoveryCandidateLike
from .models import DirectEpisodeEvidence


class TVCandidateStateKwargs(TypedDict):
    relative_folder: str
    parent_relative_folder: str | None
    discovery_reason: str
    has_direct_season_subdirs: bool
    direct_episode_file_count: int
    direct_video_file_count: int
    discovered_via_symlink: bool


ShowCandidate: TypeAlias = tuple[
    TVDiscoveryCandidateLike,
    str,
    str,
    str,
    str | None,
    list[DirectEpisodeEvidence],
]
MovieCandidate: TypeAlias = tuple[
    MovieDiscoveryCandidateLike,
    str,
    str | None,
    Path | None,
]
ProgressCallback: TypeAlias = Callable[..., object]
ProviderOverride: TypeAlias = Mapping[str, str | int | None]
ProviderOverrides: TypeAlias = Mapping[str, ProviderOverride]
