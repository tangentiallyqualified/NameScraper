"""Rename execution helpers shared by the direct-rename and queue flows.

These functions operate on preview items and filesystem paths without
depending on the scanning/orchestration classes in ``_core``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..parsing import get_season
from .models import PreviewItem, RenameResult


def check_duplicates(items: list[PreviewItem]) -> None:
    """Flag items that would collide on the same target path."""
    seen: dict[tuple[str, str], str] = {}
    for item in items:
        if item.new_name is None:
            continue
        target_dir = item.target_dir or item.original.parent
        key = (str(target_dir).lower(), item.new_name.lower())
        if key in seen:
            item.status = f"CONFLICT: same target as {seen[key]}"
        else:
            seen[key] = item.original.name


def execute_rename(
    items: list[PreviewItem],
    checked_indices: set[int],
    show_name: str,
    root_folder: Path,
    show_folder_name: str | None = None,
) -> RenameResult:
    """Perform the actual file renames and moves for checked preview items."""
    result = RenameResult()
    result.log_entry = {
        "show": show_name,
        "renames": [],
        "created_dirs": [],
        "removed_dirs": [],
        "renamed_dirs": [],
    }

    renames: list[tuple[Path, Path, Path]] = []
    source_dirs: set[Path] = set()

    for index in checked_indices:
        if index >= len(items):
            continue
        item = items[index]
        if item.new_name is None:
            continue
        if item.status != "OK" and "UNMATCHED" not in item.status:
            continue

        src = item.original
        source_dirs.add(src.parent)
        target_dir = item.target_dir or src.parent
        dst = target_dir / item.new_name

        if dst.exists() and src != dst:
            result.errors.append(f"Target already exists, skipped: {dst.name}")
            continue

        renames.append((src, dst, target_dir))

    if not renames:
        return result

    for src, dst, target_dir in renames:
        try:
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                if str(target_dir) not in result.log_entry["created_dirs"]:
                    result.log_entry["created_dirs"].append(str(target_dir))

            if src.parent != target_dir:
                shutil.move(str(src), str(dst))
            else:
                src.rename(dst)

            result.log_entry["renames"].append({
                "old": str(src), "new": str(dst),
            })
            result.renamed_count += 1
        except (OSError, shutil.Error) as error:
            result.errors.append(f"{src.name}: {error}")

    unmatched_dir = root_folder / "Unmatched"
    all_dirs = source_dirs.copy()
    for _, dst, target_dir in renames:
        all_dirs.add(target_dir)

    for season_dir in all_dirs:
        if not season_dir.exists() or season_dir == root_folder:
            continue
        try:
            season_dir.relative_to(unmatched_dir)
            continue
        except ValueError:
            pass
        season_num = get_season(season_dir)
        if season_num is None:
            continue
        proper_name = f"Season {season_num:02d}"
        if season_dir.name == proper_name:
            continue
        proper_path = season_dir.parent / proper_name
        if proper_path.exists():
            continue
        try:
            season_dir.rename(proper_path)
            result.log_entry["renamed_dirs"].append({
                "old": str(season_dir), "new": str(proper_path),
            })
        except OSError:
            pass

    for src_dir in source_dirs:
        try:
            if src_dir != root_folder and src_dir.exists():
                if not list(src_dir.iterdir()):
                    src_dir.rmdir()
                    result.log_entry["removed_dirs"].append(str(src_dir))
        except OSError:
            pass

    if show_folder_name and root_folder.exists():
        if root_folder.name != show_folder_name:
            new_root = root_folder.parent / show_folder_name
            same_dir = (
                os.path.normcase(str(root_folder))
                == os.path.normcase(str(new_root))
            )
            if same_dir or not new_root.exists():
                try:
                    root_folder.rename(new_root)
                    result.log_entry["renamed_dirs"].append({
                        "old": str(root_folder), "new": str(new_root),
                    })
                    result.new_root = new_root
                except OSError:
                    pass

    return result