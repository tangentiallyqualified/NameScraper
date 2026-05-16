"""Season-merge helpers for batch TV orchestration."""

from __future__ import annotations

from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import extract_episode, extract_season_number, get_season
from ._batch_tv_duplicates import normalized_relative_folder
from .models import ScanState, SeasonFolderEntry, iter_season_folder_paths


def preview_single_season(state: ScanState) -> int | None:
    """Return the one season covered by ``preview_items``, or ``None``."""
    if not state.preview_items:
        return None
    detected = {
        item.season for item in state.preview_items
        if item.season is not None
    }
    if len(detected) != 1:
        return None
    return next(iter(detected))


def resolve_season_folder(folder: Path, season_num: int) -> Path:
    """Return the actual directory containing episode files."""
    has_video = any(
        file.suffix.lower() in VIDEO_EXTENSIONS
        for file in folder.iterdir() if file.is_file()
    )
    if has_video:
        return folder
    for child in folder.iterdir():
        if child.is_dir() and get_season(child) == season_num:
            return child
    return folder


def represented_seasons(state: ScanState) -> set[int]:
    seasons = set(state.season_folders.keys())
    if state.season_assignment is not None:
        seasons.add(state.season_assignment)
    if not seasons:
        inferred = preview_single_season(state)
        if inferred is not None:
            seasons.add(inferred)
    return seasons


def expanded_season_folders(state: ScanState) -> dict[int, SeasonFolderEntry]:
    if state.season_folders:
        return dict(state.season_folders)
    if state.season_assignment is not None:
        return {
            state.season_assignment: resolve_season_folder(
                state.folder,
                state.season_assignment,
            )
        }
    inferred = preview_single_season(state)
    if inferred is not None:
        return {
            inferred: resolve_season_folder(state.folder, inferred),
        }
    return {}


def season_merge_priority(state: ScanState) -> tuple[int, float, int, str]:
    represented = represented_seasons(state)
    normalized_relative = normalized_relative_folder(
        state.relative_folder,
        state.folder,
    )
    manual_rank = 0 if state.match_origin == "manual" else 1
    return (
        len(represented),
        state.confidence,
        -manual_rank,
        normalized_relative,
    )


def _season_representative_priority(state: ScanState) -> tuple[int, int, float, str]:
    """Prefer fuller folders when multiple candidates cover the same season."""
    return (
        state.direct_episode_file_count,
        state.direct_video_file_count,
        state.confidence,
        normalized_relative_folder(state.relative_folder, state.folder),
    )


def _episode_keys_for_season_folder(folder: Path, season_num: int) -> set[tuple[int, int]]:
    """Return concrete episode keys represented by direct video files in *folder*."""
    keys: set[tuple[int, int]] = set()
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return keys

    for entry in entries:
        if not entry.is_file() or entry.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        episode_numbers, _raw_title, is_season_relative = extract_episode(entry.name)
        if not episode_numbers:
            continue
        file_season = extract_season_number(entry.name) if is_season_relative else None
        effective_season = file_season if file_season is not None else season_num
        if effective_season != season_num:
            continue
        keys.update((season_num, episode_num) for episode_num in episode_numbers)
    return keys


def _can_merge_disjoint_season_folder(
    existing_folders: list[Path],
    candidate_folder: Path,
    season_num: int,
) -> bool:
    existing_keys: set[tuple[int, int]] = set()
    for folder in existing_folders:
        existing_keys.update(_episode_keys_for_season_folder(folder, season_num))
    candidate_keys = _episode_keys_for_season_folder(candidate_folder, season_num)
    return bool(existing_keys) and bool(candidate_keys) and existing_keys.isdisjoint(candidate_keys)


def _combine_folder_entries(folders: list[Path]) -> SeasonFolderEntry:
    unique: list[Path] = []
    seen: set[str] = set()
    for folder in folders:
        key = folder.as_posix().casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(folder)
    if len(unique) == 1:
        return unique[0]
    return tuple(unique)


def _merge_same_season_members(
    members: list[ScanState],
    season_num: int,
) -> tuple[ScanState, list[ScanState]]:
    ordered = sorted(members, key=_season_representative_priority, reverse=True)
    representative = ordered[0]
    representative_folders = [
        resolve_season_folder(representative.folder, season_num)
    ]
    total_files = representative.direct_video_file_count
    total_episode_files = representative.direct_episode_file_count
    duplicate_siblings: list[ScanState] = []

    for sibling in ordered[1:]:
        sibling_folder = resolve_season_folder(sibling.folder, season_num)
        if _can_merge_disjoint_season_folder(
            representative_folders,
            sibling_folder,
            season_num,
        ):
            representative_folders.append(sibling_folder)
            total_files += sibling.direct_video_file_count
            total_episode_files += sibling.direct_episode_file_count
            for named_season, name in sibling.season_names.items():
                representative.season_names.setdefault(named_season, name)
            continue
        duplicate_siblings.append(sibling)

    if len(representative_folders) > 1:
        representative.season_folders = {
            season_num: _combine_folder_entries(representative_folders),
        }
        representative.direct_video_file_count = total_files
        representative.direct_episode_file_count = total_episode_files

    return representative, duplicate_siblings


