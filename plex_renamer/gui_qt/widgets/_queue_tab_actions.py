"""Action workflow helpers for QueueTab."""

from __future__ import annotations

from ...constants import JobStatus


def toggle_queue_running(queue_controller) -> None:
    if queue_controller.is_running:
        queue_controller.stop()
    else:
        queue_controller.start()


def execute_pending_jobs(queue_controller, jobs: list) -> list[str]:
    failed: list[str] = []
    for job in jobs:
        if not queue_controller.execute_single(job.job_id):
            failed.append(job.media_name or job.job_id[:8])
    return failed


def execute_focused_pending_job(queue_controller, focused_job) -> bool | None:
    if focused_job is None or focused_job.status != JobStatus.PENDING:
        return None
    return bool(queue_controller.execute_single(focused_job.job_id))


def pending_job_ids(jobs: list) -> list[str]:
    return [job.job_id for job in jobs]


def build_remove_confirmation_message(pending_jobs: list) -> str:
    total_files = sum(job.selected_count for job in pending_jobs)
    message = f"Remove {len(pending_jobs)} checked pending job(s) from the queue?"
    if len(pending_jobs) >= 10:
        message += f"\n\nThis will discard rename plans for {total_files} file(s)."
    return message
