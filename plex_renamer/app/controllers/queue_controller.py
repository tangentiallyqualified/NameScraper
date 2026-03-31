"""UI-neutral job queue management.

Consolidates queue submission, execution, and revert logic that was
previously scattered across gui/app.py methods.  The widget layer calls
these methods and handles user-facing dialogs and UI refresh itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...constants import JobKind, JobStatus, MediaType
from ...engine import (
    PreviewItem,
    RenameResult,
    ScanState,
    build_rename_job_from_items,
    build_rename_job_from_state,
)
from ...job_executor import QueueExecutor, revert_job
from ...job_store import DuplicateJobError, JobStore, RenameJob
from ...parsing import build_movie_name, build_show_folder_name
from ..services.command_gating_service import CommandGatingService

_log = logging.getLogger(__name__)


@dataclass
class BatchQueueResult:
    """Summary of a batch queue submission."""

    added: int = 0
    skipped_duplicate: int = 0
    skipped_queued: int = 0
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_skipped(self) -> int:
        return self.skipped_duplicate + self.skipped_queued


class QueueController:
    """UI-neutral job queue management.

    Owns the ``QueueExecutor`` and ``JobStore`` lifecycle.  Provides
    queue submission methods that build jobs from domain objects and
    return structured results — no dialogs, no widget imports.
    """

    def __init__(self, job_store: JobStore) -> None:
        self.job_store = job_store
        self.executor = QueueExecutor(job_store)
        self._listeners: list[dict[str, Callable | None]] = []

    # ── Listener management ─────────────────────────────────────────

    def add_listener(
        self,
        on_job_started: Callable[[RenameJob], None] | None = None,
        on_job_completed: Callable[[RenameJob, RenameResult], None] | None = None,
        on_job_failed: Callable[[RenameJob, str], None] | None = None,
        on_queue_finished: Callable[[], None] | None = None,
    ) -> int:
        """Register a listener.  Returns listener index.

        Callbacks fire from the executor's background thread — the widget
        layer is responsible for marshaling to the main thread.
        """
        listener_id = self.executor.add_listener(
            on_started=on_job_started,
            on_completed=on_job_completed,
            on_failed=on_job_failed,
            on_finished=on_queue_finished,
        )
        return listener_id

    def clear_listeners(self) -> None:
        self.executor.clear_listeners()

    # ── Properties ──────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self.executor.is_running

    @property
    def pending_count(self) -> int:
        counts = self.job_store.count_by_status()
        return counts.get(JobStatus.PENDING, 0) + counts.get(JobStatus.RUNNING, 0)

    # ── Queue submission ────────────────────────────────────────────

    def add_single_job(
        self,
        items: list[PreviewItem],
        checked_indices: set[int],
        media_type: str,
        tmdb_id: int,
        media_name: str,
        library_root: Path,
        source_folder: Path,
        show_folder_rename: str | None = None,
        poster_path: str | None = None,
    ) -> RenameJob:
        """Build and enqueue a single rename job.

        Returns the created job on success.
        Raises ``DuplicateJobError`` if the job already exists.
        """
        job = build_rename_job_from_items(
            items=items,
            checked_indices=checked_indices,
            media_type=media_type,
            tmdb_id=tmdb_id,
            media_name=media_name,
            library_root=library_root,
            source_folder=source_folder,
            show_folder_rename=show_folder_rename,
            poster_path=poster_path,
        )
        self.job_store.add_job(job)
        return job

    def add_tv_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        command_gating: CommandGatingService,
    ) -> BatchQueueResult:
        """Evaluate and enqueue all checked TV shows.

        Iterates *states*, evaluates eligibility via *command_gating*,
        builds jobs, and returns a structured summary.  States are
        marked ``queued = True`` on successful submission.
        """
        result = BatchQueueResult()

        for state in states:
            if not state.checked:
                continue

            eligibility = command_gating.evaluate_scan_state(
                state,
                require_resolved_review=True,
                allow_show_level_queue=True,
            )
            if not eligibility.enabled:
                if eligibility.command_state.value == "disabled_already_queued":
                    result.skipped_queued += 1
                else:
                    result.blocked.append(
                        f"{state.display_name}: {eligibility.reason}")
                continue

            checked = set(eligibility.selected_indices)
            show_folder = build_show_folder_name(
                state.media_info.get("name", ""),
                state.media_info.get("year", ""),
            )

            job = build_rename_job_from_state(
                state=state,
                library_root=library_root,
                show_folder_rename=show_folder,
                checked_indices=checked,
            )

            try:
                self.job_store.add_job(job)
                state.queued = True
                result.added += 1
            except DuplicateJobError:
                result.skipped_duplicate += 1
            except Exception as e:
                result.errors.append(f"{state.display_name}: {e}")

        return result

    def add_movie_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        command_gating: CommandGatingService,
    ) -> BatchQueueResult:
        """Evaluate and enqueue all eligible movies.

        Each movie becomes its own job.  States are marked
        ``queued = True`` on successful submission.
        """
        result = BatchQueueResult()

        for state in states:
            if not state.checked:
                continue

            eligibility = command_gating.evaluate_scan_state(state, require_resolved_review=True)
            if not eligibility.enabled:
                if eligibility.command_state.value == "disabled_already_queued":
                    result.skipped_queued += 1
                continue

            if not state.preview_items:
                result.skipped_queued += 1
                continue

            item = state.preview_items[0]
            movie_folder = build_movie_name(
                state.media_info.get("title", ""),
                state.media_info.get("year", ""),
                "",
            )

            job = build_rename_job_from_items(
                items=[item],
                checked_indices={0},
                media_type=MediaType.MOVIE,
                tmdb_id=state.show_id or 0,
                media_name=state.display_name,
                library_root=library_root,
                source_folder=item.original.parent,
                show_folder_rename=movie_folder,
                poster_path=state.media_info.get("poster_path"),
            )

            try:
                self.job_store.add_job(job)
                state.queued = True
                result.added += 1
            except DuplicateJobError:
                result.skipped_duplicate += 1

        return result

    # ── Direct rename recording ────────────────────────────────────

    def record_completed_job(self, job: RenameJob, result: RenameResult) -> None:
        """Record an already-executed rename as a completed history entry.

        Used by the legacy direct-rename path (execute immediately, then
        record for undo).  The PySide6 shell will use queue→execute
        instead, so this method exists to keep the tkinter shell routed
        through the controller rather than accessing JobStore directly.
        """
        if result.renamed_count == 0:
            return

        job.status = JobStatus.COMPLETED
        job.undo_data = result.log_entry
        if result.errors:
            job.error_message = "; ".join(result.errors[:5])
        self.job_store.add_job(job)

    def set_job_poster_path(self, job_id: str, poster_path: str | None) -> None:
        """Persist a resolved poster path for an existing job."""
        self.job_store.set_poster_path(job_id, poster_path)

    def get_latest_revertible_job(self) -> RenameJob | None:
        """Return the most recent completed job with stored undo data."""
        return self.job_store.get_latest_completed_with_undo()

    # ── Execution ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background queue executor."""
        self.executor.start()

    def stop(self) -> None:
        """Stop the queue executor."""
        self.executor.stop()

    def execute_single(self, job_id: str) -> bool:
        """Execute a specific pending job immediately."""
        return self.executor.execute_single_job(job_id)

    def move_jobs(self, job_ids: list[str], direction: int) -> None:
        """Move pending jobs up or down in queue order."""
        self.job_store.move_jobs(job_ids, direction)

    def remove_jobs(self, job_ids: list[str]) -> int:
        """Remove pending or cancelled jobs from the queue."""
        return self.job_store.remove_jobs(job_ids)

    def clear_history(self) -> int:
        """Delete all terminal jobs from history."""
        return self.job_store.clear_history()

    # ── Revert ──────────────────────────────────────────────────────

    def revert_job(self, job_id: str) -> tuple[bool, list[str]]:
        """Revert a completed job by ID.

        Returns ``(success, errors)``.

        Successful reverts are marked ``REVERTED``. Failed revert attempts
        are marked ``REVERT_FAILED`` so history reflects that the undo did
        not complete cleanly.
        """
        job = self.job_store.get_job(job_id)
        if job is None:
            return False, [f"Job {job_id} not found."]
        if not job.undo_data:
            return False, ["No undo data stored for this job."]

        success, errors = revert_job(job)
        self.job_store.update_status(
            job_id,
            JobStatus.REVERTED if success else JobStatus.REVERT_FAILED,
            error_message="; ".join(errors[:3]) if errors else None,
        )
        return success, errors

    # ── Query ───────────────────────────────────────────────────────

    def get_pending_jobs(self) -> list[RenameJob]:
        return self.job_store.get_pending()

    def get_job(self, job_id: str) -> RenameJob | None:
        """Return a job by ID, or None if it does not exist."""
        return self.job_store.get_job(job_id)

    def get_queue(self) -> list[RenameJob]:
        """Pending + running jobs."""
        return self.job_store.get_queue()

    def get_history(self) -> list[RenameJob]:
        """Completed, failed, reverted, revert-failed, and cancelled jobs."""
        return self.job_store.get_history()

    def count_by_status(self) -> dict[str, int]:
        return self.job_store.count_by_status()

    def backfill_missing_job_poster_paths(self, tmdb: Any) -> int:
        """Resolve and persist missing poster paths for queued/history jobs using cached TMDB metadata only."""
        cache: dict[tuple[str, int], str | None] = {}
        updated = 0

        for job in self.job_store.get_all():
            if job.poster_path or not job.tmdb_id:
                continue

            key = (job.media_type, job.tmdb_id)
            poster_path = cache.get(key)
            if key not in cache:
                poster_path = tmdb.get_cached_poster_path(job.tmdb_id, media_type=job.media_type)
                cache[key] = poster_path

            if poster_path:
                self.job_store.set_poster_path(job.job_id, poster_path)
                updated += 1

        return updated

    def close(self) -> None:
        """Clean shutdown: stop executor and close the store."""
        if self.executor.is_running:
            self.executor.stop()
        self.job_store.close()
