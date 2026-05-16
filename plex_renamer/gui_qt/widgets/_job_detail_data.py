"""Formatting and path helpers for JobDetailPanel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ...constants import JobStatus
from ...job_store import RenameJob


def build_job_summary(job: RenameJob) -> str:
    companion = len(job.companion_ops)
    parts: list[str] = []
    if companion:
        parts.append(f"{companion} companion file(s)")
    if job.depends_on:
        parts.append(f"Depends on {job.depends_on[:8]}...")
    if job.status == JobStatus.REVERTED:
        parts.append("Reverted")
    elif job.status == JobStatus.REVERT_FAILED:
        parts.append("Revert Failed")
    return " · ".join(parts)


def build_job_meta_line(job: RenameJob, *, history_mode: bool) -> str:
    primary_label = "Updated" if history_mode else "Queued"
    primary_value = job.updated_at if history_mode else job.created_at
    return f"{primary_label} {format_job_timestamp(primary_value)}"


def format_job_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%b %d, %H:%M")
    except (TypeError, ValueError):
        return value[:16] if value else ""


def build_job_fact_values(job: RenameJob) -> dict[str, str]:
    companions = len(job.companion_ops)
    files_text = f"{job.selected_count} selected"
    companions_text = str(companions) if companions else "None"
    return {
        "media": {"tv": "TV Show", "movie": "Movie"}.get(job.media_type, job.media_type.title()),
        "action": job.job_kind.title(),
        "files": files_text,
        "companions": companions_text,
    }


def folder_preview_data(job: RenameJob) -> tuple[str, str] | None:
    if job.show_folder_rename:
        source_name = folder_preview_source_name(job, include_media_name=True)
        if source_name:
            return source_name, job.show_folder_rename
        return None

    if job.media_type != "movie":
        return None

    source_name = folder_preview_source_name(job, include_media_name=False)
    target_name = movie_target_folder_name(job)
    if not source_name or not target_name or source_name == target_name:
        return None
    return source_name, target_name


def folder_preview_source_name(
    job: RenameJob,
    *,
    include_media_name: bool = True,
) -> str | None:
    source_name = Path(job.source_folder).name or job.source_folder
    if source_name and source_name != ".":
        return source_name

    ops = job.selected_ops or job.rename_ops
    for op in ops:
        parent = Path(op.original_relative).parent
        parts = [part for part in parent.parts if part not in {"", "."}]
        if parts:
            return parts[0]

    library_root_name = Path(job.library_root).name
    if library_root_name:
        return library_root_name

    if include_media_name and job.media_name:
        return job.media_name
    return None


def movie_target_folder_name(job: RenameJob) -> str | None:
    ops = job.selected_ops or job.rename_ops
    candidate_ops = [op for op in ops if op.file_type == "video"] or ops
    target_names: set[str] = set()
    for op in candidate_ops:
        parts = [part for part in Path(op.target_dir_relative).parts if part not in {"", "."}]
        if parts:
            target_names.add(parts[0])
    if len(target_names) != 1:
        return None
    return next(iter(target_names))


def target_paths(job: RenameJob) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    ops = job.selected_ops or job.rename_ops
    for op in ops:
        target = Path(job.library_root) / final_target_dir_relative(job, op)
        if target not in seen:
            seen.add(target)
            paths.append(target)
    if not paths and job.show_folder_rename:
        source_folder = Path(job.source_folder)
        if job.source_folder in ("", "."):
            fallback = Path(job.library_root) / job.show_folder_rename
        else:
            fallback = Path(job.library_root) / source_folder.parent / job.show_folder_rename
        paths.append(fallback)
    return paths


def primary_target_path(job: RenameJob) -> Path | None:
    targets = target_paths(job)
    if not targets:
        return None
    return targets[0]


def final_target_dir_relative(job: RenameJob, op: Any) -> Path:
    target_dir = Path(op.target_dir_relative)
    if not job.show_folder_rename or job.source_folder in ("", "."):
        return target_dir
    source_parts = Path(job.source_folder).parts
    target_parts = target_dir.parts
    if len(target_parts) >= len(source_parts) and tuple(target_parts[: len(source_parts)]) == source_parts:
        replacement = (*source_parts[:-1], job.show_folder_rename, *target_parts[len(source_parts):])
        return Path(*replacement)
    return target_dir


def resolve_openable_path(path: Path | None) -> Path | None:
    candidate = path
    while candidate is not None:
        if candidate.exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return None
