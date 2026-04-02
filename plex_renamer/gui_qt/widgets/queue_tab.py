"""Queue tab — controller-backed queue view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QMenu,
    QPushButton,
    QWidget,
)

from ...constants import JobStatus
from ._job_list_tab import _JobListTab

_QUEUE_FILTERS: dict[str, set[str] | None] = {
    "All": None,
    "Pending": {JobStatus.PENDING},
    "Running": {JobStatus.RUNNING},
}


class QueueTab(_JobListTab):
    """Queue tab backed by QueueController."""

    queue_changed = Signal()

    def __init__(
        self,
        queue_controller,
        tmdb_provider: Callable[[], object | None] | None = None,
        navigate_to_media: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            queue_controller=queue_controller,
            history=False,
            tmdb_provider=tmdb_provider,
            parent=parent,
        )
        self._tmdb_provider = tmdb_provider
        self._navigate_to_media = navigate_to_media

        self._start_btn = QPushButton("Start Queue")
        self._start_btn.clicked.connect(self._toggle_queue)
        self._toolbar_layout.addWidget(self._start_btn)

        self._execute_btn = QPushButton("Run Checked")
        self._execute_btn.setProperty("cssClass", "secondary")
        self._execute_btn.clicked.connect(self._execute_selected)
        self._toolbar_layout.addWidget(self._execute_btn)

        self._toolbar_layout.addSpacing(12)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setProperty("cssClass", "secondary")
        self._select_all_btn.clicked.connect(self._select_all)
        self._toolbar_layout.addWidget(self._select_all_btn)

        self._clear_selection_btn = QPushButton("Clear All")
        self._clear_selection_btn.setProperty("cssClass", "secondary")
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        self._toolbar_layout.addWidget(self._clear_selection_btn)

        self._toolbar_layout.addSpacing(12)

        self._tv_btn = QPushButton("TV Shows")
        self._tv_btn.setProperty("cssClass", "secondary")
        self._tv_btn.clicked.connect(lambda: self._switch_tab(0))
        self._toolbar_layout.addWidget(self._tv_btn)

        self._movie_btn = QPushButton("Movies")
        self._movie_btn.setProperty("cssClass", "secondary")
        self._movie_btn.clicked.connect(lambda: self._switch_tab(1))
        self._toolbar_layout.addWidget(self._movie_btn)

        self._finish_toolbar(_QUEUE_FILTERS)
        actions = QFrame()
        actions.setProperty("cssClass", "panel")
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(12, 12, 12, 12)

        self._remove_btn = QPushButton("Remove Checked")
        self._remove_btn.setProperty("cssClass", "danger")
        self._remove_btn.clicked.connect(self._remove_selected)
        actions_layout.addWidget(self._remove_btn)

        self._move_up_btn = QPushButton("Move Checked Up")
        self._move_up_btn.setProperty("cssClass", "secondary")
        self._move_up_btn.clicked.connect(lambda: self._move_selected(-1))
        actions_layout.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("Move Checked Down")
        self._move_down_btn.setProperty("cssClass", "secondary")
        self._move_down_btn.clicked.connect(lambda: self._move_selected(1))
        actions_layout.addWidget(self._move_down_btn)

        actions_layout.addStretch()
        self._insert_panel_before_detail(actions)
        self._finish_list_pane()

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
        self._sync_selection_widgets()
        self._update_job_controls()

    def _update_job_controls(self) -> None:
        focused = self._focused_job()
        checked_jobs = self._selected_jobs()
        if focused is None:
            self._detail.clear()
        else:
            self._detail.set_job(focused)
        has_pending = any(job.status == JobStatus.PENDING for job in checked_jobs)
        can_execute = len(checked_jobs) == 1 and checked_jobs[0].status == JobStatus.PENDING
        self._remove_btn.setEnabled(has_pending)
        self._move_up_btn.setEnabled(has_pending)
        self._move_down_btn.setEnabled(has_pending)
        self._execute_btn.setEnabled(can_execute)

    def _populate_context_menu(self, menu: QMenu, focused_job, checked_jobs) -> None:
        has_pending = any(job.status == JobStatus.PENDING for job in checked_jobs)
        can_execute = len(checked_jobs) == 1 and checked_jobs[0].status == JobStatus.PENDING

        execute_action = menu.addAction("Run Checked")
        execute_action.setEnabled(can_execute)
        execute_action.triggered.connect(self._execute_selected)

        remove_action = menu.addAction("Remove Checked")
        remove_action.setEnabled(has_pending)
        remove_action.triggered.connect(self._remove_selected)

        move_up_action = menu.addAction("Move Checked Up")
        move_up_action.setEnabled(has_pending)
        move_up_action.triggered.connect(lambda: self._move_selected(-1))

        move_down_action = menu.addAction("Move Checked Down")
        move_down_action.setEnabled(has_pending)
        move_down_action.triggered.connect(lambda: self._move_selected(1))

        menu.addSeparator()
        self._add_folder_context_actions(menu)
        del focused_job

    def _toggle_queue(self) -> None:
        if self._queue_ctrl.is_running:
            self._queue_ctrl.stop()
        else:
            self._queue_ctrl.start()
        self.refresh()
        self.queue_changed.emit()

    def _execute_selected(self) -> None:
        jobs = self._selected_jobs()
        if len(jobs) != 1:
            return
        if not self._queue_ctrl.execute_single(jobs[0].job_id):
            QMessageBox.warning(self, "Cannot Run Job", "The checked job could not be executed right now.")
        self.refresh()
        self.queue_changed.emit()

    def _remove_selected(self) -> None:
        jobs = self._selected_jobs()
        pending = [job for job in jobs if job.status == JobStatus.PENDING]
        if not pending:
            QMessageBox.information(self, "Cannot Remove", "Only checked pending jobs can be removed.")
            return
        if QMessageBox.question(
            self,
            "Remove Jobs",
            f"Remove {len(pending)} checked pending job(s) from the queue?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._queue_ctrl.remove_jobs([job.job_id for job in pending])
        self.refresh()
        self.queue_changed.emit()

    def _move_selected(self, direction: int) -> None:
        pending_ids = [job.job_id for job in self._selected_jobs() if job.status == JobStatus.PENDING]
        if not pending_ids:
            return
        self._queue_ctrl.move_jobs(pending_ids, direction)
        self.refresh()
        self.queue_changed.emit()
        for job_id in pending_ids:
            self.select_job(job_id)

    def _switch_tab(self, index: int) -> None:
        if self._navigate_to_media is not None:
            self._navigate_to_media(index)
