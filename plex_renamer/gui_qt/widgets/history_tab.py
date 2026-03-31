"""History tab — controller-backed history view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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

        self._revert_btn = QPushButton("Revert Selected")
        self._revert_btn.clicked.connect(self._revert_selected)
        self._toolbar_layout.addWidget(self._revert_btn)

        self._clear_btn = QPushButton("Clear History")
        self._clear_btn.setProperty("cssClass", "danger")
        self._clear_btn.clicked.connect(self._clear_history)
        self._toolbar_layout.addWidget(self._clear_btn)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setProperty("cssClass", "secondary")
        self._select_all_btn.clicked.connect(self._select_all)
        self._toolbar_layout.addWidget(self._select_all_btn)

        self._clear_selection_btn = QPushButton("Clear Selection")
        self._clear_selection_btn.setProperty("cssClass", "secondary")
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        self._toolbar_layout.addWidget(self._clear_selection_btn)

        self._finish_toolbar(_HISTORY_FILTERS)

        self._revert_banner = QFrame()
        self._revert_banner.setProperty("cssClass", "callout-banner")
        self._revert_banner.hide()
        banner_layout = QHBoxLayout(self._revert_banner)
        banner_layout.setContentsMargins(12, 12, 12, 12)
        banner_layout.setSpacing(12)

        self._revert_banner_label = QLabel("")
        self._revert_banner_label.setWordWrap(True)
        banner_layout.addWidget(self._revert_banner_label, stretch=1)

        self._confirm_revert_btn = QPushButton("Revert")
        self._confirm_revert_btn.clicked.connect(self._confirm_revert)
        banner_layout.addWidget(self._confirm_revert_btn)

        self._cancel_revert_btn = QPushButton("Cancel")
        self._cancel_revert_btn.setProperty("cssClass", "secondary")
        self._cancel_revert_btn.clicked.connect(self._cancel_revert)
        banner_layout.addWidget(self._cancel_revert_btn)

        self._insert_panel_before_detail(self._revert_banner)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self.refresh()

    def refresh(self) -> None:
        jobs = self._queue_ctrl.get_history()
        self._model.set_jobs(jobs)
        shown = self._proxy.rowCount()
        status = f"{len(jobs)} historical job(s)" if jobs else "No history yet"
        if jobs and shown != len(jobs):
            status += f" · showing {shown}/{len(jobs)}"
        self._status.setText(status)
        self._clear_btn.setEnabled(bool(jobs))
        self._select_all_btn.setEnabled(bool(jobs))
        self._clear_selection_btn.setEnabled(bool(jobs))
        if self._pending_revert_job_ids:
            available_job_ids = {job.job_id for job in jobs}
            self._pending_revert_job_ids = [
                job_id for job_id in self._pending_revert_job_ids if job_id in available_job_ids
            ]
            if not self._pending_revert_job_ids:
                self._cancel_revert()
        self._on_selection_changed()

    def _on_selection_changed(self, *_args) -> None:
        jobs = self._selected_jobs()
        valid_selected_ids = {job.job_id for job in jobs}
        if self._pending_revert_job_ids and set(self._pending_revert_job_ids) != valid_selected_ids:
            self._cancel_revert()
        if not jobs:
            self._detail.clear()
            self._revert_btn.setEnabled(False)
            return
        if len(jobs) == 1:
            self._detail.set_job(jobs[0])
        else:
            self._detail.clear(f"{len(jobs)} jobs selected")
        can_revert = any(job.status == JobStatus.COMPLETED and job.undo_data for job in jobs)
        self._revert_btn.setEnabled(can_revert)

    def _revert_selected(self) -> None:
        jobs = [job for job in self._selected_jobs() if job.status == JobStatus.COMPLETED and job.undo_data]
        if not jobs:
            QMessageBox.information(self, "Cannot Revert", "Only completed jobs with undo data can be reverted.")
            return
        self._pending_revert_job_ids = [job.job_id for job in jobs]
        total_renames = sum(len((job.undo_data or {}).get("renames", [])) for job in jobs)
        job_noun = "job" if len(jobs) == 1 else "jobs"
        file_noun = "file" if total_renames == 1 else "files"
        self._revert_banner_label.setText(
            f"Revert {len(jobs)} {job_noun}? This will move {total_renames} {file_noun} back to their original locations."
        )
        self._revert_banner.show()

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
            QMessageBox.information(self, "Cannot Revert", "The selected jobs are no longer revertible.")
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
        self._revert_banner.hide()

    def _clear_history(self) -> None:
        if QMessageBox.question(
            self,
            "Clear History",
            "Delete all history entries? Stored undo data for historical jobs will be lost.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._queue_ctrl.clear_history()
        self.refresh()
        self.history_changed.emit()
