"""State lookup and work-panel population helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex

from ...engine import ScanState
from ._episode_table_model import ROW_DATA_ROLE
from ._media_helpers import state_key as _state_key


def _preview_index_for_row(state, guide_row) -> int | None:
    """Index of the guide row's primary file in state.preview_items."""
    primary = guide_row.primary_file
    if primary is None:
        return None
    for index, item in enumerate(state.preview_items):
        if item is primary:
            return index
    return None


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
        workspace._automux.on_state_shown(state)

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
        if kind != "episode":
            return
        row_data = index.data(ROW_DATA_ROLE)
        if row_data is not None and row_data.status_text == "Missing File":
            return    # ghost rows have no expansion (R2 M5); inline Assign covers them
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
        if model.row_kind_at(index.row()) != "episode":
            return
        row_data = index.data(ROW_DATA_ROLE)
        if row_data is not None and row_data.status_text == "Missing File":
            return    # ghost rows have no expansion (R2 M5); inline Assign covers them
        view = workspace._work_panel.table_view
        row = index.row()
        if model.expanded_row() == row:
            self._close_expansion()
            return
        self._close_expansion()
        model.set_expanded_row(row)
        view.openPersistentEditor(model.index(row, 0))
        # set_expanded_row's dataChanged fired (and the view relaid out the
        # row) before the editor above existed, so the delegate's sizeHint
        # fell back to _FALLBACK_EXPANDED_HEIGHT_U instead of the real
        # editor height -- every row below sat at the wrong offset. Re-notify
        # now that the editor is registered so the view re-measures against
        # the actual card immediately, instead of leaving that correction to
        # land on some later, indirectly-triggered relayout (the "expands,
        # then after a delay snaps" viewport lurch, round5 Task 9).
        model.notify_expanded_row_changed()
        guide_row = model.guide_row_at(row)
        if guide_row is not None:
            workspace._work_panel.set_episode_overview(guide_row.overview, guide_row.air_date)

    def _close_expansion(self) -> None:
        workspace = self._workspace
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        current = model.expanded_row()
        if current is None:
            return
        model.set_expanded_row(None)
        view.closePersistentEditor(model.index(current, 0))
        workspace._work_panel.clear_episode_overview()

    def on_inline_row_action(self, index: QModelIndex, action_id: str) -> None:
        """Route an inline row action (e.g. missing-file "assign_file", or an
        unmapped/duplicate row's "assign_unmapped") through the coordinator,
        without requiring the row to be expanded first (M7, R2 M2)."""
        workspace = self._workspace
        if not index.isValid():
            return
        model = workspace._work_panel.model
        state = model.state()
        if state is None:
            return
        if action_id == "assign_unmapped":
            preview_index = model.preview_index_at(index.row())
            if preview_index is None or not (0 <= preview_index < len(state.preview_items)):
                return
            workspace._action_coordinator.assign_unmapped_file(
                state, state.preview_items[preview_index]
            )
            return
        guide_row = model.guide_row_at(index.row())
        if guide_row is not None:
            workspace._action_coordinator.handle_episode_row_action(state, guide_row, action_id)

    def _above_fold_ids(self, model, row: int) -> tuple[str, ...]:
        """The collapsed row's inline-strip action ids, forwarded to the card
        so the expansion header hosts the SAME buttons (single source of
        truth: the model's row_data)."""
        row_data = model.row_data_at(row)
        if row_data is None:
            return ()
        return tuple(aid for aid, _label in row_data.inline_actions)

    def _feed_card(self, card, state, guide_row, above_fold_ids) -> int | None:
        """Populate an expansion card from the guide row, re-adding the
        AutoMux tracks widget below the file paths. Returns the preview
        index (None when the row has no primary file)."""
        workspace = self._workspace
        preview_index = _preview_index_for_row(state, guide_row)
        if preview_index is not None and preview_index not in state.mux_opt_outs:
            mux_plan = state.mux_plans.get(preview_index)
        else:
            mux_plan = None
        card.show_episode(
            state, guide_row, mux_plan=mux_plan,
            preview_index=preview_index, above_fold_ids=above_fold_ids,
        )
        if preview_index is not None:
            tracks = workspace._automux.tracks_widget_for(state, preview_index)
            if tracks is not None:
                card.add_tracks_widget(tracks)
        return preview_index

    def expansion_card_for_index(self, index: QModelIndex):
        from ._episode_expansion import EpisodeExpansionCard

        workspace = self._workspace
        model = workspace._work_panel.model
        state = model.state()
        if state is None:
            return None
        card = EpisodeExpansionCard()
        row = index.row()
        guide_row = model.guide_row_at(row)
        if guide_row is None:
            return None
        preview_index = self._feed_card(
            card, state, guide_row, self._above_fold_ids(model, row)
        )
        card.action_requested.connect(
            lambda action_id, s=state, r=guide_row: workspace._action_coordinator.handle_episode_row_action(
                s, r, action_id
            )
        )
        card.collapse_requested.connect(self._close_expansion)
        card.open_dir_requested.connect(workspace._open_directory)
        if preview_index is not None:
            card.mux_optout_toggled.connect(
                lambda s=state, pi=preview_index: workspace._action_coordinator.toggle_episode_mux_optout(
                    s, pi
                )
            )
        return card

    def refresh_expansion_card(self) -> None:
        """Re-show the currently expanded row's card in place (e.g. after a
        per-episode AutoMux opt-out toggle) so its opt-out button label and
        header follow the fresh session state."""
        workspace = self._workspace
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        row = model.expanded_row()
        if row is None:
            return
        card = view.indexWidget(model.index(row, 0))
        state = model.state()
        guide_row = model.guide_row_at(row)
        if card is None or state is None or guide_row is None:
            return
        self._feed_card(card, state, guide_row, self._above_fold_ids(model, row))

    def update_preview_master_state(self, state: ScanState | None) -> None:
        self._workspace._work_panel.update_master_state(state)
