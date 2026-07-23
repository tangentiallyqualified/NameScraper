"""Shared context and boundary validation for per-job rollback."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .job_store import RenameJob


@dataclass(slots=True)
class RevertContext:
    job: RenameJob
    undo: dict[str, Any]
    library_root: Path
    source_boundary: Path
    output_boundary: Path | None
    cleanup_boundary: Path
    errors: list[str] = field(default_factory=list)
    moved_from_paths: list[Path] = field(default_factory=list)
    dir_rename_map: dict[Path, Path] = field(default_factory=dict)


def destination_path_errors(
    *,
    new_path: Path,
    old_path: Path,
    output_boundary: Path,
    source_boundary: Path,
) -> list[str]:
    errors: list[str] = []
    try:
        new_path.resolve(strict=False).relative_to(output_boundary)
    except (OSError, ValueError):
        errors.append(f"Revert source is outside the output root: {new_path}")

    try:
        old_path.resolve(strict=False).relative_to(source_boundary)
    except (OSError, ValueError):
        errors.append(f"Revert target is outside the source root: {old_path}")

    return errors


def _remove_paths(
    context: RevertContext,
    paths: list[str],
    *,
    outside_message: str,
    failure_label: str,
) -> None:
    for path_str in paths:
        path = Path(path_str)
        if context.output_boundary is not None:
            try:
                path.resolve(strict=False).relative_to(context.output_boundary)
            except (OSError, ValueError):
                context.errors.append(f"{outside_message}: {path}")
                continue
        try:
            if path.exists():
                path.unlink()
                context.moved_from_paths.append(path)
        except OSError as e:
            context.errors.append(f"{failure_label} {path.name}: {e}")


def remove_generated_outputs(context: RevertContext) -> None:
    _remove_paths(
        context,
        context.undo.get("remux_outputs", []),
        outside_message="Remux output is outside the output root",
        failure_label="Could not remove remux output",
    )
    _remove_paths(
        context,
        context.undo.get("created_files", []),
        outside_message="Created file is outside the output root",
        failure_label="Could not remove metadata file",
    )


def restore_directories(context: RevertContext) -> None:
    for entry in reversed(context.undo.get("renamed_dirs", [])):
        new_dir = Path(entry["new"])
        old_dir = Path(entry["old"])
        if context.output_boundary is not None:
            path_errors = destination_path_errors(
                new_path=new_dir,
                old_path=old_dir,
                output_boundary=context.output_boundary,
                source_boundary=context.source_boundary,
            )
            if path_errors:
                context.errors.extend(path_errors)
                continue
        try:
            if new_dir.exists():
                new_dir.rename(old_dir)
                context.dir_rename_map[new_dir] = old_dir
        except OSError as e:
            context.errors.append(f"Could not revert folder {new_dir.name}: {e}")

    for dir_path_str in context.undo.get("removed_dirs", []):
        dir_path = Path(dir_path_str)
        if context.output_boundary is not None:
            try:
                dir_path.resolve(strict=False).relative_to(context.source_boundary)
            except (OSError, ValueError):
                context.errors.append(f"Removed directory is outside the source root: {dir_path}")
                continue
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            context.errors.append(f"Could not recreate folder {dir_path.name}: {e}")
