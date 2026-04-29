"""Feedback and status helpers for the main window."""

from __future__ import annotations

from concurrent.futures import Future
from logging import Logger
from typing import Any, Callable

from ..engine import RenameResult
from ..job_store import RenameJob


class MainWindowFeedbackCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        queue_index: int,
        history_index: int,
    ) -> None:
        self._window = window
        self._queue_index = queue_index
        self._history_index = history_index

    def start_job_poster_backfill(
        self,
        *,
        api_key_lookup: Callable[[str], str | None],
        submit_bg: Callable[[Callable[[], None]], Future[Any]],
        logger: Logger,
    ) -> Future[Any] | None:
        window = self._window
        if window._job_poster_backfill_started:
            return window._job_poster_backfill_future
        if not api_key_lookup("TMDB"):
            return None
        try:
            tmdb = window._ensure_tmdb()
        except Exception:
            logger.debug("Job poster backfill skipped (TMDB unavailable)")
            return None
        if tmdb is None:
            return None
        window._job_poster_backfill_started = True

        def _worker() -> None:
            try:
                updated = window.queue_ctrl.backfill_missing_job_poster_paths(tmdb)
            except Exception:
                logger.debug("Job poster backfill aborted (store unavailable)")
                return
            window._queue_bridge.on_poster_backfill_finished(updated)

        window._job_poster_backfill_future = submit_bg(_worker)
        return window._job_poster_backfill_future

    def on_poster_backfill_finished(self, updated: int) -> None:
        if updated <= 0:
            return
        self._window._refresh_job_views()

    def show_scan_feedback(self, *, title: str, message: str, tone: str) -> None:
        window = self._window
        token = (title, message)
        if window._scan_feedback_token == token:
            return
        window._scan_feedback_token = token
        window._toast_manager.show_toast(
            title=title,
            message=message,
            tone=tone,
            duration_ms=4000,
        )

    def update_media_badges(self, states) -> None:
        window = self._window
        mode = window.media_ctrl.active_content_mode
        needs_action = sum(1 for state in states if state.needs_review or state.show_id is None)
        has_issues = needs_action > 0
        badge = window._tv_badge if mode == "tv" else window._movie_badge
        badge.set_count(needs_action)
        badge.set_failure_visible(has_issues)

    def refresh_job_views(self) -> None:
        window = self._window
        window._queue_tab.refresh()
        window._history_tab.refresh()
        counts = window.queue_ctrl.count_by_status()
        pending = counts.get("pending", 0) + counts.get("running", 0)
        history = sum(
            counts.get(status, 0)
            for status in ("completed", "failed", "cancelled", "reverted", "revert_failed")
        )
        window._tabs.setTabText(self._queue_index, "Queue")
        window._tabs.setTabText(self._history_index, "History")
        window._queue_badge.set_count(pending)
        window._queue_badge.set_failure_visible(bool(counts.get("failed", 0)))
        window._history_badge.set_count(history)

    def on_job_started(self, _job: RenameJob) -> None:
        window = self._window
        if not window._queue_run_started:
            window._queue_run_started = True
            window._queue_completed_count = 0
            window._queue_failed_count = 0
            window._pending_success_jobs = 0
            window._pending_success_files = 0
            window._success_toast_timer.stop()

    def on_job_completed(self, job: RenameJob, result: RenameResult) -> None:
        window = self._window
        window.media_ctrl.apply_completed_job_to_state(job, result)
        window._queue_completed_count += 1
        renamed = result.renamed_count
        if not window._queue_run_started:
            noun = "file" if renamed == 1 else "files"
            window._toast_manager.show_toast(
                title=f"Job completed: {job.media_name}",
                message=f"{renamed} {noun} renamed.",
                tone="success",
                duration_ms=3000,
            )
            return
        window._pending_success_jobs += 1
        window._pending_success_files += renamed
        window._success_toast_timer.start()

    def flush_success_toast_batch(self) -> None:
        window = self._window
        if window._pending_success_jobs <= 0 or not window._queue_run_started:
            return
        jobs = window._pending_success_jobs
        files = window._pending_success_files
        window._pending_success_jobs = 0
        window._pending_success_files = 0
        job_noun = "job" if jobs == 1 else "jobs"
        file_noun = "file" if files == 1 else "files"
        window._toast_manager.show_toast(
            title=f"{jobs} {job_noun} completed",
            message=f"{files} {file_noun} renamed.",
            tone="success",
            duration_ms=3000,
        )

    def on_job_failed(self, job: RenameJob, error: str) -> None:
        window = self._window
        window._queue_failed_count += 1
        detail = error or job.error_message or "Unknown error"
        window._toast_manager.show_toast(
            title=f"Job failed: {job.media_name}",
            message=detail,
            tone="error",
            duration_ms=0,
            action_text="Show in History",
            action_callback=lambda job_id=job.job_id: window._show_history_job(job_id),
        )

    def on_queue_finished(self) -> None:
        window = self._window
        if not window._queue_run_started:
            return
        window._success_toast_timer.stop()
        window._pending_success_jobs = 0
        window._pending_success_files = 0
        summary = f"{window._queue_completed_count} completed"
        if window._queue_failed_count:
            summary += f", {window._queue_failed_count} failed"
        window._toast_manager.show_toast(
            title="Queue finished",
            message=summary,
            tone="accent",
            duration_ms=5000,
        )
        window._queue_run_started = False
        window._queue_completed_count = 0
        window._queue_failed_count = 0
