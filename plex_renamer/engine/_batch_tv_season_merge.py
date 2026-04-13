"""Season-merge helpers for batch TV orchestration."""

from __future__ import annotations

from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import get_season
from ._batch_tv_duplicates import normalized_relative_folder
from .models import ScanState


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


def expanded_season_folders(state: ScanState) -> dict[int, Path]:
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


def merge_season_siblings(states: list[ScanState]) -> list[ScanState]:
    """Merge states that share a TMDB ID and have distinct season assignments."""
    groups: dict[int, list[ScanState]] = {}
    rest: list[ScanState] = []
    for state in states:
        show_id = state.show_id
        if show_id is None or state.season_assignment is None:
            rest.append(state)
            continue
        groups.setdefault(show_id, []).append(state)

    merged: list[ScanState] = list(rest)
    for group in groups.values():
        if len(group) < 2:
            merged.extend(group)
            continue

        assignments = {state.season_assignment for state in group}
        if len(assignments) < len(group):
            merged.extend(group)
            continue

        group.sort(key=lambda state: (-state.confidence, state.display_name.lower()))
        primary = group[0]

        season_map: dict[int, Path] = {}
        total_files = primary.direct_video_file_count
        total_episode_files = primary.direct_episode_file_count
        for state in group:
            if state.season_assignment is not None:
                season_map[state.season_assignment] = resolve_season_folder(
                    state.folder,
                    state.season_assignment,
                )
            if state is primary:
                continue
            total_files += state.direct_video_file_count
            total_episode_files += state.direct_episode_file_count
            for season_num, name in state.season_names.items():
                primary.season_names.setdefault(season_num, name)

        primary.season_folders = season_map
        primary.season_assignment = None
        primary.direct_video_file_count = total_files
        primary.direct_episode_file_count = total_episode_files
        merged.append(primary)

    return merged