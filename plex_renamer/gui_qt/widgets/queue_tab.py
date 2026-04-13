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
from ._queue_tab_actions import (
    build_remove_confirmation_message,
    execute_focused_pending_job,
    execute_pending_jobs,
    pending_job_ids,
    toggle_queue_running,
)
from ._queue_tab_presentation import apply_remove_button_state
from ._queue_tab_state import (
    build_queue_action_state,
    build_queue_toolbar_state,
    checked_pending_jobs,
)

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
        toolbar_state = build_queue_toolbar_state(
            jobs,
            shown_count=self._proxy.rowCount(),
            has_current_selection=self._table.currentIndex().isValid(),
            is_running=self._queue_ctrl.is_running,
        )
        self._status.setText(toolbar_state.status_text)
        self._start_btn.setText(toolbar_state.start_button_text)
        self._sync_selection_widgets()
        if toolbar_state.should_select_first_row:
            self._table.selectRow(0)
        self._update_job_controls()

    def _update_job_controls(self) -> None:
        focused = self._focused_job()
        checked_jobs = self._selected_jobs()
        if focused is None:
            self._detail.clear()
        else:
            self._detail.set_job(focused)
        action_state = build_queue_action_state(focused, checked_jobs)
        self._set_remove_button_enabled(action_state.has_pending_checked)
        self._execute_btn.setEnabled(bool(action_state.pending_checked_count))
        self._execute_btn.setText("Run Selected")

    def _populate_context_menu(self, menu: QMenu, focused_job, checked_jobs) -> None:
        action_state = build_queue_action_state(focused_job, checked_jobs)

        focused_action = menu.addAction("Run This Job")
        focused_action.setEnabled(action_state.can_execute_focused)
        focused_action.triggered.connect(self.execute_focused)

        execute_action = menu.addAction("Run Selected")
        execute_action.setEnabled(action_state.has_pending_checked)
        execute_action.triggered.connect(self._execute_selected)

        remove_action = menu.addAction("Remove Selected")
        remove_action.setEnabled(action_state.has_pending_checked)
        remove_action.triggered.connect(self._remove_selected)

        move_top_action = menu.addAction("Move to Top of Queue")
        move_top_action.setEnabled(action_state.has_pending_checked)
        move_top_action.triggered.connect(self._move_to_top)

        menu.addSeparator()
        self._add_folder_context_actions(menu, include_target=False)

    def _toggle_queue(self) -> None:
        toggle_queue_running(self._queue_ctrl)
        self.refresh()
        self.queue_changed.emit()

    def _execute_selected(self) -> None:
        jobs = checked_pending_jobs(self._selected_jobs())
        if not jobs:
            return
        failed = execute_pending_jobs(self._queue_ctrl, jobs)
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
        pending = checked_pending_jobs(jobs)
        if not pending:
            QMessageBox.information(self, "Cannot Remove", "Only checked pending jobs can be removed.")
            return
        message = build_remove_confirmation_message(pending)
        if QMessageBox.question(self, "Remove Jobs", message) != QMessageBox.StandardButton.Yes:
            return
        self._queue_ctrl.remove_jobs(pending_job_ids(pending))
        self.refresh()
        self.queue_changed.emit()

    def _move_to_top(self) -> None:
        pending_ids = pending_job_ids(checked_pending_jobs(self._selected_jobs()))
        if not pending_ids:
            return
        self._queue_ctrl.move_jobs_to_top(pending_ids)
        self.refresh()
        self.queue_changed.emit()

    def execute_focused(self) -> None:
        """Execute the currently focused pending job (Enter shortcut)."""
        focused = self._focused_job()
        success = execute_focused_pending_job(self._queue_ctrl, focused)
        if success is None:
            return
        if not success:
            QMessageBox.warning(self, "Cannot Run Job", "The focused job could not be executed right now.")
        self.refresh()
        self.queue_changed.emit()

    def remove_focused_checked(self) -> None:
        """Remove checked pending jobs (Delete shortcut)."""
        self._remove_selected()

    def _set_remove_button_enabled(self, enabled: bool) -> None:
        apply_remove_button_state(self._remove_btn, enabled=enabled)

