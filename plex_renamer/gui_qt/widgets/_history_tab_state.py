"""State and revert workflow helpers for HistoryTab."""

from __future__ import annotations

from dataclasses import dataclass

from ...constants import JobStatus


@dataclass(frozen=True)
class HistoryToolbarState:
    status_text: str
    should_select_first_row: bool


@dataclass(frozen=True)
class HistoryRevertBannerState:
    pending_job_ids: list[str]
    info_text: str


def build_history_toolbar_state(jobs: list, *, shown_count: int, has_current_selection: bool) -> HistoryToolbarState:
    status_text = f"{len(jobs)} historical job(s)" if jobs else "No history yet"
    if jobs and shown_count != len(jobs):
        status_text += f" · showing {shown_count}/{len(jobs)}"
    return HistoryToolbarState(
        status_text=status_text,
        should_select_first_row=not has_current_selection and shown_count > 0,
    )


def sync_pending_revert_job_ids(pending_job_ids: list[str], jobs: list) -> list[str]:
    if not pending_job_ids:
        return []
    available_job_ids = {job.job_id for job in jobs}
    return [job_id for job_id in pending_job_ids if job_id in available_job_ids]


def completed_revertible_jobs(jobs: list) -> list:
    return [job for job in jobs if job.status == JobStatus.COMPLETED and job.undo_data]


def can_revert_checked_jobs(jobs: list) -> bool:
    return bool(completed_revertible_jobs(jobs))


def pending_revert_selection_changed(pending_job_ids: list[str], selected_jobs: list) -> bool:
    if not pending_job_ids:
        return False
    return set(pending_job_ids) != {job.job_id for job in selected_jobs}


def begin_revert_banner_state(jobs: list) -> HistoryRevertBannerState | None:
    revertible_jobs = completed_revertible_jobs(jobs)
    if not revertible_jobs:
        return None
    total_renames = sum(len((job.undo_data or {}).get("renames", [])) for job in revertible_jobs)
    job_noun = "job" if len(revertible_jobs) == 1 else "jobs"
    file_noun = "file" if total_renames == 1 else "files"
    return HistoryRevertBannerState(
        pending_job_ids=[job.job_id for job in revertible_jobs],
        info_text=f"{len(revertible_jobs)} {job_noun}, {total_renames} {file_noun}",
    )


def collect_confirm_revert_jobs(history_jobs: list, pending_job_ids: list[str]) -> list:
    pending = set(pending_job_ids)
    return [
        job
        for job in history_jobs
        if job.job_id in pending and job.status == JobStatus.COMPLETED and job.undo_data
    ]


def revert_jobs(queue_controller, jobs: list) -> list[str]:
    errors: list[str] = []
    for job in jobs:
        success, revert_errors = queue_controller.revert_job(job.job_id)
        if not success:
            errors.extend(revert_errors)
    return errors
