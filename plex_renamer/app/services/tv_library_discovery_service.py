"""Recursive TV-library discovery for nested batch scan workflows."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ...constants import VIDEO_EXTENSIONS
from ...parsing import get_season, is_extras_folder, looks_like_tv_episode
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


@dataclass(slots=True)
class _DirChild:
    path: Path
    is_dir: bool
    is_file: bool
    is_symlink: bool
    season_num: int | None = None


@dataclass(slots=True)
class _ClassifiedDirectory:
    role: TVDirectoryRole
    child_dirs: list[Path]
    discovery_reason: str
    has_direct_season_subdirs: bool
    direct_episode_file_count: int
    direct_video_file_count: int
    discovered_via_symlink: bool


class TVLibraryDiscoveryService:
    """Discover nested TV show roots without misclassifying container folders."""

    def __init__(self, ignored_system_names: set[str] | None = None):
        self.ignored_system_names = {
            name.casefold() for name in (ignored_system_names or _IGNORED_SYSTEM_NAMES)
        }

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
        if (
            root_classified.role == TVDirectoryRole.SHOW_ROOT
            and root_classified.has_direct_season_subdirs
            and self._season_children_are_majority(library_root)
        ):
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
        name_cf = directory.name.casefold()
        if name_cf in self.ignored_system_names:
            return _ClassifiedDirectory(
                role=TVDirectoryRole.IGNORED_SYSTEM,
                child_dirs=[],
                discovery_reason="ignored_system_name",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=0,
                discovered_via_symlink=directory.is_symlink(),
            )
        if is_extras_folder(directory.name):
            return _ClassifiedDirectory(
                role=TVDirectoryRole.NON_TV_LEAF,
                child_dirs=[],
                discovery_reason="extras_folder",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=0,
                discovered_via_symlink=directory.is_symlink(),
            )
        if get_season(directory) is not None:
            return _ClassifiedDirectory(
                role=TVDirectoryRole.SEASON_FOLDER,
                child_dirs=[],
                discovery_reason="season_folder_name",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=0,
                discovered_via_symlink=directory.is_symlink(),
            )

        child_entries = self._scan_children(directory)
        child_dirs: list[Path] = []
        direct_video_files: list[Path] = []
        has_direct_season_subdirs = False

        for child in child_entries:
            if child.is_dir:
                if child.path.name.casefold() in self.ignored_system_names:
                    continue
                if child.season_num is not None:
                    has_direct_season_subdirs = True
                else:
                    child_dirs.append(child.path)
                continue

            if child.is_file and child.path.suffix.lower() in VIDEO_EXTENSIONS:
                direct_video_files.append(child.path)

        direct_episode_file_count = sum(
            1 for video_path in direct_video_files
            if looks_like_tv_episode(video_path)
        )

        if has_direct_season_subdirs:
            return _ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="direct_season_subdirs",
                has_direct_season_subdirs=True,
                direct_episode_file_count=direct_episode_file_count,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if direct_episode_file_count > 0:
            return _ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="direct_episode_files",
                has_direct_season_subdirs=False,
                direct_episode_file_count=direct_episode_file_count,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if len(direct_video_files) > 2:
            return _ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="multiple_direct_video_files",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if child_dirs:
            return _ClassifiedDirectory(
                role=TVDirectoryRole.CONTAINER,
                child_dirs=child_dirs,
                discovery_reason="container_children",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        return _ClassifiedDirectory(
            role=TVDirectoryRole.NON_TV_LEAF,
            child_dirs=[],
            discovery_reason="non_tv_leaf",
            has_direct_season_subdirs=False,
            direct_episode_file_count=direct_episode_file_count,
            direct_video_file_count=len(direct_video_files),
            discovered_via_symlink=directory.is_symlink(),
        )

    @staticmethod
    def _scan_children(directory: Path) -> list[_DirChild]:
        children: list[_DirChild] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    try:
                        entry_path = Path(entry.path)
                        is_dir = entry.is_dir(follow_symlinks=True)
                        is_file = entry.is_file(follow_symlinks=True)
                        season_num = get_season(entry_path) if is_dir else None
                        children.append(
                            _DirChild(
                                path=entry_path,
                                is_dir=is_dir,
                                is_file=is_file,
                                is_symlink=entry.is_symlink(),
                                season_num=season_num,
                            )
                        )
                    except OSError:
                        continue
        except OSError:
            return []
        return children

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
        """Return True if the majority of child directories are season folders.

        This distinguishes a real show folder (where most children are
        seasons like ``Season 01``, ``S04``, ``Second Season``) from a
        batch library where a few show folders happen to contain ``S##``
        in their names (e.g. ``[FLE} Solo Leveling - S01 ...``).

        Only children with season number >= 1 are counted as season dirs.
        Season 0 / Specials folders are excluded from both counts so they
        don't skew the ratio either way.
        """
        children = self._scan_children(directory)
        season_count = 0
        non_season_count = 0
        for child in children:
            if not child.is_dir:
                continue
            if child.path.name.casefold() in self.ignored_system_names:
                continue
            if is_extras_folder(child.path.name):
                continue
            sn = get_season(child.path)
            if sn is not None and sn == 0:
                # Specials/S00 — don't count in either direction
                continue
            if sn is not None and sn >= 1:
                season_count += 1
            else:
                non_season_count += 1
        total = season_count + non_season_count
        if total == 0:
            return False
        return season_count > total / 2

    @staticmethod
    def _canonical_path(directory: Path) -> str | None:
        try:
            return directory.resolve(strict=False).as_posix().casefold()
        except (OSError, RuntimeError):
            return None