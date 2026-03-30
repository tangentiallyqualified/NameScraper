"""Shared base class for queue and history job-list tabs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...job_store import RenameJob
from ..models import JobStatusFilterProxyModel, JobTableModel
from .job_detail_panel import JobDetailPanel
from .segmented_control import SegmentedControl


class _JobListTab(QWidget):
    """Shared table/detail/filter shell for queue and history tabs."""

    def __init__(
        self,
        *,
        queue_controller,
        history: bool,
        tmdb_provider: Callable[[], object | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_ctrl = queue_controller
        self._model = JobTableModel(history=history, parent=self)
        self._proxy = JobStatusFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._filters: dict[str, set[str] | None] = {}

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(8)

        self._toolbar = QFrame()
        self._toolbar.setProperty("cssClass", "panel")
        self._toolbar_layout = QHBoxLayout(self._toolbar)
        self._toolbar_layout.setContentsMargins(12, 12, 12, 12)
        self._root.addWidget(self._toolbar)

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
        self._root.addWidget(self._table, stretch=1)

        self._detail = JobDetailPanel(
            tmdb_provider=tmdb_provider,
            persist_poster_path=self._queue_ctrl.set_job_poster_path,
        )
        self._root.addWidget(self._detail)

    def _finish_toolbar(self, filters: dict[str, set[str] | None], *, current_text: str = "All") -> None:
        self._filters = dict(filters)
        self._filter_control = SegmentedControl(filters.keys(), current_text=current_text)
        self._filter_control.currentTextChanged.connect(self._apply_filter)
        self._toolbar_layout.addWidget(self._filter_control)

        self._status = QLabel("")
        self._status.setProperty("cssClass", "text-dim")
        self._toolbar_layout.addWidget(self._status, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("cssClass", "secondary")
        refresh_btn.clicked.connect(self.refresh)
        self._toolbar_layout.addWidget(refresh_btn)

    def _insert_panel_before_detail(self, widget: QWidget) -> None:
        self._root.insertWidget(self._root.count() - 1, widget)

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
        self._proxy.set_allowed_statuses(self._filters.get(label))
        self._clear_selection()
        self.refresh()

    def _select_all(self) -> None:
        self._table.selectAll()

    def _clear_selection(self) -> None:
        self._table.clearSelection()