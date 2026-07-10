"""Selection and checkbox synchronization helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex

from ._media_helpers import is_state_queue_approvable as _is_state_queue_approvable


class MediaWorkspaceSyncCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def on_roster_state_selected(self, state_index: int) -> None:
        workspace = self._workspace
        if workspace._pending_roster_selection_auto is not None:
            workspace._roster_selection_is_auto = workspace._pending_roster_selection_auto
            workspace._pending_roster_selection_auto = None
        else:
            workspace._roster_selection_is_auto = False
        if workspace._roster_syncing or workspace._media_ctrl is None:
            return
        state = workspace._media_ctrl.select_show(state_index)
        if state is None:
            return
        workspace._ensure_check_bindings(state)
        workspace._populate_preview(state)
        workspace._update_action_bar()

    def on_roster_check_toggled(self, state_index: int, checked: bool) -> None:
        workspace = self._workspace
        if workspace._roster_syncing:
            return
        states = workspace._current_states()
        if not (0 <= state_index < len(states)):
            return
        state = states[state_index]
        self.set_state_checked(state, checked)
        workspace._roster_panel.refresh_state(state_index)
        workspace._update_action_bar()

    def set_state_checked(self, state, checked: bool) -> None:
        workspace = self._workspace
        state.checked = checked
        workspace._ensure_check_bindings(state)
        can_queue = _is_state_queue_approvable(state, media_type=workspace._media_type)
        for index, preview in enumerate(state.preview_items):
            binding = state.check_vars.get(str(index))
            if binding is None or not hasattr(binding, "set"):
                continue
            binding.set(bool(checked and can_queue and preview.is_actionable))

        if workspace._selected_state() is state:
            workspace._populate_preview(state)

    def on_table_current_changed(self, current: QModelIndex) -> None:
        workspace = self._workspace
        if workspace._preview_syncing:
            return
        state = workspace._selected_state()
        if state is None:
            return
        if current is not None and current.isValid():
            preview_index = workspace._work_panel.model.preview_index_at(current.row())
            if preview_index is not None and 0 <= preview_index < len(state.preview_items):
                state.selected_index = preview_index
        workspace._update_action_bar()

    def set_roster_check_state(self, state_index: int, checked: bool) -> None:
        workspace = self._workspace
        if workspace._roster_syncing:
            return
        self.on_roster_check_toggled(state_index, checked)
