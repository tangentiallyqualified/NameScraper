"""
Job queue executor — processes jobs from the queue.

Runs in a background thread, picks pending jobs sequentially, executes
them, stores undo data, propagates path changes to dependent jobs,
and reports progress via callbacks.

Architecture notes for future extensibility:
  - The executor processes one job at a time within its worker thread.
  - Different job kinds (rename, subtitle download, etc.) are dispatched
    via _EXECUTORS, a registry mapping JobKind → executor function.
  - For future slow tasks (e.g. subtitle download), the executor can be
    extended to run multiple worker threads with a shared job queue,
    or to spawn a second QueueExecutor instance dedicated to slow tasks.
    The current sequential design is deliberate for rename jobs: TMDB
    rate limits and filesystem operations don't benefit from parallelism,
    and sequential execution simplifies undo + path propagation.

Also provides ``revert_job()`` for per-job undo without a stack constraint.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .constants import JobKind, JobStatus, MediaType
from .job_store import JobStore, RenameJob, RenameOp
from .engine import RenameResult
from .parsing import get_season

_log = logging.getLogger(__name__)


# ─── Pre-execution validation ────────────────────────────────────────────────

def _validate_sources(job: RenameJob) -> list[str]:
    """
    Pre-execution validation: check that source files exist.

    Returns a list of warning messages for missing sources.
    Files that have been moved/deleted between queue submission and
    execution are caught here rather than failing mid-rename.
    """
    library_root = Path(job.library_root)
    root_folder = library_root / job.source_folder
    missing: list[str] = []

    if not root_folder.exists():
        missing.append(
            f"Source folder no longer exists: {job.source_folder}")
        return missing  # No point checking individual files

    for op in job.rename_ops:
        if not op.selected:
            continue
        if op.status != "OK" and "UNMATCHED" not in op.status:
            continue
        if not op.new_name:
            continue

        src = library_root / op.original_relative
        if not src.exists():
            missing.append(f"Source not found: {src.name}")

    return missing


# Subdirectory name used inside a renamed target folder for files that were
# present in the source directory but not part of any rename operation.
_UNMATCHED_FILES_DIR = "Unmatched Files"


def _remap_target_into_final_root(
    target_dir: Path,
    root_folder: Path,
    final_root: Path | None,
) -> Path:
    """Route root-relative targets into the final renamed show folder.

    Queue execution previously moved files inside the source root and then
    renamed the entire root folder at the end. When leftover source
    directories remained, that pulled stale structure into the finished
    Plex folder. Remapping root-relative targets avoids that coupling.
    """
    if final_root is None:
        return target_dir
    try:
        relative = target_dir.relative_to(root_folder)
    except ValueError:
        return target_dir
    return final_root / relative


# ─── Job kind executor registry ──────────────────────────────────────────────

def _execute_rename(job: RenameJob) -> RenameResult:
    """
    Execute a rename job's file operations.

    Performs renames, directory normalization, and cleanup — but does NOT
    write to the legacy undo log.  The caller (the QueueExecutor) persists
    undo data via the JobStore and propagates path changes.
    """
    result = RenameResult()
    result.log_entry = {
        "show": job.media_name,
        "job_id": job.job_id,
        "renames": [],
        "created_dirs": [],
        "removed_dirs": [],
        "renamed_dirs": [],
    }

    library_root = Path(job.library_root)
    root_folder = library_root / job.source_folder
    root_is_library = (
        os.path.normcase(str(root_folder)) == os.path.normcase(str(library_root))
    )
    final_root: Path | None = None
    if (
        job.show_folder_rename
        and not (job.media_type == MediaType.MOVIE and root_is_library)
        and root_folder.name != job.show_folder_rename
    ):
        candidate_root = root_folder.parent / job.show_folder_rename
        same_dir = (
            os.path.normcase(str(root_folder))
            == os.path.normcase(str(candidate_root))
        )
        if not same_dir:
            final_root = candidate_root

    renames: list[tuple[Path, Path, Path]] = []
    source_dirs: set[Path] = set()
    # Maps each source directory to the target directory its files were moved
    # into.  Used after renames to relocate any leftover files.
    source_to_target: dict[Path, Path] = {}

    for op in job.rename_ops:
        if not op.selected:
            continue
        if op.status != "OK" and "UNMATCHED" not in op.status:
            continue
        if not op.new_name:
            continue

        src = library_root / op.original_relative
        target_dir = library_root / op.target_dir_relative
        target_dir = _remap_target_into_final_root(
            target_dir,
            root_folder,
            final_root,
        )
        dst = target_dir / op.new_name

        if not src.exists():
            result.errors.append(f"Source not found: {src.name}")
            continue
        if dst.exists() and src != dst:
            result.errors.append(f"Target already exists, skipped: {dst.name}")
            continue

        source_dirs.add(src.parent)
        source_to_target[src.parent] = target_dir
        renames.append((src, dst, target_dir))

    if not renames:
        return result

    # Track successful destination paths so the cleanup phase doesn't
    # treat them as leftovers (important when source and target dirs
    # resolve to the same NTFS directory with different casing).
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
        except (OSError, shutil.Error) as e:
            result.errors.append(f"{src.name}: {e}")

    # Normalize season folder names (TV only)
    unmatched_dir = root_folder / "Unmatched"
    all_dirs = source_dirs.copy()
    for _, dst, td in renames:
        all_dirs.add(td)

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
        except OSError as e:
            _log.warning("Could not normalize season dir %s: %s",
                         season_dir.name, e)

    # Clean up source directories after renames.
    #
    # For movies with their own subdirectory (release folders like
    # "Dune.2021.2160p.REMUX/"), root_folder IS the release directory.
    # Once renamed files have been moved to the Plex-named target folder,
    # anything remaining in the source directory (sample clips, NFOs,
    # extra files the scanner skipped) is relocated into
    # ``target_dir/Unmatched Files/`` rather than deleted.
    #
    # When a movie file lives directly in the library root (source_folder
    # is "."), root_folder == library_root.  In that case the library root
    # is NOT a release directory — it contains other movies and possibly
    # non-movie content — so leftover cleanup must be skipped entirely.
    #
    # For TV, root_folder is the show directory and is never touched here
    # (show_folder_rename handles it); season subdirectories follow the
    # same "move leftovers" logic.
    #
    # Revert: leftover moves are appended to ``renames``, so revert_job
    # restores them automatically alongside the primary media files — no
    # special handling required.
    for src_dir in source_dirs:
        try:
            # Never clean up the library root — it is shared across jobs
            # and is not a release directory for any single item.
            if os.path.normcase(str(src_dir)) == os.path.normcase(str(library_root)):
                continue
            if src_dir == root_folder and job.media_type != MediaType.MOVIE:
                continue
            if not src_dir.exists():
                continue

            remaining = list(src_dir.iterdir())

            if not remaining:
                src_dir.rmdir()
                result.log_entry["removed_dirs"].append(str(src_dir))
                continue

            # Separate files from subdirectories.  Only files are relocated;
            # subdirectories are left in place (safe default).
            # Exclude files that were just renamed — on NTFS a case-only
            # folder difference means source and target dirs resolve to the
            # same directory, so renamed files still appear in src_dir.
            leftover_files = [
                f for f in remaining
                if f.is_file()
                and os.path.normcase(str(f)) not in successful_destinations
            ]
            if not leftover_files:
                continue  # Only subdirs remain — leave the directory alone

            target_dir = source_to_target.get(src_dir)
            if target_dir is None:
                continue  # No known target — leave it alone

            unmatched_dir = target_dir / _UNMATCHED_FILES_DIR
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
                except (OSError, shutil.Error) as e:
                    _log.warning("Could not move leftover %s: %s",
                                 leftover.name, e)
                    moved_all = False

            # Remove source dir only when it is now completely empty
            if moved_all and not list(src_dir.iterdir()):
                src_dir.rmdir()
                result.log_entry["removed_dirs"].append(str(src_dir))

        except OSError as e:
            _log.warning("Could not clean up source dir %s: %s",
                         src_dir.name, e)

    # Rename root show/movie folder to match TMDB naming.
    # Skip this when targets were already routed into the final root.
    if (
        final_root is None
        and job.show_folder_rename
        and root_folder.exists()
        and not (job.media_type == MediaType.MOVIE and root_is_library)
    ):
        if root_folder.name != job.show_folder_rename:
            new_root = root_folder.parent / job.show_folder_rename
            # On case-insensitive filesystems (NTFS), new_root.exists()
            # returns True for case-only differences like "Goodfellas (1990)"
            # vs "GoodFellas (1990)".  Allow the rename when the paths
            # resolve to the same directory (case correction) but block it
            # when new_root is a genuinely different existing directory.
            same_dir = (
                os.path.normcase(str(root_folder)) ==
                os.path.normcase(str(new_root))
            )
            if same_dir or not new_root.exists():
                try:
                    root_folder.rename(new_root)
                    result.log_entry["renamed_dirs"].append({
                        "old": str(root_folder), "new": str(new_root),
                    })
                    result.new_root = new_root
                except OSError as e:
                    _log.warning(
                        "Could not rename show folder %s → %s: %s",
                        root_folder.name, job.show_folder_rename, e)

    return result


# Registry: add new job kinds here.
_EXECUTORS: dict[str, Callable[[RenameJob], RenameResult]] = {
    JobKind.RENAME: _execute_rename,
}


# ─── Per-job revert ──────────────────────────────────────────────────────────

def revert_job(job: RenameJob) -> tuple[bool, list[str]]:
    """
    Revert a single completed job using its stored undo data.

    Returns (success, errors).
    """
    if not job.undo_data:
        return False, ["No undo data stored for this job."]

    undo = job.undo_data
    library_root = Path(job.library_root)
    source_folder = Path(job.source_folder)
    cleanup_boundary = library_root / source_folder.parent
    errors: list[str] = []

    # Revert folder renames (in reverse order)
    dir_rename_map: dict[Path, Path] = {}
    for entry in reversed(undo.get("renamed_dirs", [])):
        new_dir = Path(entry["new"])
        old_dir = Path(entry["old"])
        try:
            if new_dir.exists():
                new_dir.rename(old_dir)
                dir_rename_map[new_dir] = old_dir
        except OSError as e:
            errors.append(f"Could not revert folder {new_dir.name}: {e}")

    # Recreate removed directories
    for dir_path_str in undo.get("removed_dirs", []):
        try:
            Path(dir_path_str).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(
                f"Could not recreate folder {Path(dir_path_str).name}: {e}")

    # Move files back
    for entry in reversed(undo.get("renames", [])):
        new_path = Path(entry["new"])
        old_path = Path(entry["old"])

        for renamed_new, renamed_old in dir_rename_map.items():
            try:
                rel = new_path.relative_to(renamed_new)
                new_path = renamed_old / rel
            except ValueError:
                pass
            try:
                rel = old_path.relative_to(renamed_new)
                old_path = renamed_old / rel
            except ValueError:
                pass

        try:
            old_path.parent.mkdir(parents=True, exist_ok=True)
            if new_path.exists():
                if new_path.parent != old_path.parent:
                    shutil.move(str(new_path), str(old_path))
                else:
                    new_path.rename(old_path)
            else:
                errors.append(f"File not found: {new_path.name}")
        except (OSError, shutil.Error) as e:
            errors.append(f"{new_path.name}: {e}")

    # Remove created directories if empty
    cleaned_dirs: set[str] = set()
    for dir_path_str in undo.get("created_dirs", []):
        dir_path = Path(dir_path_str)
        try:
            if dir_path.exists() and not list(dir_path.iterdir()):
                dir_path.rmdir()
                cleaned_dirs.add(dir_path_str)
        except OSError:
            pass

    for dir_path_str in list(cleaned_dirs):
        parent = Path(dir_path_str).parent
        while (
            parent.exists()
            and parent != parent.parent
            and parent != cleanup_boundary
        ):
            try:
                if not list(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                else:
                    break
            except OSError:
                break

    return len(errors) == 0, errors


# ─── Queue executor ──────────────────────────────────────────────────────────

class QueueExecutor:
    """
    Background worker that processes pending jobs from the queue.

    After each successful job with directory renames, calls
    ``store.propagate_path_changes()`` to update pending jobs.

    Listener management:
      - ``add_listener()`` registers callback sets.
      - ``clear_listeners()`` removes all registered listeners.
      - Callers should clear before re-registering to avoid duplicate
        callbacks when start/stop is toggled repeatedly.
    """

    def __init__(self, store: JobStore):
        self.store = store
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False

        # Listener-based callbacks (additive — callers must clear to avoid dups)
        self._listeners: list[dict[str, Callable | None]] = []

    def add_listener(
        self,
        on_started: Callable[[RenameJob], None] | None = None,
        on_completed: Callable[[RenameJob, RenameResult], None] | None = None,
        on_failed: Callable[[RenameJob, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> int:
        """Register a callback listener.  Returns listener index."""
        self._listeners.append({
            "started": on_started,
            "completed": on_completed,
            "failed": on_failed,
            "finished": on_finished,
        })
        return len(self._listeners) - 1

    def clear_listeners(self) -> None:
        self._listeners.clear()

    def _notify(self, event: str, *args: Any) -> None:
        """Fire all registered callbacks for the given event."""
        for listener in self._listeners:
            cb = listener.get(event)
            if cb is not None:
                try:
                    if event == "finished":
                        cb()
                    else:
                        cb(*args)
                except Exception:
                    _log.exception("Listener callback error for %s", event)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="QueueExecutor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _worker(self) -> None:
        _log.info("Queue executor started")
        try:
            while not self._stop_event.is_set():
                job = self.store.get_next_pending()
                if job is None:
                    break
                self._execute_one(job)
        except Exception as e:
            _log.exception("Queue executor crashed: %s", e)
        finally:
            self._running = False
            self._notify("finished")
            _log.info("Queue executor stopped")

    def execute_single_job(self, job_id: str) -> bool:
        """Execute a specific pending job by ID without starting the full queue.

        Returns True if the job was found and executed (regardless of
        success/failure), False if the job doesn't exist or isn't pending.

        Fires the same listener callbacks as the background worker so the
        UI stays in sync.  Safe to call from any thread, but callers must
        ensure only one execution path is active at a time (do not call
        while the background worker is running).
        """
        job = self.store.get_job(job_id)
        if job is None or job.status != JobStatus.PENDING:
            return False
        self._execute_one(job)
        return True

    def _execute_one(self, job: RenameJob) -> None:
        _log.info("Executing job %s: %s", job.job_id[:8], job.media_name)

        # ── Pre-execution validation ──────────────────────────────
        # Check that source paths still exist before transitioning
        # to RUNNING.  Catches files moved/deleted externally between
        # queue submission and execution.
        missing = _validate_sources(job)
        if missing:
            all_missing = all(
                not (Path(job.library_root) / op.original_relative).exists()
                for op in job.rename_ops
                if op.selected and op.new_name
                and (op.status == "OK" or "UNMATCHED" in op.status)
            )
            if all_missing:
                # Every source file is gone — fail immediately
                error_msg = (
                    f"All source files missing ({len(missing)}). "
                    f"Files may have been moved or deleted externally."
                )
                _log.error("Job %s: %s", job.job_id[:8], error_msg)
                self.store.update_status(
                    job.job_id, JobStatus.FAILED, error_message=error_msg)
                job.status = JobStatus.FAILED
                job.error_message = error_msg
                self._notify("failed", job, error_msg)
                return
            else:
                # Partial — log warnings but proceed (executor handles
                # per-file "source not found" gracefully)
                for msg in missing:
                    _log.warning("Job %s pre-check: %s",
                                 job.job_id[:8], msg)

        # ── Execute ───────────────────────────────────────────────
        self.store.update_status(job.job_id, JobStatus.RUNNING)
        job.status = JobStatus.RUNNING
        self._notify("started", job)

        try:
            executor_fn = _EXECUTORS.get(job.job_kind)
            if executor_fn is None:
                raise ValueError(f"Unknown job kind: {job.job_kind}")

            result = executor_fn(job)

            if result.errors and result.renamed_count == 0:
                error_msg = "; ".join(result.errors[:5])
                self.store.update_status(
                    job.job_id, JobStatus.FAILED, error_message=error_msg)
                job.status = JobStatus.FAILED
                job.error_message = error_msg
                self._notify("failed", job, error_msg)
            else:
                self.store.set_undo_data(job.job_id, result.log_entry)
                job.undo_data = result.log_entry

                if result.errors:
                    error_msg = "; ".join(result.errors[:5])
                    self.store.update_status(
                        job.job_id, JobStatus.COMPLETED,
                        error_message=error_msg)
                    job.error_message = error_msg
                else:
                    self.store.update_status(
                        job.job_id, JobStatus.COMPLETED)

                job.status = JobStatus.COMPLETED

                # Path propagation
                renamed_dirs = result.log_entry.get("renamed_dirs", [])
                if renamed_dirs:
                    propagated = self.store.propagate_path_changes(
                        job.job_id, renamed_dirs)
                    if propagated:
                        _log.info(
                            "Updated %d pending job(s) after path changes "
                            "from %s", propagated, job.media_name)

                self._notify("completed", job, result)

        except Exception as e:
            _log.exception("Job %s failed: %s", job.job_id[:8], e)
            error_msg = str(e)
            self.store.update_status(
                job.job_id, JobStatus.FAILED, error_message=error_msg)
            job.status = JobStatus.FAILED
            job.error_message = error_msg
            self._notify("failed", job, error_msg)
