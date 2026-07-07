"""State lookup and work-panel population helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex

from ...engine import ScanState
from ._media_helpers import state_key as _state_key


class MediaWorkspaceStateCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def sync_roster_items(self, states: list[ScanState]) -> None:
        workspace = self._workspace
        workspace._roster_panel.sync_items(states, collapsed_groups=workspace._roster_collapsed)

    def set_roster_current_state(self, state_index: int, *, auto_selected: bool) -> None:
        workspace = self._workspace
        if workspace._roster_panel.current_state_index() == state_index:
            workspace._roster_selection_is_auto = auto_selected
            workspace._pending_roster_selection_auto = None
            return
        workspace._pending_roster_selection_auto = auto_selected
        workspace._roster_panel.set_current_state(state_index)
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
        index = workspace._roster_panel.current_state_index()
        if index is not None and 0 <= index < len(states):
            return states[index]
        return None

    def on_roster_group_toggled(self, group: str) -> None:
        workspace = self._workspace
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

    def show_in_work_panel(self, state: ScanState) -> None:
        workspace = self._workspace
        workspace._action_coordinator.discard_bulk_assign_on_state_change(state)
        if state.preview_items:
            workspace._ensure_check_bindings(state)
        collapsed = workspace._preview_group_state.setdefault(_state_key(state), set())
        workspace._preview_syncing = True
        try:
            workspace._work_panel.show_state(
                state,
                collapsed_sections=collapsed,
                folder_preview=workspace._folder_preview_data(state),
            )
        finally:
            workspace._preview_syncing = False
        self.update_preview_master_state(state)

    def on_table_section_toggled(self, section_key: str) -> None:
        workspace = self._workspace
        if workspace._preview_syncing:
            return
        workspace._work_panel.model.toggle_section(section_key)
        workspace._work_panel.update_footer()

    def on_table_row_clicked(self, index: QModelIndex) -> None:
        """A second click on the already-current episode/movie row expands it
        (Qt does not refire currentChanged for the same row)."""
        workspace = self._workspace
        if workspace._preview_syncing or not index.isValid():
            return
        model = workspace._work_panel.model
        kind = model.row_kind_at(index.row())
        if kind not in {"episode", "movie-file"}:
            return
        if index != workspace._work_panel.table_view.currentIndex():
            return
        if model.expanded_row() == index.row():
            return
        self.on_table_expand_requested(index)

    def on_table_expand_requested(self, index: QModelIndex) -> None:
        workspace = self._workspace
        if not index.isValid():
            return
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        row = index.row()
        if model.expanded_row() == row:
            self._close_expansion()
            return
        self._close_expansion()
        model.set_expanded_row(row)
        view.openPersistentEditor(model.index(row, 0))

    def _close_expansion(self) -> None:
        workspace = self._workspace
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        current = model.expanded_row()
        if current is None:
            return
        model.set_expanded_row(None)
        view.closePersistentEditor(model.index(current, 0))

    def expansion_card_for_index(self, index: QModelIndex):
        from ._episode_expansion import EpisodeExpansionCard

        workspace = self._workspace
        model = workspace._work_panel.model
        state = model.state()
        if state is None:
            return None
        card = EpisodeExpansionCard()
        row = index.row()
        kind = model.row_kind_at(row)
        if kind == "movie-file":
            preview_index = model.preview_index_at(row)
            if preview_index is None or not (0 <= preview_index < len(state.preview_items)):
                return None
            card.show_movie(state, state.preview_items[preview_index])
        else:
            guide_row = model.guide_row_at(row)
            if guide_row is None:
                return None
            card.show_episode(state, guide_row)
            card.action_requested.connect(
                lambda action_id, s=state, r=guide_row: workspace._action_coordinator.handle_episode_row_action(
                    s, r, action_id
                )
            )
        card.collapse_requested.connect(self._close_expansion)
        card.open_dir_requested.connect(workspace._open_directory)
        return card

    def update_preview_master_state(self, state: ScanState | None) -> None:
        self._workspace._work_panel.update_master_state(state)
