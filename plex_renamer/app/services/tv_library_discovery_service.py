"""Recursive TV-library discovery for nested batch scan workflows."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ...parsing import get_season, is_extras_folder
from ._tv_library_classification import (
    ClassifiedDirectory as _ClassifiedDirectory,
    DirChild as _DirChild,
    TVDirectoryClassifier,
)
from ..models import TVDirectoryRole, TVDiscoveryCandidate


_IGNORED_SYSTEM_NAMES = {
    "@eadir",
    ".ds_store",
    ".metadata",
    ".plexmatch",
    "$recycle.bin",
    "system volume information",
    "lost+found",
    ".debris",
    "#recycle",
}

class TVLibraryDiscoveryService:
    """Discover nested TV show roots without misclassifying container folders."""

    def __init__(self, ignored_system_names: set[str] | None = None):
        self.ignored_system_names = {
            name.casefold() for name in (ignored_system_names or _IGNORED_SYSTEM_NAMES)
        }
        self._classifier = TVDirectoryClassifier(self.ignored_system_names)

    def discover_show_roots(self, library_root: Path) -> list[TVDiscoveryCandidate]:
        """Return recursively discovered TV show roots below *library_root*.

        If the library_root itself looks like a show root (has direct season
        subdirectories), it is returned as the sole candidate rather than
        walking children.  This handles the common case where the user selects
        a single show folder instead of a multi-show library.
        """
        # Check if the root itself is a show folder (has season subdirs).
        # This handles the common case where the user selects a single show
        # folder instead of a multi-show library.
        #
        # Guard: only treat the root as a show if the MAJORITY of its child
        # directories are season folders.  A batch library like:
        #   Quarantine/
        #     S00/                          <- season 0
        #     [FLE} Solo Leveling - S01/    <- get_season sees "S01"
        #     [sam] Haikyuu!!/              <- show root
        # has 2 season-like children out of 3 dirs but they belong to
        # different shows.  A real single-show folder like:
        #   Haikyuu!!/
        #     Season 01/                    <- season 1
        #     Second Season/                <- season 2
        #     S04/                          <- season 4
        #     Karasuno.../                  <- non-season (named season)
        # has 3 out of 4 as season dirs — a strong majority.
        root_classified = self._classify_directory(library_root)
        if root_classified.role == TVDirectoryRole.SHOW_ROOT:
            # The root itself looks like a show folder.  Return it as the
            # sole candidate when either:
            #   a) It has season subdirs AND the majority of children are
            #      seasons (distinguishes a real show from a batch library
            #      where a few folders happen to contain "S##").
            #   b) It has direct episode files but NO season subdirs — a
            #      flat show folder like "[FLE] Solo Leveling - S01 (…)/".
            is_season_root = (
                root_classified.has_direct_season_subdirs
                and self._season_children_are_majority(library_root)
            )
            is_flat_episode_root = (
                not root_classified.has_direct_season_subdirs
                and root_classified.direct_episode_file_count > 0
            )
            if is_season_root or is_flat_episode_root:
                return [
                    TVDiscoveryCandidate(
                        folder=library_root,
                        relative_folder=".",
                        parent_relative_folder=None,
                        depth=0,
                        discovery_reason=root_classified.discovery_reason,
                        has_direct_season_subdirs=root_classified.has_direct_season_subdirs,
                        direct_episode_file_count=root_classified.direct_episode_file_count,
                        direct_video_file_count=root_classified.direct_video_file_count,
                        discovered_via_symlink=root_classified.discovered_via_symlink,
                    )
                ]

        candidates: list[TVDiscoveryCandidate] = []
        visited_paths: set[str] = set()

        for child in self._iter_child_dirs(library_root):
            self._walk_directory(child, library_root, visited_paths, candidates)

        candidates.sort(key=lambda candidate: self.normalize_relative_path(candidate.relative_folder))
        return candidates

    def classify_directory(self, directory: Path) -> TVDirectoryRole:
        """Classify a directory using direct-child evidence only."""
        return self._classify_directory(directory).role

    @staticmethod
    def normalize_relative_path(relative_folder: str) -> str:
        """Return a cross-platform normalized path string for stable sorting."""
        text = relative_folder.replace("\\", "/")
        return PurePosixPath(text).as_posix().casefold()

    def _walk_directory(
        self,
        directory: Path,
        library_root: Path,
        visited_paths: set[str],
        candidates: list[TVDiscoveryCandidate],
    ) -> None:
        canonical = self._canonical_path(directory)
        if canonical is not None:
            if canonical in visited_paths:
                return
            visited_paths.add(canonical)

        classified = self._classify_directory(directory)
        if classified.role == TVDirectoryRole.SHOW_ROOT:
            try:
                relative_path = directory.relative_to(library_root).as_posix()
            except ValueError:
                relative_path = directory.as_posix()
            parent_relative = str(PurePosixPath(relative_path).parent)
            if parent_relative == ".":
                parent_relative = None
            candidates.append(
                TVDiscoveryCandidate(
                    folder=directory,
                    relative_folder=relative_path,
                    parent_relative_folder=parent_relative,
                    depth=len(PurePosixPath(relative_path).parts),
                    discovery_reason=classified.discovery_reason,
                    has_direct_season_subdirs=classified.has_direct_season_subdirs,
                    direct_episode_file_count=classified.direct_episode_file_count,
                    direct_video_file_count=classified.direct_video_file_count,
                    discovered_via_symlink=classified.discovered_via_symlink,
                )
            )
            return

        if classified.role != TVDirectoryRole.CONTAINER:
            return

        child_dirs = sorted(
            classified.child_dirs,
            key=lambda child: self.normalize_relative_path(child.name),
        )
        for child in child_dirs:
            self._walk_directory(child, library_root, visited_paths, candidates)

    def _classify_directory(self, directory: Path) -> _ClassifiedDirectory:
        return self._classifier.classify_directory(directory)

    def _counts_as_season_subdir(self, child: _DirChild) -> bool:
        return self._classifier.counts_as_season_subdir(child)

    @staticmethod
    def _scan_children(directory: Path) -> list[_DirChild]:
        return TVDirectoryClassifier.scan_children(directory)

    @staticmethod
    def _iter_child_dirs(directory: Path) -> list[Path]:
        children: list[Path] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    try:
                        if entry.is_dir(follow_symlinks=True):
                            children.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            return []
        return sorted(children, key=lambda child: child.name.casefold())

    def _season_children_are_majority(self, directory: Path) -> bool:
        return self._classifier.season_children_are_majority(directory)

    @staticmethod
    def _child_title_matches_parent(child_name: str, parent_title_cf: str) -> bool:
        return TVDirectoryClassifier.child_title_matches_parent(child_name, parent_title_cf)

    @staticmethod
    def _canonical_path(directory: Path) -> str | None:
        try:
            return directory.resolve(strict=False).as_posix().casefold()
        except (OSError, RuntimeError):
            return None