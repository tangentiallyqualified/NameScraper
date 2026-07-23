"""Per-job rollback orchestration and filesystem helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .job_store import RenameJob


@dataclass(slots=True)
class RevertContext:
    job: RenameJob
    undo: dict[str, Any]
    library_root: Path
    source_boundary: Path
    output_boundary: Path | None
    cleanup_boundary: Path
    errors: list[str] = field(default_factory=list[str])
    moved_from_paths: list[Path] = field(default_factory=list[Path])
    dir_rename_map: dict[Path, Path] = field(default_factory=dict[Path, Path])


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


def remap_after_directory_revert(path: Path, mapping: dict[Path, Path]) -> Path:
    for renamed_new, renamed_old in mapping.items():
        try:
            return renamed_old / path.relative_to(renamed_new)
        except ValueError:
            continue
    return path


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


def restore_files(context: RevertContext) -> None:
    for entry in reversed(context.undo.get("renames", [])):
        new_path = Path(entry["new"])
        old_path = Path(entry["old"])

        for renamed_new, renamed_old in context.dir_rename_map.items():
            mapping = {renamed_new: renamed_old}
            new_path = remap_after_directory_revert(new_path, mapping)
            old_path = remap_after_directory_revert(old_path, mapping)

        if context.output_boundary is not None:
            path_errors = destination_path_errors(
                new_path=new_path,
                old_path=old_path,
                output_boundary=context.output_boundary,
                source_boundary=context.source_boundary,
            )
            if path_errors:
                context.errors.extend(path_errors)
                continue

        try:
            old_path.parent.mkdir(parents=True, exist_ok=True)
            if new_path.exists():
                if new_path.parent != old_path.parent:
                    shutil.move(str(new_path), str(old_path))
                else:
                    new_path.rename(old_path)
                context.moved_from_paths.append(new_path)
            else:
                context.errors.append(f"File not found: {new_path.name}")
        except (OSError, shutil.Error) as e:
            context.errors.append(f"{new_path.name}: {e}")


def _cleanup_empty_output_dirs(
    *,
    output_root: Path,
    created_dirs: list[str],
    moved_from_paths: list[Path],
) -> None:
    boundary = output_root.resolve()
    candidates = {Path(path) for path in created_dirs}
    candidates.update(path.parent for path in moved_from_paths)

    for candidate in sorted(
        candidates,
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        _remove_empty_directory_chain(candidate, boundary)


def _remove_empty_directory_chain(candidate: Path, boundary: Path) -> None:
    current = candidate
    while True:
        try:
            resolved = current.resolve()
        except OSError:
            break
        if resolved == boundary:
            break
        if not resolved.is_relative_to(boundary):
            break
        try:
            if current.exists() and not any(current.iterdir()):
                current.rmdir()
                current = current.parent
                continue
        except OSError:
            pass
        break


def cleanup_reverted_tree(context: RevertContext) -> None:
    if context.job.output_root:
        _cleanup_empty_output_dirs(
            output_root=Path(context.job.output_root),
            created_dirs=list(context.undo.get("created_dirs", [])),
            moved_from_paths=context.moved_from_paths,
        )
        return

    _cleanup_empty_output_dirs(
        output_root=context.cleanup_boundary,
        created_dirs=list(context.undo.get("created_dirs", [])),
        moved_from_paths=context.moved_from_paths,
    )


def revert_job(job: RenameJob) -> tuple[bool, list[str]]:
    """Revert a single completed job using its stored undo data."""
    undo = cast(dict[str, Any] | None, cast(Any, job).undo_data)
    if not undo:
        return False, ["No undo data stored for this job."]

    if undo.get("irreversible"):
        return False, ["This job replaced its source files (No Fear mode) and cannot be reverted."]

    library_root = Path(job.library_root)
    source_folder = Path(job.source_folder)
    source_boundary = library_root.resolve(strict=False)
    try:
        cleanup_boundary = (library_root / source_folder.parent).resolve(strict=False)
        cleanup_boundary.relative_to(source_boundary)
    except (OSError, ValueError):
        cleanup_boundary = source_boundary
    output_path = job.output_path
    output_boundary = output_path.resolve(strict=False) if output_path else source_boundary
    context = RevertContext(
        job=job,
        undo=undo,
        library_root=library_root,
        source_boundary=source_boundary,
        output_boundary=output_boundary,
        cleanup_boundary=cleanup_boundary,
    )

    remove_generated_outputs(context)
    restore_directories(context)
    restore_files(context)
    cleanup_reverted_tree(context)

    return len(context.errors) == 0, context.errors
