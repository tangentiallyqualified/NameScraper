"""Queue tab — controller-backed queue view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QItemSelectionModel
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

_QUEUE_FILTERS: dict[str, set[str] | None] = {
    "All": None,
    "Pending": {JobStatus.PENDING},
    "Running": {JobStatus.RUNNING},
}


class QueueTab(QWidget):
    """Queue tab backed by QueueController."""

    def __init__(
        self,
        queue_controller,
        tmdb_provider: Callable[[], object | None] | None = None,
        navigate_to_media: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_ctrl = queue_controller
        self._tmdb_provider = tmdb_provider
        self._navigate_to_media = navigate_to_media
        self._model = JobTableModel(history=False, parent=self)
        self._proxy = JobStatusFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QFrame()
        toolbar.setProperty("cssClass", "panel")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 12, 12, 12)

        self._start_btn = QPushButton("Start Queue")
        self._start_btn.clicked.connect(self._toggle_queue)
        toolbar_layout.addWidget(self._start_btn)

        self._execute_btn = QPushButton("Run Selected")
        self._execute_btn.setProperty("cssClass", "secondary")
        self._execute_btn.clicked.connect(self._execute_selected)
        toolbar_layout.addWidget(self._execute_btn)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setProperty("cssClass", "secondary")
        self._select_all_btn.clicked.connect(self._select_all)
        toolbar_layout.addWidget(self._select_all_btn)

        self._clear_selection_btn = QPushButton("Clear Selection")
        self._clear_selection_btn.setProperty("cssClass", "secondary")
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        toolbar_layout.addWidget(self._clear_selection_btn)

        self._filter_control = SegmentedControl(_QUEUE_FILTERS.keys(), current_text="All")
        self._filter_control.currentTextChanged.connect(self._apply_filter)
        toolbar_layout.addWidget(self._filter_control)

        self._status = QLabel("Queue empty")
        self._status.setProperty("cssClass", "text-dim")
        toolbar_layout.addWidget(self._status, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("cssClass", "secondary")
        refresh_btn.clicked.connect(self.refresh)
        toolbar_layout.addWidget(refresh_btn)
        root.addWidget(toolbar)

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

        actions = QFrame()
        actions.setProperty("cssClass", "panel")
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(12, 12, 12, 12)

        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.setProperty("cssClass", "danger")
        self._remove_btn.clicked.connect(self._remove_selected)
        actions_layout.addWidget(self._remove_btn)

        self._move_up_btn = QPushButton("Move Up")
        self._move_up_btn.setProperty("cssClass", "secondary")
        self._move_up_btn.clicked.connect(lambda: self._move_selected(-1))
        actions_layout.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("Move Down")
        self._move_down_btn.setProperty("cssClass", "secondary")
        self._move_down_btn.clicked.connect(lambda: self._move_selected(1))
        actions_layout.addWidget(self._move_down_btn)

        actions_layout.addStretch()

        self._tv_btn = QPushButton("Go to TV Shows")
        self._tv_btn.setProperty("cssClass", "secondary")
        self._tv_btn.clicked.connect(lambda: self._switch_tab(0))
        actions_layout.addWidget(self._tv_btn)

        self._movie_btn = QPushButton("Go to Movies")
        self._movie_btn.setProperty("cssClass", "secondary")
        self._movie_btn.clicked.connect(lambda: self._switch_tab(1))
        actions_layout.addWidget(self._movie_btn)
        root.addWidget(actions)

        self._detail = JobDetailPanel(tmdb_provider=self._tmdb_provider)
        root.addWidget(self._detail)

        self.refresh()

    def refresh(self) -> None:
        jobs = self._queue_ctrl.get_queue()
        self._model.set_jobs(jobs)
        shown = self._proxy.rowCount()
        pending = sum(1 for job in jobs if job.status == JobStatus.PENDING)
        running = sum(1 for job in jobs if job.status == JobStatus.RUNNING)
        parts = []
        if running:
            parts.append(f"{running} running")
        if pending:
            parts.append(f"{pending} pending")
        if jobs and shown != len(jobs):
            parts.append(f"showing {shown}/{len(jobs)}")
        self._status.setText(" · ".join(parts) if parts else "Queue empty")
        self._start_btn.setText("Stop Queue" if self._queue_ctrl.is_running else "Start Queue")
        has_jobs = bool(jobs)
        self._select_all_btn.setEnabled(has_jobs)
        self._clear_selection_btn.setEnabled(has_jobs)
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
        self._proxy.set_allowed_statuses(_QUEUE_FILTERS.get(label))
        self._clear_selection()
        self.refresh()

    def _on_selection_changed(self, *_args) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            self._detail.clear()
            self._remove_btn.setEnabled(False)
            self._move_up_btn.setEnabled(False)
            self._move_down_btn.setEnabled(False)
            self._execute_btn.setEnabled(False)
            return
        self._detail.set_job(jobs[0] if len(jobs) == 1 else None)
        if len(jobs) > 1:
            self._detail.clear(f"{len(jobs)} jobs selected")
        has_pending = any(job.status == JobStatus.PENDING for job in jobs)
        can_execute = len(jobs) == 1 and jobs[0].status == JobStatus.PENDING
        self._remove_btn.setEnabled(has_pending)
        self._move_up_btn.setEnabled(has_pending)
        self._move_down_btn.setEnabled(has_pending)
        self._execute_btn.setEnabled(can_execute)

    def _toggle_queue(self) -> None:
        if self._queue_ctrl.is_running:
            self._queue_ctrl.stop()
        else:
            self._queue_ctrl.start()
        self.refresh()

    def _execute_selected(self) -> None:
        jobs = self._selected_jobs()
        if len(jobs) != 1:
            return
        if not self._queue_ctrl.execute_single(jobs[0].job_id):
            QMessageBox.warning(self, "Cannot Run Job", "The selected job could not be executed right now.")
        self.refresh()

    def _remove_selected(self) -> None:
        jobs = self._selected_jobs()
        pending = [job for job in jobs if job.status == JobStatus.PENDING]
        if not pending:
            QMessageBox.information(self, "Cannot Remove", "Only pending jobs can be removed.")
            return
        if QMessageBox.question(
            self,
            "Remove Jobs",
            f"Remove {len(pending)} pending job(s) from the queue?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._queue_ctrl.remove_jobs([job.job_id for job in pending])
        self.refresh()

    def _move_selected(self, direction: int) -> None:
        pending_ids = [job.job_id for job in self._selected_jobs() if job.status == JobStatus.PENDING]
        if not pending_ids:
            return
        self._queue_ctrl.move_jobs(pending_ids, direction)
        self.refresh()
        for job_id in pending_ids:
            self.select_job(job_id)

    def _switch_tab(self, index: int) -> None:
        if self._navigate_to_media is not None:
            self._navigate_to_media(index)

    def _select_all(self) -> None:
        self._table.selectAll()

    def _clear_selection(self) -> None:
        self._table.clearSelection()
