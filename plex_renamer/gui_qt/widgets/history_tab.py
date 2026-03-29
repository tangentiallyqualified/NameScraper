"""History tab — controller-backed history view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...constants import JobStatus
from ...job_store import RenameJob
from ..models import JobStatusFilterProxyModel, JobTableModel
from .job_detail_panel import JobDetailPanel
from .segmented_control import SegmentedControl

_HISTORY_FILTERS: dict[str, set[str] | None] = {
    "All": None,
    "Completed": {JobStatus.COMPLETED},
    "Failed": {JobStatus.FAILED},
    "Reverted": {JobStatus.REVERTED},
    "Cancelled": {JobStatus.CANCELLED},
}


class HistoryTab(QWidget):
    """History tab backed by QueueController."""

    history_changed = Signal()

    def __init__(
        self,
        queue_controller,
        tmdb_provider: Callable[[], object | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_ctrl = queue_controller
        self._model = JobTableModel(history=True, parent=self)
        self._proxy = JobStatusFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._pending_revert_job_ids: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QFrame()
        toolbar.setProperty("cssClass", "panel")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 12, 12, 12)

        self._revert_btn = QPushButton("Revert Selected")
        self._revert_btn.clicked.connect(self._revert_selected)
        toolbar_layout.addWidget(self._revert_btn)

        self._clear_btn = QPushButton("Clear History")
        self._clear_btn.setProperty("cssClass", "danger")
        self._clear_btn.clicked.connect(self._clear_history)
        toolbar_layout.addWidget(self._clear_btn)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setProperty("cssClass", "secondary")
        self._select_all_btn.clicked.connect(self._select_all)
        toolbar_layout.addWidget(self._select_all_btn)

        self._clear_selection_btn = QPushButton("Clear Selection")
        self._clear_selection_btn.setProperty("cssClass", "secondary")
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        toolbar_layout.addWidget(self._clear_selection_btn)

        self._filter_control = SegmentedControl(_HISTORY_FILTERS.keys(), current_text="All")
        self._filter_control.currentTextChanged.connect(self._apply_filter)
        toolbar_layout.addWidget(self._filter_control)

        self._status = QLabel("No history yet")
        self._status.setProperty("cssClass", "text-dim")
        toolbar_layout.addWidget(self._status, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("cssClass", "secondary")
        refresh_btn.clicked.connect(self.refresh)
        toolbar_layout.addWidget(refresh_btn)
        root.addWidget(toolbar)

        self._revert_banner = QFrame()
        self._revert_banner.setProperty("cssClass", "panel")
        self._revert_banner.setStyleSheet(
            "QFrame { border-left: 4px solid #4a9eda; }"
        )
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

        root.addWidget(self._revert_banner)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
            self._table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table, stretch=1)

        self._detail = JobDetailPanel(tmdb_provider=tmdb_provider)
        root.addWidget(self._detail)

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

    def select_job(self, job_id: str) -> None:
        for row, job in enumerate(self._model.jobs()):
            if job.job_id != job_id:
                continue
            source_index = self._model.index(row, 0)
            proxy_index = self._proxy.mapFromSource(source_index)
            if not proxy_index.isValid():
                continue
            self._table.selectRow(proxy_index.row())
            self._table.scrollTo(proxy_index)
            return

    def _selected_jobs(self) -> list[RenameJob]:
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        jobs: list[RenameJob] = []
        for row in rows:
            proxy_index = self._proxy.index(row, 0)
            source_index = self._proxy.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            job = self._model.job_at(source_index.row())
            if job is not None:
                jobs.append(job)
        return jobs

    def _apply_filter(self, label: str) -> None:
        self._proxy.set_allowed_statuses(_HISTORY_FILTERS.get(label))
        self._clear_selection()
        self.refresh()

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

    def _select_all(self) -> None:
        self._table.selectAll()

    def _clear_selection(self) -> None:
        self._table.clearSelection()
