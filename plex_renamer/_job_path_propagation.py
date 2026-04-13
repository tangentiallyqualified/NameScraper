"""Helpers for rewriting queued job paths after directory renames."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def rewrite_job_paths(
    *,
    library_root: str,
    source_folder: str,
    rename_ops: list[dict[str, Any]],
    renamed_dirs: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]], bool]:
    """Apply renamed directory prefixes to one queued job payload."""
    updated_source_folder = source_folder
    updated_ops = [dict(op) for op in rename_ops]
    changed = False

    for dir_rename in renamed_dirs:
        old_dir = dir_rename["old"]
        new_dir = dir_rename["new"]

        rebased_source = _rebase_job_path(
            library_root=library_root,
            path_str=updated_source_folder,
            old_prefix=old_dir,
            new_prefix=new_dir,
        )
        if rebased_source != updated_source_folder:
            updated_source_folder = rebased_source
            changed = True

        for op in updated_ops:
            rebased_original = _rebase_job_path(
                library_root=library_root,
                path_str=op["original_relative"],
                old_prefix=old_dir,
                new_prefix=new_dir,
            )
            if rebased_original != op["original_relative"]:
                op["original_relative"] = rebased_original
                changed = True

            rebased_target = _rebase_job_path(
                library_root=library_root,
                path_str=op["target_dir_relative"],
                old_prefix=old_dir,
                new_prefix=new_dir,
            )
            if rebased_target != op["target_dir_relative"]:
                op["target_dir_relative"] = rebased_target
                changed = True

    return updated_source_folder, updated_ops, changed


def _rebase_job_path(
    *,
    library_root: str,
    path_str: str,
    old_prefix: str,
    new_prefix: str,
) -> str:
    absolute_path = str(Path(library_root) / path_str)
    rebased_path = rebase_path(absolute_path, old_prefix, new_prefix)
    if rebased_path == absolute_path:
        return path_str
    try:
        return str(Path(rebased_path).relative_to(library_root))
    except ValueError:
        return rebased_path


def rebase_path(path_str: str, old_prefix: str, new_prefix: str) -> str:
    """If *path_str* starts with *old_prefix*, replace that prefix."""
    norm_path = path_str.replace("\\", "/")
    norm_old = old_prefix.replace("\\", "/")
    if norm_path == norm_old:
        return new_prefix
    if norm_path.startswith(norm_old + "/"):
        return new_prefix + path_str[len(old_prefix):]
    return path_str
