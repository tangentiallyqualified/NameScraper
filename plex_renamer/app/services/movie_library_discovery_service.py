"""Recursive movie-library discovery for nested batch scan workflows."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ..models import MovieDirectoryRole, MovieDiscoveryCandidate
from ._movie_library_classification import ClassifiedDirectory, MovieDirectoryClassifier

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

class MovieLibraryDiscoveryService:
    """Discover nested movie roots without misclassifying container or TV folders."""

    def __init__(self, ignored_system_names: set[str] | None = None):
        self.ignored_system_names = {
            name.casefold() for name in (ignored_system_names or _IGNORED_SYSTEM_NAMES)
        }
        self._classifier = MovieDirectoryClassifier(self.ignored_system_names)

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

    def _classify_directory(self, directory: Path) -> ClassifiedDirectory:
        return self._classifier.classify_directory(directory)

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
