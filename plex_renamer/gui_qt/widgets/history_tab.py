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
from ._history_tab_banner import hide_revert_banner, show_revert_banner
from ._job_list_tab import _JobListTab
from ._history_tab_state import (
    begin_revert_banner_state,
    build_history_toolbar_state,
    can_revert_checked_jobs,
    collect_confirm_revert_jobs,
    pending_revert_selection_changed,
    revert_jobs,
    sync_pending_revert_job_ids,
)

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

        self._confirm_revert_btn = QPushButton("Confirm Revert")
        self._confirm_revert_btn.setProperty("cssClass", "danger")
        self._confirm_revert_btn.clicked.connect(self._confirm_revert)
        self._confirm_revert_btn.hide()
        self._toolbar_layout.addWidget(self._confirm_revert_btn)

        self._cancel_revert_btn = QPushButton("Cancel")
        self._cancel_revert_btn.setProperty("cssClass", "secondary")
        self._cancel_revert_btn.clicked.connect(self._cancel_revert)
        self._toolbar_layout.addWidget(self._cancel_revert_btn)

        self._revert_info = QLabel("")
        self._revert_info.setProperty("cssClass", "text-dim")
        self._toolbar_layout.addWidget(self._revert_info)

        hide_revert_banner(
            self._revert_btn,
            self._confirm_revert_btn,
            self._cancel_revert_btn,
            self._revert_info,
        )

        self._finish_toolbar(_HISTORY_FILTERS)
        self._finish_list_pane()
        self.refresh()

    def refresh(self) -> None:
        jobs = self._queue_ctrl.get_history()
        self._model.set_jobs(jobs)
        toolbar_state = build_history_toolbar_state(
            jobs,
            shown_count=self._proxy.rowCount(),
            has_current_selection=self._table.currentIndex().isValid(),
        )
        self._status.setText(toolbar_state.status_text)
        if self._pending_revert_job_ids:
            self._pending_revert_job_ids = sync_pending_revert_job_ids(self._pending_revert_job_ids, jobs)
            if not self._pending_revert_job_ids:
                self._cancel_revert()
        self._sync_selection_widgets()
        if toolbar_state.should_select_first_row:
            self._table.selectRow(0)
        self._update_job_controls()

    def _update_job_controls(self) -> None:
        jobs = self._selected_jobs()
        focused = self._focused_job()
        if pending_revert_selection_changed(self._pending_revert_job_ids, jobs):
            self._cancel_revert()
        if focused is None:
            self._detail.clear()
        else:
            self._detail.set_job(focused)
        self._revert_btn.setEnabled(can_revert_checked_jobs(jobs))

    def _populate_context_menu(self, menu: QMenu, focused_job, checked_jobs) -> None:
        can_revert = can_revert_checked_jobs(checked_jobs)

        revert_action = menu.addAction("Revert Selected")
        revert_action.setEnabled(can_revert)
        revert_action.triggered.connect(self._revert_selected)

        menu.addSeparator()
        self._add_folder_context_actions(menu)
        del focused_job

    def _revert_selected(self) -> None:
        banner_state = begin_revert_banner_state(self._selected_jobs())
        if banner_state is None:
            QMessageBox.information(self, "Cannot Revert", "Only selected completed jobs with undo data can be reverted.")
            return
        self._pending_revert_job_ids = banner_state.pending_job_ids
        show_revert_banner(
            self._revert_btn,
            self._confirm_revert_btn,
            self._cancel_revert_btn,
            self._revert_info,
            info_text=banner_state.info_text,
        )

    def _confirm_revert(self) -> None:
        if not self._pending_revert_job_ids:
            self._cancel_revert()
            return

        jobs = collect_confirm_revert_jobs(self._queue_ctrl.get_history(), self._pending_revert_job_ids)
        if not jobs:
            self._cancel_revert()
            QMessageBox.information(self, "Cannot Revert", "The selected jobs are no longer revertible.")
            return

        errors = revert_jobs(self._queue_ctrl, jobs)
        self._cancel_revert()
        self.refresh()
        self.history_changed.emit()
        if errors:
            QMessageBox.warning(self, "Partial Revert", "\n".join(errors[:8]))

    def _cancel_revert(self) -> None:
        self._pending_revert_job_ids = []
        hide_revert_banner(
            self._revert_btn,
            self._confirm_revert_btn,
            self._cancel_revert_btn,
            self._revert_info,
        )

