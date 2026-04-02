"""Shared base class for queue and history job-list tabs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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


class _MasterCheckBox(QCheckBox):
    """Tri-state display checkbox that toggles like a normal binary control."""

    def nextCheckState(self) -> None:
        self.setCheckState(
            Qt.CheckState.Unchecked
            if self.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )


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
        self._master_check_syncing = False

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
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3, 4, 5, 6):
            self._table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        self._selection_bar = QFrame()
        self._selection_bar.setProperty("cssClass", "panel")
        self._selection_bar_layout = QHBoxLayout(self._selection_bar)
        self._selection_bar_layout.setContentsMargins(12, 10, 12, 10)
        self._selection_bar_layout.setSpacing(8)

        self._master_check = _MasterCheckBox("Select All")
        self._master_check.setTristate(True)
        self._master_check.stateChanged.connect(self._on_master_check_changed)
        self._selection_bar_layout.addWidget(self._master_check)

        self._selection_status = QLabel("0 checked")
        self._selection_status.setProperty("cssClass", "text-dim")
        self._selection_bar_layout.addWidget(self._selection_status)
        self._selection_bar_layout.addStretch()

        self._root.addWidget(self._selection_bar)
        self._root.addWidget(self._table, stretch=1)

        self._detail = JobDetailPanel(
            tmdb_provider=tmdb_provider,
            persist_poster_path=self._queue_ctrl.set_job_poster_path,
        )
        self._root.addWidget(self._detail)
        self._table.clicked.connect(self._on_table_clicked)
        self._table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)
        self._model.dataChanged.connect(self._on_checked_jobs_changed)
        self._model.modelReset.connect(self._sync_selection_widgets)

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
            self._table.selectionModel().setCurrentIndex(
                proxy_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
            )
            self._table.scrollTo(proxy_index)
            return

    def _selected_jobs(self) -> list[RenameJob]:
        return self._model.checked_jobs()

    def _focused_job(self) -> RenameJob | None:
        current = self._table.currentIndex()
        if not current.isValid():
            return None
        source_index = self._proxy.mapToSource(self._proxy.index(current.row(), 0))
        if not source_index.isValid():
            return None
        return self._model.job_at(source_index.row())

    def _apply_filter(self, label: str) -> None:
        self._proxy.set_allowed_statuses(self._filters.get(label))
        self._retain_visible_checked_jobs()
        self.refresh()

    def _select_all(self) -> None:
        self._model.set_jobs_checked(self._visible_job_ids(), True)

    def _clear_selection(self) -> None:
        self._model.clear_checked()

    def _visible_job_ids(self) -> set[str]:
        job_ids: set[str] = set()
        for row in range(self._proxy.rowCount()):
            proxy_index = self._proxy.index(row, 0)
            source_index = self._proxy.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            job = self._model.job_at(source_index.row())
            if job is not None:
                job_ids.add(job.job_id)
        return job_ids

    def _retain_visible_checked_jobs(self) -> None:
        self._model.set_checked_job_ids(self._model.checked_job_ids() & self._visible_job_ids())

    def _on_master_check_changed(self, state: int) -> None:
        if self._master_check_syncing:
            return
        checked_value = Qt.CheckState.Checked.value
        unchecked_value = Qt.CheckState.Unchecked.value
        if state == checked_value:
            self._select_all()
        elif state == unchecked_value:
            self._clear_selection()

    def _on_current_row_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._update_job_controls()

    def _on_table_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != 0:
            return
        current = self._proxy.data(index, Qt.ItemDataRole.CheckStateRole)
        next_state = (
            Qt.CheckState.Unchecked
            if current == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self._proxy.setData(index, next_state, Qt.ItemDataRole.CheckStateRole)

    def _on_checked_jobs_changed(self, top_left: QModelIndex, _bottom_right: QModelIndex, roles: list[int]) -> None:
        if roles and Qt.ItemDataRole.CheckStateRole not in roles:
            return
        if top_left.column() != 0:
            return
        self._sync_selection_widgets()
        self._update_job_controls()

    def _sync_selection_widgets(self) -> None:
        visible_ids = self._visible_job_ids()
        checked_ids = self._model.checked_job_ids()
        checked_visible = len(visible_ids & checked_ids)
        total_checked = len(checked_ids)

        if total_checked and total_checked != checked_visible:
            self._selection_status.setText(f"{checked_visible} visible checked ({total_checked} total)")
        else:
            noun = "job" if total_checked == 1 else "jobs"
            self._selection_status.setText(f"{total_checked} {noun} checked")

        self._master_check_syncing = True
        try:
            self._master_check.setEnabled(bool(visible_ids))
            if not visible_ids or checked_visible == 0:
                self._master_check.setCheckState(Qt.CheckState.Unchecked)
            elif checked_visible == len(visible_ids):
                self._master_check.setCheckState(Qt.CheckState.Checked)
            else:
                self._master_check.setCheckState(Qt.CheckState.PartiallyChecked)
        finally:
            self._master_check_syncing = False

    def _update_job_controls(self) -> None:
        """Implemented by subclasses to refresh detail and button enabled states."""