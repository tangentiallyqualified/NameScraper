"""Media workspace widget for TV Shows and Movies tabs.

Manages the EMPTY -> SCANNING -> READY state machine via a
QStackedWidget. The READY state shows a controller-backed 2-panel
workspace: a roster and a work panel (header/strip/toolbar/episode
table/footer) that replaces the old preview + detail split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QInputDialog,
    QMessageBox,
    QWidget,
)

from ...engine import ScanState
from ._media_workspace_actions import MediaWorkspaceActionCoordinator
from ._media_workspace_automux import MediaWorkspaceAutoMuxCoordinator
from ._media_workspace_lifecycle import MediaWorkspaceLifecycleCoordinator
from ._media_workspace_refresh import MediaWorkspaceRefreshCoordinator
from ._media_workspace_state import MediaWorkspaceStateCoordinator
from ._media_workspace_sync import MediaWorkspaceSyncCoordinator
from ._media_workspace_ui import MediaWorkspaceUiCoordinator
from ._media_workspace_view import MediaWorkspaceViewCoordinator
from .match_picker_dialog import MatchPickerDialog
from .scan_progress import ScanProgressWidget

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService

# Stack indices
_EMPTY = 0
_SCANNING = 1
_READY = 2


class MediaWorkspace(QWidget):
    """TV or Movie tab workspace with state-driven content switching."""

    # Emitted when a folder is selected — MainWindow handles the
    # controller call and state transitions.
    folder_selected = Signal(str)
    queue_changed = Signal()
    status_message = Signal(str, int)
    toast_requested = Signal(str, str, str)  # title, message, tone ("success"/"info"/"error")

    def __init__(
        self,
        media_type: str = "tv",
        media_controller=None,
        queue_controller=None,
        tmdb_provider=None,
        settings_service: SettingsService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._media_ctrl = media_controller
        self._queue_ctrl = queue_controller
        self._tmdb_provider = tmdb_provider
        self._settings = settings_service
        self._roster_syncing = False
        self._preview_syncing = False
        self._preview_group_state: dict[str, set[int | str]] = {}
        self._roster_collapsed: dict[str, bool] = {"fully-ready": True}
        self._roster_selection_is_auto = False
        self._pending_roster_selection_auto: bool | None = None
        self._action_coordinator = MediaWorkspaceActionCoordinator(self)
        self._automux = MediaWorkspaceAutoMuxCoordinator(self)
        self._lifecycle_coordinator = MediaWorkspaceLifecycleCoordinator(
            self,
            empty_index=_EMPTY,
            scanning_index=_SCANNING,
            ready_index=_READY,
        )
        self._refresh_coordinator = MediaWorkspaceRefreshCoordinator(self)
        self._state_coordinator = MediaWorkspaceStateCoordinator(self)
        self._ui_coordinator = MediaWorkspaceUiCoordinator(self, empty_index=_EMPTY)
        self._view_coordinator = MediaWorkspaceViewCoordinator(self)
        self._build_ui()
        self._sync_coordinator = MediaWorkspaceSyncCoordinator(self)

    def _build_ui(self) -> None:
        self._ui_coordinator.build_ui()

    # ── Public API ───────────────────────────────────────────────

    def open_folder_dialog(self) -> None:
        """Trigger the empty state's folder picker dialog."""
        self._empty_state.open_folder_dialog()

    def load_folder(self, path: str) -> None:
        """Load a specific folder path (e.g. from recent folders menu)."""
        self._on_folder_selected(path)

    def show_empty(self) -> None:
        """Switch to the empty state."""
        self._lifecycle_coordinator.show_empty()

    def show_scanning(self) -> None:
        """Switch to the scanning state and start the timer."""
        self._lifecycle_coordinator.show_scanning()

    def show_ready(self) -> None:
        """Switch to the 2-panel ready state."""
        self._lifecycle_coordinator.show_ready()

    def show_ready_when_posters_warm(self) -> None:
        """Switch to READY once matched posters have warmed up (or timed out)."""
        self._lifecycle_coordinator.show_ready_when_posters_warm()

    def is_showing_ready(self) -> bool:
        return self._stack.currentIndex() == _READY

    @property
    def scan_progress_widget(self) -> ScanProgressWidget:
        return self._scan_progress

    def apply_settings(self) -> None:
        self._lifecycle_coordinator.apply_settings()

    def queue_selected(self) -> None:
        self._activate_selected_primary_action()

    def _toggle_automux(self) -> None:
        self._automux.toggle_selected()

    def queue_checked(self) -> None:
        self._queue_checked()

    def toggle_focused_check(self) -> None:
        """Toggle the checkbox on the currently focused roster item (Space)."""
        if self._stack.currentIndex() != _READY:
            return
        state_index = self._roster_panel.current_state_index()
        states = self._current_states()
        if state_index is None or not (0 <= state_index < len(states)):
            return
        self._set_roster_check_state(state_index, not states[state_index].checked)

    def force_rematch(self) -> None:
        """Open the Fix Match dialog for the currently selected roster item (F5)."""
        if self._stack.currentIndex() != _READY:
            return
        self._fix_match()

    def cancel_scan(self) -> bool:
        """Cancel a running scan. Returns True if a cancel was initiated."""
        if self._stack.currentIndex() != _SCANNING:
            return False
        self._on_cancel_scan()
        return True

    # ── Internals ────────────────────────────────────────────────

    def _on_folder_selected(self, path: str) -> None:
        self._lifecycle_coordinator.on_folder_selected(path)

    def _on_cancel_scan(self) -> None:
        self._lifecycle_coordinator.on_cancel_scan()

    def _on_splitter_moved(self) -> None:
        self._lifecycle_coordinator.on_splitter_moved()

    def _on_roster_master_changed(self, state: int) -> None:
        if self._roster_panel.master_syncing:
            return
        checked_value = Qt.CheckState.Checked.value
        unchecked_value = Qt.CheckState.Unchecked.value
        if state == checked_value:
            self._check_all()
        elif state == unchecked_value:
            self._uncheck_all()

    def refresh_from_controller(self) -> None:
        """Synchronize the ready-state roster and preview from controller state."""
        self._refresh_coordinator.refresh_from_controller()

    def _sync_roster_items(self, states: list[ScanState]) -> None:
        self._state_coordinator.sync_roster_items(states)

    def _set_roster_current_state(self, state_index: int, *, auto_selected: bool) -> None:
        self._state_coordinator.set_roster_current_state(state_index, auto_selected=auto_selected)

    def _current_states(self) -> list[ScanState]:
        return self._state_coordinator.current_states()

    def _selected_state(self) -> ScanState | None:
        return self._state_coordinator.selected_state()

    def _ensure_check_bindings(self, state: ScanState) -> None:
        self._refresh_coordinator.ensure_check_bindings(state)

    def _on_roster_group_toggled(self, group: str) -> None:
        self._state_coordinator.on_roster_group_toggled(group)

    def _on_roster_state_selected(self, state_index: int) -> None:
        self._sync_coordinator.on_roster_state_selected(state_index)

    def _on_roster_check_toggled(self, state_index: int, checked: bool) -> None:
        self._sync_coordinator.on_roster_check_toggled(state_index, checked)

    def _set_state_checked(self, state: ScanState, checked: bool) -> None:
        self._sync_coordinator.set_state_checked(state, checked)

    def _populate_preview(self, state: ScanState) -> None:
        self._state_coordinator.show_in_work_panel(state)

    def _on_episode_filter_changed(self, mode: str) -> None:
        state = self._selected_state()
        if state is not None:
            self._populate_preview(state)

    def _on_episode_search_changed(self, text: str) -> None:
        self._work_panel.model.set_search_text(text)
        self._work_panel.update_footer()

    def _on_episode_code_search_changed(self, text: str) -> None:
        self._work_panel.model.set_episode_search(text)
        self._work_panel.update_footer()

    def _on_table_section_toggled(self, section_key: str) -> None:
        self._state_coordinator.on_table_section_toggled(section_key)

    def _on_table_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        self._sync_coordinator.on_table_current_changed(current)

    def _on_table_row_clicked(self, index: QModelIndex) -> None:
        self._state_coordinator.on_table_row_clicked(index)

    def _on_table_expand_requested(self, index: QModelIndex) -> None:
        self._state_coordinator.on_table_expand_requested(index)

    def _on_inline_row_action(self, index: QModelIndex, action_id: str) -> None:
        self._state_coordinator.on_inline_row_action(index, action_id)

    def _expansion_card_for_index(self, index: QModelIndex):
        return self._state_coordinator.expansion_card_for_index(index)

    def _open_directory(self, directory: str) -> None:
        if directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def _check_all(self) -> None:
        self._refresh_coordinator.check_all()

    def _uncheck_all(self) -> None:
        self._refresh_coordinator.uncheck_all()

    def _queue_selected_state(self) -> None:
        self._action_coordinator.queue_selected_state()

    def _activate_selected_primary_action(self) -> None:
        self._action_coordinator.activate_selected_primary_action()

    def _queue_checked(self) -> None:
        self._action_coordinator.queue_checked(question_box=QMessageBox)

    def _summarize_skip_reasons(self, states: list[ScanState]) -> dict[str, int]:
        return self._action_coordinator.summarize_skip_reasons(states)

    def _queue_states(self, states: list[ScanState], *, empty_message: str) -> None:
        self._action_coordinator.queue_states(
            states,
            empty_message=empty_message,
            warning_box=QMessageBox,
        )

    def _fix_match(self) -> None:
        self._action_coordinator.fix_match(
            match_picker_dialog=MatchPickerDialog,
            warning_box=QMessageBox,
        )

    def _queue_eligibility(self, states: list[ScanState]):
        return self._action_coordinator.queue_eligibility(states)

    def _update_action_bar(self) -> None:
        self._action_coordinator.update_action_bar()

    def _set_roster_queue_button_text(self, text: str) -> None:
        self._action_coordinator.set_roster_queue_button_text(text)

    def _sync_action_button_metrics(self) -> None:
        self._action_coordinator.sync_action_button_metrics()

    def _update_roster_selection_header(self, states: list[ScanState]) -> None:
        self._roster_panel.update_selection_header(states)

    def _set_roster_check_state(self, state_index: int, checked: bool) -> None:
        self._sync_coordinator.set_roster_check_state(state_index, checked)

    def _approve_match(self, state: ScanState) -> None:
        self._action_coordinator.approve_match(state)

    def _approve_all_episode_mappings(self) -> None:
        self._action_coordinator.approve_all_episode_mappings()

    def _unassign_all_episode_mappings(self) -> None:
        self._action_coordinator.unassign_all_episode_mappings()

    def _enter_bulk_assign(self) -> None:
        self._action_coordinator.enter_bulk_assign()

    def _on_bulk_apply(self, pairs: list, unassign_file_ids: list | None = None) -> None:
        self._action_coordinator.apply_bulk_assignments(pairs, unassign_file_ids)

    def _on_bulk_cancel(self) -> None:
        self._action_coordinator.cancel_bulk_assign()

    def _prompt_assign_season(self, state: ScanState) -> None:
        self._action_coordinator.prompt_assign_season(
            state,
            input_dialog=QInputDialog,
            warning_box=QMessageBox,
        )

    def _apply_alternate_match(self, state: ScanState, match: dict) -> None:
        self._action_coordinator.apply_alternate_match(
            state,
            match,
            warning_box=QMessageBox,
        )

    def _folder_preview_data(self, state: ScanState) -> tuple[str, str] | None:
        return self._view_coordinator.folder_preview_data(state)

    def _media_noun(self) -> str:
        return self._action_coordinator.media_noun()

    def _queue_selected_label(self) -> str:
        return self._action_coordinator.queue_selected_label()

    def _primary_action_label(self, state: ScanState | None) -> str:
        return self._action_coordinator.primary_action_label(state)

    def _fix_match_label(self, state: ScanState | None) -> str:
        return self._action_coordinator.fix_match_label(state)

    def _needs_inline_match_choice(self, state: ScanState) -> bool:
        return self._action_coordinator.needs_inline_match_choice(state)

    def _can_inline_assign_season(self, state: ScanState) -> bool:
        return self._action_coordinator.can_inline_assign_season(state)

    def _can_inline_approve(self, state: ScanState) -> bool:
        return self._action_coordinator.can_inline_approve(state)

    def _can_fix_match(self, state: ScanState) -> bool:
        return self._action_coordinator.can_fix_match(state)

    def _restore_roster_selection_by_key(self, state_key: str | None) -> None:
        self._view_coordinator.restore_roster_selection_by_key(state_key)

    def _season_ratio_text(self, state: ScanState, season_num: int | None, item_count: int) -> str:
        return self._view_coordinator.season_ratio_text(state, season_num, item_count)
