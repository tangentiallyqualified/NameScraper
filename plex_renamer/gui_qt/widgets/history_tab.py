"""History tab — controller-backed history view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
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
from ..models import JobTableModel
from .job_detail_panel import JobDetailPanel


class HistoryTab(QWidget):
    """History tab backed by QueueController."""

    def __init__(
        self,
        queue_controller,
        tmdb_provider: Callable[[], object | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_ctrl = queue_controller
        self._model = JobTableModel(history=True, parent=self)

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

        self._status = QLabel("No history yet")
        self._status.setProperty("cssClass", "text-dim")
        toolbar_layout.addWidget(self._status, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("cssClass", "secondary")
        refresh_btn.clicked.connect(self.refresh)
        toolbar_layout.addWidget(refresh_btn)
        root.addWidget(toolbar)

        self._table = QTableView()
        self._table.setModel(self._model)
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
        self._status.setText(f"{len(jobs)} historical job(s)" if jobs else "No history yet")
        self._clear_btn.setEnabled(bool(jobs))
        self._on_selection_changed()

    def select_job(self, job_id: str) -> None:
        for row, job in enumerate(self._model.jobs()):
            if job.job_id != job_id:
                continue
            self._table.selectRow(row)
            self._table.scrollTo(self._model.index(row, 0))
            return

    def _selected_jobs(self) -> list[RenameJob]:
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        return [job for row in rows if (job := self._model.job_at(row)) is not None]

    def _on_selection_changed(self, *_args) -> None:
        jobs = self._selected_jobs()
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
        if QMessageBox.question(
            self,
            "Revert Jobs",
            f"Revert {len(jobs)} completed job(s)? Files will be restored to their original locations.",
        ) != QMessageBox.StandardButton.Yes:
            return
        errors: list[str] = []
        for job in jobs:
            success, revert_errors = self._queue_ctrl.revert_job(job.job_id)
            if not success:
                errors.extend(revert_errors)
        self.refresh()
        if errors:
            QMessageBox.warning(self, "Partial Revert", "\n".join(errors[:8]))

    def _clear_history(self) -> None:
        if QMessageBox.question(
            self,
            "Clear History",
            "Delete all history entries? Stored undo data for historical jobs will be lost.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._queue_ctrl.clear_history()
        self.refresh()
