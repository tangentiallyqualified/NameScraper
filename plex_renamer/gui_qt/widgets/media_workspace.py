"""Media workspace widget for TV Shows and Movies tabs.

Manages the EMPTY -> SCANNING -> READY state machine via a
QStackedWidget. The READY state shows a controller-backed 3-panel
workspace with roster, preview, and selection/detail summaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ._media_workspace_actions import MediaWorkspaceActionCoordinator
from ._media_workspace_lifecycle import MediaWorkspaceLifecycleCoordinator
from ._media_workspace_refresh import MediaWorkspaceRefreshCoordinator
from ._media_workspace_roster import _ROSTER_ENTRY_KIND_ROLE
from ._media_workspace_state import MediaWorkspaceStateCoordinator
from ._media_workspace_sync import MediaWorkspaceSyncCoordinator
from ._media_workspace_ui import MediaWorkspaceUiCoordinator
from ._media_workspace_view import MediaWorkspaceViewCoordinator
from ._workspace_widgets import (
    PreviewRowWidget as _PreviewRowWidget,
    RosterRowWidget as _RosterRowWidget,
)
from .match_picker_dialog import MatchPickerDialog
from .scan_progress import ScanProgressWidget

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService

# Stack indices
_EMPTY = 0
_SCANNING = 1
_READY = 2
_FOLDER_SECTION_KEY = "folder"


class MediaWorkspace(QWidget):
    """TV or Movie tab workspace with state-driven content switching."""

    # Emitted when a folder is selected — MainWindow handles the
    # controller call and state transitions.
    folder_selected = Signal(str)
    queue_changed = Signal()
    status_message = Signal(str, int)

    def __init__(
        self,
        media_type: str = "tv",
        media_controller=None,
        queue_controller=None,
        tmdb_provider=None,
        settings_service: "SettingsService | None" = None,
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
        self._roster_collapsed: dict[str, bool] = {"plex-ready": True}
        self._roster_selection_is_auto = False
        self._pending_roster_selection_auto: bool | None = None
        self._action_coordinator = MediaWorkspaceActionCoordinator(self)
        self._lifecycle_coordinator = MediaWorkspaceLifecycleCoordinator(
            self,
            empty_index=_EMPTY,
            scanning_index=_SCANNING,
            ready_index=_READY,
        )
        self._refresh_coordinator = MediaWorkspaceRefreshCoordinator(self)
        self._state_coordinator = MediaWorkspaceStateCoordinator(self, folder_section_key=_FOLDER_SECTION_KEY)
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
        """Switch to the 3-panel ready state."""
        self._lifecycle_coordinator.show_ready()

    def is_showing_ready(self) -> bool:
        return self._stack.currentIndex() == _READY

    @property
    def scan_progress_widget(self) -> ScanProgressWidget:
        return self._scan_progress

    @property
    def splitter(self) -> QSplitter:
        return self._splitter

    def apply_settings(self) -> None:
        self._lifecycle_coordinator.apply_settings()

    def queue_selected(self) -> None:
        self._activate_selected_primary_action()

    def queue_checked(self) -> None:
        self._queue_checked()

    def toggle_focused_check(self) -> None:
        """Toggle the checkbox on the currently focused roster item (Space)."""
        if self._stack.currentIndex() != _READY:
            return
        item = self._roster_list.currentItem()
        if item is None or item.data(_ROSTER_ENTRY_KIND_ROLE) != "state":
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        states = self._current_states()
        if row is None or not (0 <= row < len(states)):
            return
        state = states[row]
        self._set_item_check_state(item, not state.checked, preview=False)

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

    def _find_roster_item_by_index(self, index: int) -> QListWidgetItem | None:
        return self._state_coordinator.find_roster_item_by_index(index)

    def _set_roster_current_item(self, item: QListWidgetItem, *, auto_selected: bool) -> None:
        self._state_coordinator.set_roster_current_item(item, auto_selected=auto_selected)

    def _preferred_batch_focus_index(self, states: list[ScanState]) -> int | None:
        return self._refresh_coordinator.preferred_batch_focus_index(states)

    def _current_states(self) -> list[ScanState]:
        return self._state_coordinator.current_states()

    def _selected_state(self) -> ScanState | None:
        return self._state_coordinator.selected_state()

    def _ensure_check_bindings(self, state: ScanState) -> None:
        self._refresh_coordinator.ensure_check_bindings(state)

    def _normalize_queue_selection(self, states: list[ScanState]) -> None:
        self._refresh_coordinator.normalize_queue_selection(states)

    def _on_roster_item_clicked(self, item: QListWidgetItem) -> None:
        self._state_coordinator.on_roster_item_clicked(item)

    def _on_roster_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._sync_coordinator.on_roster_current_item_changed(current)

    def _on_roster_item_changed(self, item: QListWidgetItem) -> None:
        self._sync_coordinator.on_roster_item_changed(item)

    def _set_state_checked(self, state: ScanState, checked: bool) -> None:
        self._sync_coordinator.set_state_checked(state, checked)

    def _populate_preview(self, state: ScanState) -> None:
        self._state_coordinator.populate_preview(state)

    def _warm_preview_cache(self, states: list[ScanState], active_state: ScanState | None) -> None:
        self._state_coordinator.warm_preview_cache(states, active_state)

    def _on_preview_item_clicked(self, item: QListWidgetItem) -> None:
        self._state_coordinator.on_preview_item_clicked(item)

    def _update_sticky_header(self) -> None:
        self._state_coordinator.update_sticky_header()

    def _on_preview_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._sync_coordinator.on_preview_current_item_changed(current)

    def _on_preview_item_changed(self, item: QListWidgetItem) -> None:
        self._sync_coordinator.on_preview_item_changed(item)

    def _on_preview_master_changed(self, check_state: int) -> None:
        self._sync_coordinator.on_preview_master_changed(check_state)

    def _update_preview_master_state(self, state: ScanState | None) -> None:
        self._state_coordinator.update_preview_master_state(state)

    def _render_detail(self, state: ScanState | None, preview: PreviewItem | None = None) -> None:
        self._view_coordinator.render_detail(state, preview)

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

    def _set_preview_summary(self, text: str) -> None:
        self._preview_panel.set_summary(text)

    def _update_roster_selection_header(self, states: list[ScanState]) -> None:
        self._roster_panel.update_selection_header(states)

    def _attach_preview_widget(self, item: QListWidgetItem, state: ScanState, index: int, preview: PreviewItem) -> None:
        self._preview_panel.attach_preview_widget(item, state, index, preview)

    def _attach_folder_preview_widget(self, item: QListWidgetItem, source_name: str, target_name: str) -> None:
        self._preview_panel.attach_folder_preview_widget(item, source_name, target_name)

    def _set_item_check_state(self, item: QListWidgetItem, checked: bool, *, preview: bool) -> None:
        self._sync_coordinator.set_item_check_state(item, checked, preview=preview)

    def _sync_row_selection(self, list_widget: QListWidget) -> None:
        self._sync_coordinator.sync_row_selection(list_widget)

    def _approve_match(self, state: ScanState) -> None:
        self._action_coordinator.approve_match(state)

    def _approve_episode_mapping(self, state: ScanState, preview: PreviewItem) -> None:
        self._action_coordinator.approve_episode_mapping(state, preview)

    def _approve_all_episode_mappings(self) -> None:
        self._action_coordinator.approve_all_episode_mappings()

    def _prompt_fix_episode_mapping(self, state: ScanState, preview: PreviewItem) -> None:
        self._action_coordinator.prompt_fix_episode_mapping(
            state,
            preview,
            input_dialog=QInputDialog,
            warning_box=QMessageBox,
        )

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

    def _selected_preview(self) -> PreviewItem | None:
        return self._view_coordinator.selected_preview()

    def _folder_plan_text(self, state: ScanState) -> str:
        return self._view_coordinator.folder_plan_text(state)

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

    def _scroll_roster_item_into_context(self, item: QListWidgetItem) -> None:
        self._view_coordinator.scroll_roster_item_into_context(item)

    def _season_ratio_text(self, state: ScanState, season_num: int | None, item_count: int) -> str:
        return self._view_coordinator.season_ratio_text(state, season_num, item_count)

    def _season_expected_count(self, state: ScanState, season_num: int | None) -> int:
        return self._view_coordinator.season_expected_count(state, season_num)
