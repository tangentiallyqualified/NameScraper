"""State lookup and panel-population helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from ...engine import ScanState
from ._media_helpers import state_key as _state_key
from ._media_workspace_preview import _PREVIEW_ENTRY_KIND_ROLE, _PREVIEW_SECTION_ROLE
from ._media_workspace_roster import _ROSTER_ENTRY_KEY_ROLE, _ROSTER_ENTRY_KIND_ROLE


class MediaWorkspaceStateCoordinator:
    def __init__(self, workspace: Any, *, folder_section_key: str) -> None:
        self._workspace = workspace
        self._folder_section_key = folder_section_key

    def sync_roster_items(self, states: list[ScanState]) -> None:
        workspace = self._workspace
        workspace._roster_panel.sync_items(states, collapsed_groups=workspace._roster_collapsed)

    def find_roster_item_by_index(self, index: int) -> QListWidgetItem | None:
        return self._workspace._roster_panel.find_item_by_index(index)

    def set_roster_current_item(self, item: QListWidgetItem, *, auto_selected: bool) -> None:
        workspace = self._workspace
        if workspace._roster_list.currentItem() is item:
            workspace._roster_selection_is_auto = auto_selected
            workspace._pending_roster_selection_auto = None
            return
        workspace._pending_roster_selection_auto = auto_selected
        workspace._roster_list.setCurrentItem(item)
        if workspace._pending_roster_selection_auto is not None:
            workspace._roster_selection_is_auto = auto_selected
            workspace._pending_roster_selection_auto = None

    def current_states(self) -> list[ScanState]:
        workspace = self._workspace
        if workspace._media_ctrl is None:
            return []
        if workspace._media_type == "movie":
            return list(workspace._media_ctrl.movie_library_states)
        return list(workspace._media_ctrl.batch_states)

    def selected_state(self) -> ScanState | None:
        workspace = self._workspace
        states = self.current_states()
        item = workspace._roster_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and 0 <= index < len(states):
            return states[index]
        return None

    def on_roster_item_clicked(self, item: QListWidgetItem) -> None:
        workspace = self._workspace
        if item.data(_ROSTER_ENTRY_KIND_ROLE) != "header":
            return
        key = item.data(_ROSTER_ENTRY_KEY_ROLE) or ""
        group = key.removeprefix("header:")
        if not group:
            return
        workspace._roster_collapsed[group] = not workspace._roster_collapsed.get(group, False)
        states = self.current_states()
        if states:
            workspace._roster_syncing = True
            try:
                self.sync_roster_items(states)
            finally:
                workspace._roster_syncing = False

    def populate_preview(self, state: ScanState) -> None:
        workspace = self._workspace
        workspace._preview_syncing = True
        workspace._preview_list.setUpdatesEnabled(False)
        workspace._preview_panel.populate_from_state(
            state,
            preview_group_state=workspace._preview_group_state,
            folder_section_key=self._folder_section_key,
            ensure_check_bindings=workspace._ensure_check_bindings,
            folder_plan_text=workspace._folder_plan_text,
            folder_preview_data=workspace._folder_preview_data,
        )
        workspace._preview_syncing = False
        workspace._preview_list.setUpdatesEnabled(True)
        workspace._sync_row_selection(workspace._preview_list)
        self.update_preview_master_state(state)

    def warm_preview_cache(self, states: list[ScanState], active_state: ScanState | None) -> None:
        workspace = self._workspace
        if workspace._media_type != "tv" or active_state is None:
            return
        targets = [
            state
            for state in states
            if state is not active_state
            and state.preview_items
            and not workspace._preview_panel.has_current_render(
                state,
                folder_preview=workspace._folder_preview_data(state),
            )
        ]
        if not targets:
            return

        workspace._preview_syncing = True
        workspace._preview_list.setUpdatesEnabled(False)
        try:
            for state in targets:
                workspace._preview_panel.populate_from_state(
                    state,
                    preview_group_state=workspace._preview_group_state,
                    folder_section_key=self._folder_section_key,
                    ensure_check_bindings=workspace._ensure_check_bindings,
                    folder_plan_text=workspace._folder_plan_text,
                    folder_preview_data=workspace._folder_preview_data,
                )
            workspace._preview_panel.populate_from_state(
                active_state,
                preview_group_state=workspace._preview_group_state,
                folder_section_key=self._folder_section_key,
                ensure_check_bindings=workspace._ensure_check_bindings,
                folder_plan_text=workspace._folder_plan_text,
                folder_preview_data=workspace._folder_preview_data,
            )
        finally:
            workspace._preview_syncing = False
            workspace._preview_list.setUpdatesEnabled(True)
        workspace._sync_row_selection(workspace._preview_list)
        self.update_preview_master_state(active_state)

    def on_preview_item_clicked(self, item: QListWidgetItem) -> None:
        workspace = self._workspace
        if workspace._preview_syncing:
            return
        state = self.selected_state()
        if state is None:
            return
        if item.data(_PREVIEW_ENTRY_KIND_ROLE) != "header":
            return
        section_key = item.data(_PREVIEW_SECTION_ROLE)
        if section_key is None:
            return
        handled = workspace._preview_panel.toggle_section(
            state=state,
            section_key=section_key,
            preview_group_state=workspace._preview_group_state,
        )
        if handled:
            return
        collapsed = workspace._preview_group_state.setdefault(_state_key(state), set())
        if section_key in collapsed:
            collapsed.remove(section_key)
        else:
            collapsed.add(section_key)
        self.populate_preview(state)

    def update_sticky_header(self) -> None:
        self._workspace._preview_panel.update_sticky_header()

    def update_preview_master_state(self, state: ScanState | None) -> None:
        self._workspace._preview_panel.update_master_state(state)
