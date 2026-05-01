"""Refresh and queue-normalization helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from ...engine import ScanState
from ._media_helpers import (
    is_state_queue_approvable as _is_state_queue_approvable,
    roster_group as _roster_group,
    roster_selection_key as _roster_selection_key,
)
from ._workspace_widgets import _CheckBinding


class MediaWorkspaceRefreshCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def refresh_from_controller(self) -> None:
        workspace = self._workspace
        if workspace._media_ctrl is None:
            return

        states = workspace._current_states()
        self.normalize_queue_selection(states)
        selected_state_key = _roster_selection_key(workspace._selected_state())
        workspace._roster_syncing = True
        workspace._roster_list.setUpdatesEnabled(False)
        workspace._sync_roster_items(states)
        workspace._roster_syncing = False
        workspace._roster_list.setUpdatesEnabled(True)

        if not states:
            self._reset_empty_ready_state()
            return

        selected_index = workspace._media_ctrl.library_selected_index
        selection_is_auto = workspace._roster_selection_is_auto
        if selected_state_key is not None:
            matched_index = next(
                (index for index, state in enumerate(states) if _roster_selection_key(state) == selected_state_key),
                None,
            )
            if matched_index is not None:
                selected_index = matched_index

        preferred_focus_index = self.preferred_batch_focus_index(states)
        if preferred_focus_index is not None:
            if selected_state_key is None:
                selected_index = preferred_focus_index
                selection_is_auto = True
            elif (
                selection_is_auto
                and selected_index is not None
                and 0 <= selected_index < len(states)
                and _roster_group(states[selected_index]) not in {"matched", "review"}
            ):
                selected_index = preferred_focus_index
                selection_is_auto = True

        if selected_index is None or not (0 <= selected_index < len(states)):
            selected_index = preferred_focus_index if preferred_focus_index is not None else 0
            selection_is_auto = True
        selected_state = workspace._media_ctrl.select_show(selected_index)

        selected_item = workspace._find_roster_item_by_index(selected_index)
        if selected_item is not None:
            workspace._set_roster_current_item(selected_item, auto_selected=selection_is_auto)

        if selected_state is not None:
            self.ensure_check_bindings(selected_state)
            workspace._populate_preview(selected_state)
            workspace._warm_preview_cache(states, selected_state)
            workspace._render_detail(selected_state, workspace._selected_preview())
        workspace._update_action_bar()
        workspace._sync_row_selection(workspace._roster_list)

    def check_all(self) -> None:
        workspace = self._workspace
        for state in workspace._current_states():
            state.checked = _is_state_queue_approvable(state, media_type=workspace._media_type)
            self.ensure_check_bindings(state)
            for index, preview in enumerate(state.preview_items):
                state.check_vars[str(index)].set(bool(state.checked and preview.is_actionable))
        workspace.refresh_from_controller()

    def uncheck_all(self) -> None:
        workspace = self._workspace
        for state in workspace._current_states():
            state.checked = False
            for index in range(len(state.preview_items)):
                binding = state.check_vars.get(str(index))
                if binding is not None:
                    binding.set(False)
        workspace.refresh_from_controller()

    def ensure_check_bindings(self, state: ScanState) -> None:
        workspace = self._workspace
        for index, item in enumerate(state.preview_items):
            key = str(index)
            if key not in state.check_vars:
                state.check_vars[key] = _CheckBinding(
                    bool(
                        state.checked
                        and item.is_actionable
                        and _is_state_queue_approvable(state, media_type=workspace._media_type)
                    )
                )

    def normalize_queue_selection(self, states: list[ScanState]) -> None:
        workspace = self._workspace
        for state in states:
            if _is_state_queue_approvable(state, media_type=workspace._media_type):
                self.ensure_check_bindings(state)
                actionable_values: list[bool] = []
                for index, item in enumerate(state.preview_items):
                    if not item.is_actionable:
                        continue
                    key = str(index)
                    binding = state.check_vars.get(key)
                    if binding is not None:
                        actionable_values.append(binding.get())
                if actionable_values:
                    state.checked = any(actionable_values)
                elif state.preview_items:
                    state.checked = False
                continue
            state.checked = False
            for binding in state.check_vars.values():
                if hasattr(binding, "set"):
                    binding.set(False)

    def preferred_batch_focus_index(self, states: list[ScanState]) -> int | None:
        if len(states) <= 1:
            return None
        for group in ("matched", "review"):
            for index, state in enumerate(states):
                if _roster_group(state) == group:
                    return index
        return None

    def _reset_empty_ready_state(self) -> None:
        workspace = self._workspace
        workspace._preview_list.clear()
        workspace._folder_plan_label.setText("")
        workspace._set_preview_summary("Preview items will appear here once a scan is ready.")
        workspace._detail_panel.clear()
        workspace._roster_selection_is_auto = False
        workspace._pending_roster_selection_auto = None
        workspace._roster_queue_btn.setEnabled(False)
        workspace._set_roster_queue_button_text("Queue Checked")
        workspace._roster_queue_btn.setToolTip("")
        workspace._update_roster_selection_header([])
        workspace._fix_match_btn.setEnabled(False)
        workspace._fix_match_btn.setText("Fix Match")
        workspace._queue_inline_btn.setEnabled(False)
        workspace._queue_inline_btn.setText(workspace._queue_selected_label())
