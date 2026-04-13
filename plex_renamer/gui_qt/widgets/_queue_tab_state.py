"""Pure view-state helpers for QueueTab."""

from __future__ import annotations

from dataclasses import dataclass

from ...constants import JobStatus


@dataclass(frozen=True)
class QueueToolbarState:
    status_text: str
    start_button_text: str
    should_select_first_row: bool


@dataclass(frozen=True)
class QueueActionState:
    has_pending_checked: bool
    pending_checked_count: int
    can_execute_focused: bool


def build_queue_toolbar_state(jobs: list, *, shown_count: int, has_current_selection: bool, is_running: bool) -> QueueToolbarState:
    pending = sum(1 for job in jobs if job.status == JobStatus.PENDING)
    running = sum(1 for job in jobs if job.status == JobStatus.RUNNING)
    parts: list[str] = []
    if running:
        parts.append(f"{running} running")
    if pending:
        parts.append(f"{pending} pending")
    if jobs and shown_count != len(jobs):
        parts.append(f"showing {shown_count}/{len(jobs)}")
    return QueueToolbarState(
        status_text=" · ".join(parts) if parts else "Queue empty",
        start_button_text="Stop Queue" if is_running else "Start Queue",
        should_select_first_row=not has_current_selection and shown_count > 0,
    )


def build_queue_action_state(focused_job, checked_jobs: list) -> QueueActionState:
    has_pending_checked = any(job.status == JobStatus.PENDING for job in checked_jobs)
    pending_checked_count = sum(1 for job in checked_jobs if job.status == JobStatus.PENDING)
    can_execute_focused = focused_job is not None and focused_job.status == JobStatus.PENDING
    return QueueActionState(
        has_pending_checked=has_pending_checked,
        pending_checked_count=pending_checked_count,
        can_execute_focused=can_execute_focused,
    )


def remove_button_css_class(*, enabled: bool) -> str:
    return "danger" if enabled else "secondary"


def checked_pending_jobs(jobs: list) -> list:
    return [job for job in jobs if job.status == JobStatus.PENDING]
