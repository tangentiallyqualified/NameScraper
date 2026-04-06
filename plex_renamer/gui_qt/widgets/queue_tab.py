"""Queue tab — controller-backed queue view for Phase 4."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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

        self._execute_btn = QPushButton("Run Selected")
        self._execute_btn.setProperty("cssClass", "secondary")
        self._execute_btn.clicked.connect(self._execute_selected)
        self._toolbar_layout.addWidget(self._execute_btn)

        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.setProperty("cssClass", "secondary")
        self._remove_btn.clicked.connect(self._remove_selected)
        self._toolbar_layout.addWidget(self._remove_btn)

        self._finish_toolbar(_QUEUE_FILTERS)
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
        self._sync_selection_widgets()
        if not self._table.currentIndex().isValid() and self._proxy.rowCount():
            self._table.selectRow(0)
        self._update_job_controls()

    def _update_job_controls(self) -> None:
        focused = self._focused_job()
        checked_jobs = self._selected_jobs()
        if focused is None:
            self._detail.clear()
        else:
            self._detail.set_job(focused)
        has_pending = any(job.status == JobStatus.PENDING for job in checked_jobs)
        pending_checked = [job for job in checked_jobs if job.status == JobStatus.PENDING]
        self._set_remove_button_enabled(has_pending)
        self._execute_btn.setEnabled(bool(pending_checked))
        self._execute_btn.setText("Run Selected")

    def _populate_context_menu(self, menu: QMenu, focused_job, checked_jobs) -> None:
        has_pending = any(job.status == JobStatus.PENDING for job in checked_jobs)
        can_execute = any(job.status == JobStatus.PENDING for job in checked_jobs)

        execute_action = menu.addAction("Run Selected")
        execute_action.setEnabled(can_execute)
        execute_action.triggered.connect(self._execute_selected)

        remove_action = menu.addAction("Remove Selected")
        remove_action.setEnabled(has_pending)
        remove_action.triggered.connect(self._remove_selected)

        move_top_action = menu.addAction("Move to Top of Queue")
        move_top_action.setEnabled(has_pending)
        move_top_action.triggered.connect(self._move_to_top)

        menu.addSeparator()
        self._add_folder_context_actions(menu, include_target=False)
        del focused_job

    def _toggle_queue(self) -> None:
        if self._queue_ctrl.is_running:
            self._queue_ctrl.stop()
        else:
            self._queue_ctrl.start()
        self.refresh()
        self.queue_changed.emit()

    def _execute_selected(self) -> None:
        jobs = [job for job in self._selected_jobs() if job.status == JobStatus.PENDING]
        if not jobs:
            return
        failed: list[str] = []
        for job in jobs:
            if not self._queue_ctrl.execute_single(job.job_id):
                failed.append(job.media_name or job.job_id[:8])
        self.refresh()
        self.queue_changed.emit()
        if failed:
            QMessageBox.warning(
                self,
                "Cannot Run Job",
                "The following checked jobs could not be executed right now:\n\n" + "\n".join(failed[:8]),
            )

    def _remove_selected(self) -> None:
        jobs = self._selected_jobs()
        pending = [job for job in jobs if job.status == JobStatus.PENDING]
        if not pending:
            QMessageBox.information(self, "Cannot Remove", "Only checked pending jobs can be removed.")
            return
        total_files = sum(job.selected_count for job in pending)
        message = f"Remove {len(pending)} checked pending job(s) from the queue?"
        if len(pending) >= 10:
            message += f"\n\nThis will discard rename plans for {total_files} file(s)."
        if QMessageBox.question(self, "Remove Jobs", message) != QMessageBox.StandardButton.Yes:
            return
        self._queue_ctrl.remove_jobs([job.job_id for job in pending])
        self.refresh()
        self.queue_changed.emit()

    def _move_to_top(self) -> None:
        pending_ids = [job.job_id for job in self._selected_jobs() if job.status == JobStatus.PENDING]
        if not pending_ids:
            return
        self._queue_ctrl.move_jobs_to_top(pending_ids)
        self.refresh()
        self.queue_changed.emit()

    def execute_focused(self) -> None:
        """Execute the currently focused pending job (Enter shortcut)."""
        focused = self._focused_job()
        if focused is None or focused.status != JobStatus.PENDING:
            return
        if not self._queue_ctrl.execute_single(focused.job_id):
            QMessageBox.warning(self, "Cannot Run Job", "The focused job could not be executed right now.")
        self.refresh()
        self.queue_changed.emit()

    def remove_focused_checked(self) -> None:
        """Remove checked pending jobs (Delete shortcut)."""
        self._remove_selected()

    def _set_remove_button_enabled(self, enabled: bool) -> None:
        css_class = "danger" if enabled else "secondary"
        if self._remove_btn.property("cssClass") != css_class:
            self._remove_btn.setProperty("cssClass", css_class)
            style = self._remove_btn.style()
            style.unpolish(self._remove_btn)
            style.polish(self._remove_btn)
        self._remove_btn.setEnabled(enabled)

