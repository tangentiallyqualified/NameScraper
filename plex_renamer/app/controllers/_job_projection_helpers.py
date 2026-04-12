"""Helpers for completed-job projection and queued-state syncing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ...constants import MediaType
from ...engine import CompanionFile, PreviewItem, ScanState


@dataclass(frozen=True, slots=True)
class CompletedJobProjection:
    changed: bool
    movie_preview_items: list[PreviewItem] | None = None


def apply_completed_job_projection(
    job: Any,
    states: list[ScanState],
    movie_preview_items: list[PreviewItem],
) -> CompletedJobProjection:
    if not states or not job.tmdb_id:
        return CompletedJobProjection(False)

    state = _find_state_for_job(states, job)
    if state is None:
        return CompletedJobProjection(False)

    library_root = Path(job.library_root)
    preview_lookup: dict[str, PreviewItem] = {}
    for preview in state.preview_items:
        key = _normalized_preview_relative(preview, library_root)
        if key:
            preview_lookup[key] = preview

    companion_lookup: dict[str, CompanionFile] = {}
    for preview in state.preview_items:
        for companion in preview.companions:
            key = _normalized_relative_path(companion.original, library_root)
            if key:
                companion_lookup[key] = companion

    changed = False
    for op in job.rename_ops:
        if not op.selected:
            continue
        final_dir_relative = _final_target_dir_relative(job, op)
        final_dir = library_root / Path(final_dir_relative)
        final_path = final_dir / op.new_name
        normalized_original = _normalized_relative_string(op.original_relative)

        if op.file_type == "video":
            preview = preview_lookup.get(normalized_original)
            if preview is None and len(state.preview_items) == 1:
                preview = state.preview_items[0]
            if preview is None:
                continue
            preview.original = final_path
            preview.new_name = op.new_name
            preview.target_dir = final_dir
            preview.status = "OK"
            changed = True
        else:
            companion = companion_lookup.get(normalized_original)
            if companion is None:
                continue
            companion.original = final_path
            companion.new_name = op.new_name
            changed = True

    if not changed:
        return CompletedJobProjection(False)

    root_relative = _job_completed_root_relative(job)
    if root_relative is not None:
        state.folder = library_root / Path(root_relative)
        state.relative_folder = root_relative
        parent_relative = PurePosixPath(root_relative).parent
        state.parent_relative_folder = None if str(parent_relative) in {"", "."} else parent_relative.as_posix()

    season_folders: dict[int, Path] = {}
    for preview in state.preview_items:
        if preview.season is None or preview.target_dir is None:
            continue
        season_folders[preview.season] = preview.target_dir
    state.season_folders = season_folders
    state.scanned = True
    state.scanning = False
    state.queued = False
    state.checked = False
    state.reset_gui_state()
    state.selected_index = 0 if state.preview_items else None

    updated_movie_preview_items: list[PreviewItem] | None = None
    if job.media_type == MediaType.MOVIE:
        updated_movie_preview_items = [
            state.preview_items[0] if item.media_id == job.tmdb_id else item
            for item in movie_preview_items
        ]

    return CompletedJobProjection(True, updated_movie_preview_items)


def sync_queued_state_flags(
    queue_jobs: list[Any],
    tv_states: list[ScanState],
    movie_states: list[ScanState],
) -> None:
    queued_keys = {
        (job.media_type, job.tmdb_id)
        for job in queue_jobs
        if job.tmdb_id
    }

    _sync_state_group(tv_states, MediaType.TV, queued_keys)
    _sync_state_group(movie_states, MediaType.MOVIE, queued_keys)


def _normalized_relative_string(value: str) -> str:
    text = value.replace("\\", "/") if value else ""
    normalized = PurePosixPath(text)
    return "" if str(normalized) == "." else normalized.as_posix()


def _normalized_relative_path(path: Path, library_root: Path) -> str:
    try:
        relative = path.relative_to(library_root)
    except ValueError:
        return _normalized_relative_string(str(path))
    return _normalized_relative_string(relative.as_posix())


def _normalized_preview_relative(preview: PreviewItem, library_root: Path) -> str:
    return _normalized_relative_path(preview.original, library_root)


def _find_state_for_job(states: list[ScanState], job: Any) -> ScanState | None:
    candidates = [
        state
        for state in states
        if state.show_id == job.tmdb_id and state.duplicate_of is None
    ]
    if not candidates:
        return None

    job_source = _normalized_relative_string(job.source_folder)
    library_root = Path(job.library_root)
    for state in candidates:
        state_source = state.relative_folder
        if not state_source:
            try:
                state_source = str(state.folder.relative_to(library_root))
            except ValueError:
                state_source = state.folder.name
        if _normalized_relative_string(state_source) == job_source:
            return state
    return candidates[0]


def _job_completed_root_relative(job: Any) -> str | None:
    selected_video_ops = [op for op in job.video_ops if op.selected]
    if not selected_video_ops:
        return None

    source_folder = _normalized_relative_string(job.source_folder)
    if job.show_folder_rename and source_folder not in {"", "."}:
        source_path = PurePosixPath(source_folder)
        parent = source_path.parent
        base = PurePosixPath(job.show_folder_rename)
        if str(parent) in {"", "."}:
            return base.as_posix()
        return (parent / base).as_posix()

    root_path = PurePosixPath(_final_target_dir_relative(job, selected_video_ops[0]))
    parts = root_path.parts
    if not parts:
        return None
    if job.media_type == MediaType.MOVIE:
        return root_path.as_posix()
    if len(parts) >= 2 and parts[-1].lower().startswith("season "):
        return PurePosixPath(*parts[:-1]).as_posix()
    return root_path.as_posix()


def _final_target_dir_relative(job: Any, op: Any) -> str:
    target_dir = PurePosixPath(_normalized_relative_string(op.target_dir_relative) or ".")
    source_folder = _normalized_relative_string(job.source_folder)
    if not job.show_folder_rename or source_folder in {"", "."}:
        return target_dir.as_posix()

    source_parts = PurePosixPath(source_folder).parts
    target_parts = target_dir.parts
    if len(target_parts) >= len(source_parts) and tuple(target_parts[: len(source_parts)]) == source_parts:
        replacement = (*source_parts[:-1], job.show_folder_rename, *target_parts[len(source_parts):])
        return PurePosixPath(*replacement).as_posix()
    return target_dir.as_posix()


def _sync_state_group(
    states: list[ScanState],
    media_type: MediaType,
    queued_keys: set[tuple[MediaType, int]],
) -> None:
    for state in states:
        if state.duplicate_of is not None:
            state.queued = False
            continue
        state.queued = (media_type, state.show_id or 0) in queued_keys