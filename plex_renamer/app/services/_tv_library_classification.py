"""Folder-classification helpers for recursive TV library discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ...constants import VIDEO_EXTENSIONS
from ...parsing import (
    clean_folder_name,
    get_season,
    is_extras_folder,
    is_season_only_name,
    looks_like_tv_episode,
)
from ..models import TVDirectoryRole


@dataclass(slots=True)
class DirChild:
    path: Path
    is_dir: bool
    is_file: bool
    is_symlink: bool
    season_num: int | None = None


@dataclass(slots=True)
class ClassifiedDirectory:
    role: TVDirectoryRole
    child_dirs: list[Path]
    discovery_reason: str
    has_direct_season_subdirs: bool
    direct_episode_file_count: int
    direct_video_file_count: int
    discovered_via_symlink: bool


class TVDirectoryClassifier:
    """Encapsulate TV folder classification heuristics."""

    def __init__(self, ignored_system_names: set[str]):
        self.ignored_system_names = ignored_system_names

    def classify_directory(self, directory: Path) -> ClassifiedDirectory:
        name_cf = directory.name.casefold()
        if name_cf in self.ignored_system_names:
            return ClassifiedDirectory(
                role=TVDirectoryRole.IGNORED_SYSTEM,
                child_dirs=[],
                discovery_reason="ignored_system_name",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=0,
                discovered_via_symlink=directory.is_symlink(),
            )
        if is_extras_folder(directory.name):
            return ClassifiedDirectory(
                role=TVDirectoryRole.NON_TV_LEAF,
                child_dirs=[],
                discovery_reason="extras_folder",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=0,
                discovered_via_symlink=directory.is_symlink(),
            )

        season_num = get_season(directory)
        if season_num is not None:
            child_entries = self.scan_children(directory)
            has_direct_video_files = any(
                child.is_file and child.path.suffix.lower() in VIDEO_EXTENSIONS
                for child in child_entries
            )
            has_direct_episodes = any(
                child.is_file
                and child.path.suffix.lower() in VIDEO_EXTENSIONS
                and looks_like_tv_episode(child.path)
                for child in child_entries
            )
            has_non_extras_child_dirs = any(
                child.is_dir
                and child.path.name.casefold() not in self.ignored_system_names
                and not is_extras_folder(child.path.name)
                for child in child_entries
            )
            if season_num == 0 and has_direct_video_files:
                pass
            elif not has_direct_episodes and not has_non_extras_child_dirs:
                return ClassifiedDirectory(
                    role=TVDirectoryRole.SEASON_FOLDER,
                    child_dirs=[],
                    discovery_reason="season_folder_name",
                    has_direct_season_subdirs=False,
                    direct_episode_file_count=0,
                    direct_video_file_count=0,
                    discovered_via_symlink=directory.is_symlink(),
                )
        else:
            child_entries = self.scan_children(directory)

        child_dirs: list[Path] = []
        specials_dirs: list[Path] = []
        direct_video_files: list[Path] = []
        has_direct_season_subdirs = False
        has_regular_season_subdirs = False

        for child in child_entries:
            if child.is_dir:
                if child.path.name.casefold() in self.ignored_system_names:
                    continue
                if self.counts_as_season_subdir(child):
                    has_direct_season_subdirs = True
                    if child.season_num == 0:
                        specials_dirs.append(child.path)
                    else:
                        has_regular_season_subdirs = True
                else:
                    child_dirs.append(child.path)
                continue

            if child.is_file and child.path.suffix.lower() in VIDEO_EXTENSIONS:
                direct_video_files.append(child.path)

        direct_episode_file_count = sum(
            1 for video_path in direct_video_files
            if looks_like_tv_episode(video_path)
        )

        if has_regular_season_subdirs or (specials_dirs and direct_episode_file_count > 0):
            return ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="direct_season_subdirs",
                has_direct_season_subdirs=True,
                direct_episode_file_count=direct_episode_file_count,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if direct_episode_file_count > 0:
            return ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="direct_episode_files",
                has_direct_season_subdirs=False,
                direct_episode_file_count=direct_episode_file_count,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if season_num == 0 and direct_video_files:
            return ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="specials_video_files",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if len(direct_video_files) > 2:
            return ClassifiedDirectory(
                role=TVDirectoryRole.SHOW_ROOT,
                child_dirs=[],
                discovery_reason="multiple_direct_video_files",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        if specials_dirs and not has_regular_season_subdirs and direct_episode_file_count == 0:
            child_dirs = [*child_dirs, *specials_dirs]

        if child_dirs:
            return ClassifiedDirectory(
                role=TVDirectoryRole.CONTAINER,
                child_dirs=child_dirs,
                discovery_reason="container_children",
                has_direct_season_subdirs=False,
                direct_episode_file_count=0,
                direct_video_file_count=len(direct_video_files),
                discovered_via_symlink=directory.is_symlink(),
            )

        return ClassifiedDirectory(
            role=TVDirectoryRole.NON_TV_LEAF,
            child_dirs=[],
            discovery_reason="non_tv_leaf",
            has_direct_season_subdirs=False,
            direct_episode_file_count=direct_episode_file_count,
            direct_video_file_count=len(direct_video_files),
            discovered_via_symlink=directory.is_symlink(),
        )

    def counts_as_season_subdir(self, child: DirChild) -> bool:
        if not child.is_dir or child.season_num is None:
            return False

        child_entries = self.scan_children(child.path)
        if not child_entries:
            return False

        has_direct_episodes = any(
            grandchild.is_file
            and grandchild.path.suffix.lower() in VIDEO_EXTENSIONS
            and looks_like_tv_episode(grandchild.path)
            for grandchild in child_entries
        )
        if has_direct_episodes:
            return True

        has_nested_non_extras_dirs = any(
            grandchild.is_dir
            and grandchild.path.name.casefold() not in self.ignored_system_names
            and not is_extras_folder(grandchild.path.name)
            for grandchild in child_entries
        )
        return not has_nested_non_extras_dirs

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

    def season_children_are_majority(self, directory: Path) -> bool:
        parent_title = clean_folder_name(directory.name, include_year=False).casefold()
        children = self.scan_children(directory)
        season_count = 0
        non_season_count = 0
        for child in children:
            if not child.is_dir:
                continue
            if child.path.name.casefold() in self.ignored_system_names:
                continue
            if is_extras_folder(child.path.name):
                continue
            season_num = get_season(child.path)
            if season_num is not None and season_num == 0:
                continue
            if season_num is not None and season_num >= 1:
                if is_season_only_name(child.path.name):
                    season_count += 1
                elif self.child_title_matches_parent(child.path.name, parent_title):
                    season_count += 1
                else:
                    non_season_count += 1
            else:
                non_season_count += 1
        total = season_count + non_season_count
        if total == 0:
            return False
        return season_count > total / 2

    @staticmethod
    def child_title_matches_parent(child_name: str, parent_title_cf: str) -> bool:
        if not parent_title_cf:
            return False
        child_title = clean_folder_name(child_name, include_year=False).casefold()
        return child_title == parent_title_cf or child_title.startswith(parent_title_cf)
