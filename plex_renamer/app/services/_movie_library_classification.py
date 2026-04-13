"""Folder-classification helpers for recursive movie library discovery."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ...constants import VIDEO_EXTENSIONS
from ...parsing import get_season, is_extras_folder, looks_like_tv_episode
from ..models import MovieDirectoryRole

_TITLE_YEAR_RE = re.compile(r".+\(\d{4}\)$")


@dataclass(slots=True)
class DirChild:
    path: Path
    is_dir: bool
    is_file: bool
    is_symlink: bool
    season_num: int | None = None


@dataclass(slots=True)
class ClassifiedDirectory:
    role: MovieDirectoryRole
    child_dirs: list[Path]
    discovery_reason: str
    direct_video_file_count: int
    has_title_year_folder_name: bool
    discovered_via_symlink: bool


class MovieDirectoryClassifier:
    """Encapsulate movie folder classification heuristics."""

    def __init__(self, ignored_system_names: set[str]):
        self.ignored_system_names = ignored_system_names

    def classify_directory(self, directory: Path) -> ClassifiedDirectory:
        name_cf = directory.name.casefold()

        if name_cf in self.ignored_system_names:
            return ClassifiedDirectory(
                role=MovieDirectoryRole.IGNORED_SYSTEM,
                child_dirs=[],
                discovery_reason="ignored_system_name",
                direct_video_file_count=0,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        if is_extras_folder(directory.name):
            return ClassifiedDirectory(
                role=MovieDirectoryRole.EXTRAS_FOLDER,
                child_dirs=[],
                discovery_reason="extras_folder",
                direct_video_file_count=0,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        if get_season(directory) is not None:
            return ClassifiedDirectory(
                role=MovieDirectoryRole.NON_MOVIE_LEAF,
                child_dirs=[],
                discovery_reason="season_folder",
                direct_video_file_count=0,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        child_entries = self.scan_children(directory)
        child_dirs: list[Path] = []
        direct_video_files: list[Path] = []
        has_direct_season_subdirs = False

        for child in child_entries:
            if child.is_dir:
                if child.path.name.casefold() in self.ignored_system_names:
                    continue
                if is_extras_folder(child.path.name):
                    continue
                if child.season_num is not None:
                    has_direct_season_subdirs = True
                else:
                    child_dirs.append(child.path)
                continue

            if child.is_file and child.path.suffix.lower() in VIDEO_EXTENSIONS:
                direct_video_files.append(child.path)

        if has_direct_season_subdirs:
            return ClassifiedDirectory(
                role=MovieDirectoryRole.NON_MOVIE_LEAF,
                child_dirs=[],
                discovery_reason="has_season_subdirs",
                direct_video_file_count=len(direct_video_files),
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        has_title_year = bool(_TITLE_YEAR_RE.match(directory.name.strip()))
        tv_file_count = sum(1 for video_path in direct_video_files if looks_like_tv_episode(video_path))
        non_tv_video_count = len(direct_video_files) - tv_file_count
        total_video = len(direct_video_files)

        if total_video > 0 and tv_file_count > total_video / 2:
            return ClassifiedDirectory(
                role=MovieDirectoryRole.NON_MOVIE_LEAF,
                child_dirs=[],
                discovery_reason="majority_tv_content",
                direct_video_file_count=non_tv_video_count,
                has_title_year_folder_name=False,
                discovered_via_symlink=directory.is_symlink(),
            )

        if 1 <= non_tv_video_count <= 2 and tv_file_count == 0:
            reason = "title_year_folder" if has_title_year else "direct_video_files"
            return ClassifiedDirectory(
                role=MovieDirectoryRole.MOVIE_ROOT,
                child_dirs=[],
                discovery_reason=reason,
                direct_video_file_count=non_tv_video_count,
                has_title_year_folder_name=has_title_year,
                discovered_via_symlink=directory.is_symlink(),
            )

        if non_tv_video_count >= 3:
            return ClassifiedDirectory(
                role=MovieDirectoryRole.MULTI_MOVIE_FOLDER,
                child_dirs=[],
                discovery_reason="multiple_direct_video_files",
                direct_video_file_count=non_tv_video_count,
                has_title_year_folder_name=has_title_year,
                discovered_via_symlink=directory.is_symlink(),
            )

        if child_dirs and non_tv_video_count == 0:
            return ClassifiedDirectory(
                role=MovieDirectoryRole.CONTAINER,
                child_dirs=child_dirs,
                discovery_reason="container_children",
                direct_video_file_count=0,
                has_title_year_folder_name=has_title_year,
                discovered_via_symlink=directory.is_symlink(),
            )

        return ClassifiedDirectory(
            role=MovieDirectoryRole.NON_MOVIE_LEAF,
            child_dirs=[],
            discovery_reason="non_movie_leaf",
            direct_video_file_count=len(direct_video_files),
            has_title_year_folder_name=has_title_year,
            discovered_via_symlink=directory.is_symlink(),
        )

    @staticmethod
    def scan_children(directory: Path) -> list[DirChild]:
        children: list[DirChild] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    try:
                        entry_path = Path(entry.path)
                        is_dir = entry.is_dir(follow_symlinks=True)
                        is_file = entry.is_file(follow_symlinks=True)
                        season_num = get_season(entry_path) if is_dir else None
                        children.append(
                            DirChild(
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