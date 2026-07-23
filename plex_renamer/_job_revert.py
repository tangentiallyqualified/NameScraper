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
