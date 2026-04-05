"""History tab — controller-backed history view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
)

from ...constants import JobStatus
from ._job_list_tab import _JobListTab

_HISTORY_FILTERS: dict[str, set[str] | None] = {
    "All": None,
    "Completed": {JobStatus.COMPLETED},
    "Failed": {JobStatus.FAILED},
    "Reverted": {JobStatus.REVERTED},
    "Revert Failed": {JobStatus.REVERT_FAILED},
    "Cancelled": {JobStatus.CANCELLED},
}


class HistoryTab(_JobListTab):
    """History tab backed by QueueController."""

    history_changed = Signal()

    def __init__(
        self,
        queue_controller,
        tmdb_provider: Callable[[], object | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            queue_controller=queue_controller,
            history=True,
            tmdb_provider=tmdb_provider,
            parent=parent,
        )
        self._pending_revert_job_ids: list[str] = []

        self._revert_btn = QPushButton("Revert Checked")
        self._revert_btn.clicked.connect(self._revert_selected)
        self._toolbar_layout.addWidget(self._revert_btn)

        self._confirm_revert_btn = QPushButton("Confirm Revert")
        self._confirm_revert_btn.setProperty("cssClass", "danger")
        self._confirm_revert_btn.clicked.connect(self._confirm_revert)
        self._confirm_revert_btn.hide()
        self._toolbar_layout.addWidget(self._confirm_revert_btn)

        self._cancel_revert_btn = QPushButton("Cancel")
        self._cancel_revert_btn.setProperty("cssClass", "secondary")
        self._cancel_revert_btn.clicked.connect(self._cancel_revert)
        self._cancel_revert_btn.hide()
        self._toolbar_layout.addWidget(self._cancel_revert_btn)

        self._revert_info = QLabel("")
        self._revert_info.setProperty("cssClass", "text-dim")
        self._revert_info.hide()
        self._toolbar_layout.addWidget(self._revert_info)

        self._finish_toolbar(_HISTORY_FILTERS)
        self._finish_list_pane()
        self.refresh()

    def refresh(self) -> None:
        jobs = self._queue_ctrl.get_history()
        self._model.set_jobs(jobs)
        shown = self._proxy.rowCount()
        status = f"{len(jobs)} historical job(s)" if jobs else "No history yet"
        if jobs and shown != len(jobs):
            status += f" · showing {shown}/{len(jobs)}"
        self._status.setText(status)
        if self._pending_revert_job_ids:
            available_job_ids = {job.job_id for job in jobs}
            self._pending_revert_job_ids = [
                job_id for job_id in self._pending_revert_job_ids if job_id in available_job_ids
            ]
            if not self._pending_revert_job_ids:
                self._cancel_revert()
        self._sync_selection_widgets()
        if not self._table.currentIndex().isValid() and self._proxy.rowCount():
            self._table.selectRow(0)
        self._update_job_controls()

    def _update_job_controls(self) -> None:
        jobs = self._selected_jobs()
        focused = self._focused_job()
        valid_selected_ids = {job.job_id for job in jobs}
        if self._pending_revert_job_ids and set(self._pending_revert_job_ids) != valid_selected_ids:
            self._cancel_revert()
        if focused is None:
            self._detail.clear()
        else:
            self._detail.set_job(focused)
        can_revert = any(job.status == JobStatus.COMPLETED and job.undo_data for job in jobs)
        self._revert_btn.setEnabled(can_revert)

    def _populate_context_menu(self, menu: QMenu, focused_job, checked_jobs) -> None:
        can_revert = any(job.status == JobStatus.COMPLETED and job.undo_data for job in checked_jobs)

        revert_action = menu.addAction("Revert Checked")
        revert_action.setEnabled(can_revert)
        revert_action.triggered.connect(self._revert_selected)

        menu.addSeparator()
        self._add_folder_context_actions(menu)
        del focused_job

    def _revert_selected(self) -> None:
        jobs = [job for job in self._selected_jobs() if job.status == JobStatus.COMPLETED and job.undo_data]
        if not jobs:
            QMessageBox.information(self, "Cannot Revert", "Only checked completed jobs with undo data can be reverted.")
            return
        self._pending_revert_job_ids = [job.job_id for job in jobs]
        total_renames = sum(len((job.undo_data or {}).get("renames", [])) for job in jobs)
        job_noun = "job" if len(jobs) == 1 else "jobs"
        file_noun = "file" if total_renames == 1 else "files"
        self._revert_info.setText(f"{len(jobs)} {job_noun}, {total_renames} {file_noun}")
        self._revert_btn.hide()
        self._confirm_revert_btn.show()
        self._cancel_revert_btn.show()
        self._revert_info.show()

    def _confirm_revert(self) -> None:
        if not self._pending_revert_job_ids:
            self._cancel_revert()
            return

        pending = set(self._pending_revert_job_ids)
        jobs = [
            job
            for job in self._queue_ctrl.get_history()
            if job.job_id in pending and job.status == JobStatus.COMPLETED and job.undo_data
        ]
        if not jobs:
            self._cancel_revert()
            QMessageBox.information(self, "Cannot Revert", "The checked jobs are no longer revertible.")
            return

        errors: list[str] = []
        for job in jobs:
            success, revert_errors = self._queue_ctrl.revert_job(job.job_id)
            if not success:
                errors.extend(revert_errors)
        self._cancel_revert()
        self.refresh()
        self.history_changed.emit()
        if errors:
            QMessageBox.warning(self, "Partial Revert", "\n".join(errors[:8]))

    def _cancel_revert(self) -> None:
        self._pending_revert_job_ids = []
        self._confirm_revert_btn.hide()
        self._cancel_revert_btn.hide()
        self._revert_info.hide()
        self._revert_btn.show()

