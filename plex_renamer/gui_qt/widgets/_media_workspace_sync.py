"""Selection and checkbox synchronization helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ._media_workspace_roster import _CHECKED_ROLE
from ._media_helpers import is_state_queue_approvable as _is_state_queue_approvable
from ._workspace_widgets import (
    EpisodeGuideRowWidget as _EpisodeGuideRowWidget,
    PreviewRowWidget as _PreviewRowWidget,
    RosterRowWidget as _RosterRowWidget,
)


class MediaWorkspaceSyncCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def on_roster_current_item_changed(self, current: QListWidgetItem | None) -> None:
        workspace = self._workspace
        if workspace._pending_roster_selection_auto is not None:
            workspace._roster_selection_is_auto = workspace._pending_roster_selection_auto
            workspace._pending_roster_selection_auto = None
        elif current is not None:
            workspace._roster_selection_is_auto = False
        if workspace._roster_syncing or workspace._media_ctrl is None or current is None:
            return
        self.sync_row_selection(workspace._roster_list)
        row = current.data(Qt.ItemDataRole.UserRole)
        if row is None:
            return
        state = workspace._media_ctrl.select_show(row)
        if state is None:
            return
        workspace._ensure_check_bindings(state)
        workspace._populate_preview(state)
        workspace._render_detail(state)
        workspace._update_action_bar()

    def on_roster_item_changed(self, item: QListWidgetItem) -> None:
        workspace = self._workspace
        if workspace._roster_syncing:
            return
        states = workspace._current_states()
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is None or not (0 <= row < len(states)):
            return
        state = states[row]
        checked = bool(item.data(_CHECKED_ROLE))
        self.set_state_checked(state, checked)
        widget = workspace._roster_list.itemWidget(item)
        if isinstance(widget, _RosterRowWidget):
            widget.set_checked(state.checked)
        workspace._update_action_bar()
        if row == workspace._roster_list.currentRow():
            workspace._render_detail(state)

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

    def on_preview_current_item_changed(self, current: QListWidgetItem | None) -> None:
        workspace = self._workspace
        if workspace._preview_syncing:
            return
        state = workspace._selected_state()
        if state is None:
            return
        preview = None
        if current is not None:
            index = current.data(Qt.ItemDataRole.UserRole)
            if index is not None and 0 <= index < len(state.preview_items):
                state.selected_index = index
                preview = state.preview_items[index]
        self.sync_row_selection(workspace._preview_list)
        workspace._render_detail(state, preview)

    def on_preview_item_changed(self, item: QListWidgetItem) -> None:
        workspace = self._workspace
        if workspace._preview_syncing:
            return
        state = workspace._selected_state()
        if state is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        binding = state.check_vars.get(str(index))
        if binding is None:
            return
        binding.set(bool(item.data(_CHECKED_ROLE)))
        widget = workspace._preview_list.itemWidget(item)
        if isinstance(widget, _PreviewRowWidget):
            widget.set_checked(binding.get())
        state.checked = any(
            state.check_vars[str(i)].get()
            for i, preview in enumerate(state.preview_items)
            if preview.is_actionable
        )
        self._sync_current_roster_row_checked(state.checked)
        workspace._render_detail(state, state.preview_items[index])
        workspace._update_preview_master_state(state)
        workspace._update_action_bar()

    def on_preview_master_changed(self, check_state: int) -> None:
        workspace = self._workspace
        if workspace._preview_panel.master_syncing:
            return
        state = workspace._selected_state()
        if state is None:
            return
        target = check_state == int(Qt.CheckState.Checked.value)
        workspace._preview_syncing = True
        try:
            for index, preview in enumerate(state.preview_items):
                if not preview.is_actionable:
                    continue
                binding = state.check_vars.get(str(index))
                if binding is not None:
                    binding.set(target)
                for row in range(workspace._preview_list.count()):
                    item = workspace._preview_list.item(row)
                    if item is not None and item.data(Qt.ItemDataRole.UserRole) == index:
                        item.setData(_CHECKED_ROLE, target)
                        widget = workspace._preview_list.itemWidget(item)
                        if isinstance(widget, _PreviewRowWidget):
                            widget.set_checked(target)
                        break
        finally:
            workspace._preview_syncing = False
        state.checked = target
        self._sync_current_roster_row_checked(state.checked)
        workspace._update_preview_master_state(state)
        workspace._update_action_bar()

    def set_item_check_state(self, item: QListWidgetItem, checked: bool, *, preview: bool) -> None:
        workspace = self._workspace
        syncing_attr = "_preview_syncing" if preview else "_roster_syncing"
        if getattr(workspace, syncing_attr):
            return
        setattr(workspace, syncing_attr, True)
        item.setData(_CHECKED_ROLE, checked)
        setattr(workspace, syncing_attr, False)
        if preview:
            self.on_preview_item_changed(item)
        else:
            self.on_roster_item_changed(item)

    def sync_row_selection(self, list_widget: QListWidget) -> None:
        current = list_widget.currentItem()
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            widget = list_widget.itemWidget(item)
            if isinstance(widget, (_RosterRowWidget, _PreviewRowWidget, _EpisodeGuideRowWidget)):
                widget.set_selected(item is current)

    def _sync_current_roster_row_checked(self, checked: bool) -> None:
        workspace = self._workspace
        current_roster_item = workspace._roster_list.item(workspace._roster_list.currentRow())
        if current_roster_item is None or current_roster_item.data(Qt.ItemDataRole.UserRole) is None:
            return
        workspace._roster_syncing = True
        current_roster_item.setData(_CHECKED_ROLE, checked)
        workspace._roster_syncing = False
        roster_widget = workspace._roster_list.itemWidget(current_roster_item)
        if isinstance(roster_widget, _RosterRowWidget):
            roster_widget.set_checked(checked)
