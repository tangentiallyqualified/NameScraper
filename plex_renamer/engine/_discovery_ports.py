"""Structural ports for application-owned library discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence


class TVDiscoveryCandidateLike(Protocol):
    folder: Path
    relative_folder: str
    parent_relative_folder: str | None
    discovery_reason: str
    has_direct_season_subdirs: bool
    direct_episode_file_count: int
    direct_video_file_count: int
    discovered_via_symlink: bool


class MovieDiscoveryCandidateLike(Protocol):
    folder: Path
    relative_folder: str
    parent_relative_folder: str | None
    discovery_reason: str
    direct_video_file_count: int
    discovered_via_symlink: bool


class TVLibraryDiscoverer(Protocol):
    def discover_show_roots(
        self,
        library_root: Path,
    ) -> Sequence[TVDiscoveryCandidateLike]: ...


class MovieLibraryDiscoverer(Protocol):
    def discover_movie_roots(
        self,
        library_root: Path,
    ) -> Sequence[MovieDiscoveryCandidateLike]: ...