def _enumerate_direct_season_subdirs(folder: Path) -> dict[int, Path]:
    """Return ``{season_num: subdir}`` for all season-named children of *folder*."""
    result: dict[int, Path] = {}
    try:
        for child in folder.iterdir():
            if not child.is_dir():
                continue
            season_num = get_season(child)
            if season_num is None:
                continue
            result.setdefault(season_num, child)
    except OSError:
        pass
    return result


def merge_season_siblings(states: list[ScanState]) -> list[ScanState]:
    """Merge states that share a TMDB ID and have distinct season assignments."""
    groups: dict[int, dict[int, list[ScanState]]] = {}
    rest: list[ScanState] = []
    for state in states:
        show_id = state.show_id
        if show_id is None or state.season_assignment is None:
            rest.append(state)
            continue
        groups.setdefault(show_id, {}).setdefault(state.season_assignment, []).append(state)

    merged: list[ScanState] = list(rest)
    for season_groups in groups.values():
        representatives: list[ScanState] = []
        duplicate_season_siblings: list[ScanState] = []
        for season_num, members in season_groups.items():
            if len(members) == 1:
                representatives.append(members[0])
                continue
            representative, duplicates = _merge_same_season_members(members, season_num)
            representatives.append(representative)
            duplicate_season_siblings.extend(duplicates)

        if len(representatives) < 2:
            merged.extend(representatives)
            merged.extend(duplicate_season_siblings)
            continue

        representatives.sort(key=lambda state: (-state.confidence, state.display_name.lower()))
        primary = representatives[0]

        season_map: dict[int, SeasonFolderEntry] = {}
        total_files = 0
        total_episode_files = 0
        for state in representatives:
            for season_num, folder_entry in expanded_season_folders(state).items():
                if season_num in season_map:
                    existing = list(iter_season_folder_paths(season_map[season_num]))
                    existing.extend(iter_season_folder_paths(folder_entry))
                    season_map[season_num] = _combine_folder_entries(existing)
                else:
                    season_map[season_num] = folder_entry
            total_files += state.direct_video_file_count
            total_episode_files += state.direct_episode_file_count
            if state is primary:
                continue
            for season_num, name in state.season_names.items():
                primary.season_names.setdefault(season_num, name)

        primary.season_folders = season_map
        primary.season_assignment = None
        primary.direct_video_file_count = total_files
        primary.direct_episode_file_count = total_episode_files
        merged.append(primary)
        merged.extend(duplicate_season_siblings)

    return merged


def merge_umbrella_siblings(states: list[ScanState]) -> list[ScanState]:
    """Absorb explicit-season sibling folders into a same-show multi-season state.

    When a library contains both a parent show folder with per-season
    subdirectories (e.g. ``Family Guy (1999)/Season 01``, ``Season 02``…) and
    a standalone release folder for a single season (e.g. ``Family Guy (1999)
    - Season 23 [WEBDL]``), both match the same TMDB show.  The sibling covers
    a season that the umbrella does not, so it is absorbed into the umbrella's
    ``season_folders`` map and dropped from the output so the GUI shows one
    card for the whole series.

    Siblings whose season is already represented under the umbrella are left
    in place so the duplicate labeler can flag them as true duplicates.
    """
    groups: dict[int, list[ScanState]] = {}
    for state in states:
        show_id = state.show_id
        if show_id is None:
            continue
        groups.setdefault(show_id, []).append(state)

    removed: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        umbrellas = [
            state for state in group
            if state.season_assignment is None and state.has_direct_season_subdirs
        ]
        explicit = [state for state in group if state.season_assignment is not None]
        if not umbrellas or not explicit:
            continue

        umbrellas.sort(key=lambda state: (-state.confidence, state.display_name.lower()))
        primary = umbrellas[0]
        primary_subdirs = dict(primary.season_folders) if primary.season_folders else {}
        if not primary_subdirs:
            primary_subdirs = _enumerate_direct_season_subdirs(primary.folder)

        for sibling in explicit:
            season_num = sibling.season_assignment
            if season_num is None or season_num in primary_subdirs:
                continue
            primary_subdirs[season_num] = resolve_season_folder(
                sibling.folder,
                season_num,
            )
            for named_season, name in sibling.season_names.items():
                primary.season_names.setdefault(named_season, name)
            primary.direct_video_file_count += sibling.direct_video_file_count
            primary.direct_episode_file_count += sibling.direct_episode_file_count
            removed.add(id(sibling))

        if primary_subdirs:
            primary.season_folders = primary_subdirs
            primary.season_assignment = None

    return [state for state in states if id(state) not in removed]
