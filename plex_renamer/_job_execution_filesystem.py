"""Filesystem helpers for queued rename execution."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from .constants import MediaType
from .engine import RenameResult
from .parsing import get_season

_log = logging.getLogger(__name__)


UNMATCHED_FILES_DIR = "Unmatched Files"


def remap_target_into_final_root(
    target_dir: Path,
    root_folder: Path,
    final_root: Path | None,
) -> Path:
    """Route root-relative targets into the final renamed show folder."""
    if final_root is None:
        return target_dir
    try:
        relative = target_dir.relative_to(root_folder)
    except ValueError:
        return target_dir
    return final_root / relative


def apply_rename_plan(
    renames: list[tuple[Path, Path, Path]],
    result: RenameResult,
) -> set[str]:
    """Execute the planned file moves and record undo metadata."""
    successful_destinations: set[str] = set()

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
            successful_destinations.add(os.path.normcase(str(dst)))
        except (OSError, shutil.Error) as error:
            result.errors.append(f"{src.name}: {error}")

    return successful_destinations


def normalize_season_directories(
    *,
    root_folder: Path,
    source_dirs: set[Path],
    renames: list[tuple[Path, Path, Path]],
    result: RenameResult,
) -> None:
    """Normalize season directory names after a successful rename pass."""
    unmatched_dir = root_folder / "Unmatched"
    all_dirs = source_dirs.copy()
    for _, _, target_dir in renames:
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
        same_dir = os.path.normcase(str(season_dir)) == os.path.normcase(str(proper_path))
        if proper_path.exists() and not same_dir:
            continue
        try:
            season_dir.rename(proper_path)
            result.log_entry["renamed_dirs"].append({
                "old": str(season_dir), "new": str(proper_path),
            })
        except OSError as error:
            _log.warning("Could not normalize season dir %s: %s",
                         season_dir.name, error)


def cleanup_source_directories(
    *,
    media_type: str,
    library_root: Path,
    root_folder: Path,
    source_dirs: set[Path],
    source_to_target: dict[Path, Path],
    successful_destinations: set[str],
    result: RenameResult,
) -> None:
    """Move leftover files and remove emptied source directories."""
    for src_dir in source_dirs:
        try:
            if os.path.normcase(str(src_dir)) == os.path.normcase(str(library_root)):
                continue
            if src_dir == root_folder and media_type != MediaType.MOVIE:
                continue
            if not src_dir.exists():
                continue

            remaining = list(src_dir.iterdir())

            if not remaining:
                src_dir.rmdir()
                result.log_entry["removed_dirs"].append(str(src_dir))
                continue

            leftover_files = [
                path for path in remaining
                if path.is_file()
                and os.path.normcase(str(path)) not in successful_destinations
            ]
            if not leftover_files:
                continue

            target_dir = source_to_target.get(src_dir)
            if target_dir is None:
                continue

            unmatched_dir = target_dir / UNMATCHED_FILES_DIR
            moved_all = True

            for leftover in leftover_files:
                try:
                    if not unmatched_dir.exists():
                        unmatched_dir.mkdir(parents=True, exist_ok=True)
                        result.log_entry["created_dirs"].append(
                            str(unmatched_dir))
                    dst = unmatched_dir / leftover.name
                    shutil.move(str(leftover), str(dst))
                    result.log_entry["renames"].append(
                        {"old": str(leftover), "new": str(dst)})
                    _log.info("Moved leftover to Unmatched Files: %s",
                              leftover.name)
                except (OSError, shutil.Error) as error:
                    _log.warning("Could not move leftover %s: %s",
                                 leftover.name, error)
                    moved_all = False

            if moved_all and not list(src_dir.iterdir()):
                src_dir.rmdir()
                result.log_entry["removed_dirs"].append(str(src_dir))

        except OSError as error:
            _log.warning("Could not clean up source dir %s: %s",
                         src_dir.name, error)
