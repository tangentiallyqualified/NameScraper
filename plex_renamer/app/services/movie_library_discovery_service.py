"""Recursive movie-library discovery for nested batch scan workflows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ...constants import VIDEO_EXTENSIONS
from ...parsing import get_season, is_extras_folder, looks_like_tv_episode
from ..models import MovieDirectoryRole, MovieDiscoveryCandidate

# Reuse the same ignored-system set as TV discovery.
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

# Matches Plex-style "Title (Year)" folder names.
_TITLE_YEAR_RE = re.compile(r".+\(\d{4}\)$")


@dataclass(slots=True)
class _DirChild:
    path: Path
    is_dir: bool
    is_file: bool
    is_symlink: bool
    season_num: int | None = None


@dataclass(slots=True)
class _ClassifiedDirectory:
    role: MovieDirectoryRole
    child_dirs: list[Path]
    discovery_reason: str
    direct_video_file_count: int
    has_title_year_folder_name: bool
    discovered_via_symlink: bool


class MovieLibraryDiscoveryService:
    """Discover nested movie roots without misclassifying container or TV folders."""

    def __init__(self, ignored_system_names: set[str] | None = None):
        self.ignored_system_names = {
            name.casefold() for name in (ignored_system_names or _IGNORED_SYSTEM_NAMES)
        }

    def discover_movie_roots(self, library_root: Path) -> list[MovieDiscoveryCandidate]:
        """Return recursively discovered movie roots below *library_root*."""
        candidates: list[MovieDiscoveryCandidate] = []
        visited_paths: set[str] = set()

        for child in self._iter_child_dirs(library_root):
            self._walk_directory(child, library_root, visited_paths, candidates)

        candidates.sort(key=lambda c: self.normalize_relative_path(c.relative_folder))
        return candidates

    def classify_directory(self, directory: Path) -> MovieDirectoryRole:
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
        candidates: list[MovieDiscoveryCandidate],
    ) -> None:
        canonical = self._canonical_path(directory)
        if canonical is not None:
            if canonical in visited_paths:
                return
            visited_paths.add(canonical)

        classified = self._classify_directory(directory)

        if classified.role in (MovieDirectoryRole.MOVIE_ROOT, MovieDirectoryRole.MULTI_MOVIE_FOLDER):
            try:
                relative_path = directory.relative_to(library_root).as_posix()
            except ValueError:
                relative_path = directory.as_posix()
            parent_relative = str(PurePosixPath(relative_path).parent)
            if parent_relative == ".":
                parent_relative = None
            candidates.append(
                MovieDiscoveryCandidate(
                    folder=directory,
                    relative_folder=relative_path,
                    parent_relative_folder=parent_relative,
                    depth=len(PurePosixPath(relative_path).parts),
                    discovery_reason=classified.discovery_reason,
                    direct_video_file_count=classified.direct_video_file_count,
                    has_title_year_folder_name=classified.has_title_year_folder_name,
                    discovered_via_symlink=classified.discovered_via_symlink,
                )
            )
            return

        if classified.role != MovieDirectoryRole.CONTAINER:
            return

        child_dirs = sorted(
            classified.child_dirs,
            key=lambda child: self.normalize_relative_path(child.name),
        )
        for child in child_dirs:
            self._walk_directory(child, library_root, visited_paths, candidates)

    def _classify_directory(self, directory: Path) -> _ClassifiedDirectory:
        name_cf = directory.name.casefold()

        # --- ignored system folders ---
        if name_cf in self.ignored_system_names:
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.IGNORED_SYSTEM,
                child_dirs=[],
                discovery_reason="ignored_system_name",
                direct_video_file_count=0,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        # --- extras / featurettes folders ---
        if is_extras_folder(directory.name):
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.EXTRAS_FOLDER,
                child_dirs=[],
                discovery_reason="extras_folder",
                direct_video_file_count=0,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        # --- season folders belong to TV, not movies ---
        if get_season(directory) is not None:
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.NON_MOVIE_LEAF,
                child_dirs=[],
                discovery_reason="season_folder",
                direct_video_file_count=0,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        # --- scan direct children ---
        child_entries = self._scan_children(directory)
        child_dirs: list[Path] = []
        direct_video_files: list[Path] = []
        has_direct_season_subdirs = False

        for child in child_entries:
            if child.is_dir:
                if child.path.name.casefold() in self.ignored_system_names:
                    continue
                # Extras/featurettes folders are legitimate movie companions,
                # not season directories. Skip them before checking season_num
                # because get_season() maps specials/extras names to Season 0.
                if is_extras_folder(child.path.name):
                    continue
                if child.season_num is not None:
                    has_direct_season_subdirs = True
                else:
                    child_dirs.append(child.path)
                continue

            if child.is_file and child.path.suffix.lower() in VIDEO_EXTENSIONS:
                direct_video_files.append(child.path)

        # If the folder has direct season subdirectories, it looks like a TV
        # show root — classify as non-movie so we don't steal TV content.
        if has_direct_season_subdirs:
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.NON_MOVIE_LEAF,
                child_dirs=[],
                discovery_reason="has_season_subdirs",
                direct_video_file_count=len(direct_video_files),
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        has_title_year = bool(_TITLE_YEAR_RE.match(directory.name.strip()))
        tv_file_count = sum(1 for f in direct_video_files if looks_like_tv_episode(f))
        non_tv_video_count = len(direct_video_files) - tv_file_count

        # --- movie root: 1-2 non-TV video files ---
        if 1 <= non_tv_video_count <= 2 and tv_file_count == 0:
            reason = "title_year_folder" if has_title_year else "direct_video_files"
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.MOVIE_ROOT,
                child_dirs=[],
                discovery_reason=reason,
                direct_video_file_count=non_tv_video_count,
                has_title_year_folder_name=has_title_year,
                discovered_via_symlink=directory.is_symlink(),
            )

        # --- multi-movie folder: 3+ non-TV video files ---
        if non_tv_video_count >= 3:
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.MULTI_MOVIE_FOLDER,
                child_dirs=[],
                discovery_reason="multiple_direct_video_files",
                direct_video_file_count=non_tv_video_count,
                has_title_year_folder_name=has_title_year,
                discovered_via_symlink=directory.is_symlink(),
            )

        # --- container: has child dirs worth exploring, no/few direct videos ---
        if child_dirs and non_tv_video_count == 0:
            return _ClassifiedDirectory(
                role=MovieDirectoryRole.CONTAINER,
                child_dirs=child_dirs,
                discovery_reason="container_children",
                direct_video_file_count=0,
                has_title_year_folder_name=has_title_year,
                discovered_via_symlink=directory.is_symlink(),
            )

        # --- non-movie leaf ---
        return _ClassifiedDirectory(
            role=MovieDirectoryRole.NON_MOVIE_LEAF,
            child_dirs=[],
            discovery_reason="non_movie_leaf",
            direct_video_file_count=len(direct_video_files),
            has_title_year_folder_name=has_title_year,
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

    @staticmethod
    def _canonical_path(directory: Path) -> str | None:
        try:
            return directory.resolve(strict=False).as_posix().casefold()
        except (OSError, RuntimeError):
            return None
