"""UI construction helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QStackedWidget, QVBoxLayout, QWidget

from ._work_panel import MediaWorkPanel
from ._media_workspace_roster import MediaWorkspaceRosterPanel
from .empty_state import EmptyStateWidget
from .scan_progress import ScanProgressWidget


class MediaWorkspaceUiCoordinator:
    def __init__(self, workspace: Any, *, empty_index: int) -> None:
        self._workspace = workspace
        self._empty_index = empty_index

    def build_ui(self) -> None:
        workspace = self._workspace
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        workspace._stack = QStackedWidget()
        layout.addWidget(workspace._stack)

        self._build_empty_state()
        self._build_scanning_state()
        self._build_ready_state()
        self._restore_splitter_positions()
        workspace._splitter.splitterMoved.connect(workspace._on_splitter_moved)
        workspace._stack.setCurrentIndex(self._empty_index)

    def _build_empty_state(self) -> None:
        workspace = self._workspace
        workspace._empty_state = EmptyStateWidget(
            media_type=workspace._media_type,
            settings_service=workspace._settings,
        )
        workspace._empty_state.folder_selected.connect(workspace._on_folder_selected)
        workspace._stack.addWidget(workspace._empty_state)

    def _build_scanning_state(self) -> None:
        workspace = self._workspace
        workspace._scan_progress = ScanProgressWidget(media_type=workspace._media_type)
        workspace._scan_progress.cancel_requested.connect(workspace._on_cancel_scan)
        workspace._stack.addWidget(workspace._scan_progress)

    def _build_ready_state(self) -> None:
        workspace = self._workspace
        ready_container = QWidget()
        ready_layout = QVBoxLayout(ready_container)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(0)

        workspace._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._build_roster_panel()
        self._build_work_panel()

        workspace._splitter.addWidget(workspace._roster_panel)
        workspace._splitter.addWidget(workspace._work_panel)
        workspace._splitter.setSizes([380, 860])
        workspace._splitter.setChildrenCollapsible(False)

        ready_layout.addWidget(workspace._splitter, stretch=1)
        workspace._stack.addWidget(ready_container)

    def _build_roster_panel(self) -> None:
        workspace = self._workspace
        workspace._roster_panel = MediaWorkspaceRosterPanel(
            media_type=workspace._media_type,
            settings_service=workspace._settings,
            tmdb_provider=workspace._tmdb_provider,
        )
        workspace._roster_master_check = workspace._roster_panel.master_check
        workspace._roster_selection_summary = workspace._roster_panel.selection_summary
        workspace._roster_queue_btn = workspace._roster_panel.queue_button
        workspace._roster_master_check.stateChanged.connect(workspace._on_roster_master_changed)
        workspace._roster_queue_btn.clicked.connect(workspace._queue_checked)
        workspace._roster_panel.state_selected.connect(workspace._on_roster_state_selected)
        workspace._roster_panel.check_toggled.connect(workspace._on_roster_check_toggled)
        workspace._roster_panel.group_toggled.connect(workspace._on_roster_group_toggled)
        workspace._set_roster_queue_button_text("Queue Checked")

    def _build_work_panel(self) -> None:
        workspace = self._workspace
        workspace._work_panel = MediaWorkPanel(
            media_type=workspace._media_type,
            settings_service=workspace._settings,
            tmdb_provider=workspace._tmdb_provider,
            guide_provider=(
                workspace._media_ctrl.episode_guide_for_state
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "episode_guide_for_state")
                else None
            ),
            cached_guide_provider=(
                workspace._media_ctrl.cached_episode_guide_for_state
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "cached_episode_guide_for_state")
                else None
            ),
            guide_builder=(
                workspace._media_ctrl.build_episode_guide_snapshot
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "build_episode_guide_snapshot")
                else None
            ),
            guide_store=(
                workspace._media_ctrl.store_episode_guide
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "store_episode_guide")
                else None
            ),
        )
        panel = workspace._work_panel
        panel.setProperty("panelVariant", "square")
        workspace._fix_match_btn = panel.fix_match_button
        workspace._queue_inline_btn = panel.primary_action_button
        workspace._fix_match_btn.clicked.connect(workspace._fix_match)
        workspace._queue_inline_btn.clicked.connect(workspace._activate_selected_primary_action)
        panel.automux_button.clicked.connect(workspace._toggle_automux)
        workspace._queue_inline_btn.setText(workspace._queue_selected_label())
        workspace._sync_action_button_metrics()

        # The panel self-toggles the model on header clicks; the workspace
        # coordinator owns the shared collapsed set + footer refresh instead,
        # so drop the panel's internal connection to avoid a double toggle.
        panel.table_view.header_clicked.disconnect(panel._on_header_clicked)

        panel.filter_changed.connect(workspace._on_episode_filter_changed)
        panel.search_changed.connect(workspace._on_episode_search_changed)
        panel.episode_search_changed.connect(workspace._on_episode_code_search_changed)
        panel.approve_all_clicked.connect(workspace._approve_all_episode_mappings)
        panel.unassign_all_clicked.connect(workspace._unassign_all_episode_mappings)
        panel.season_chip_clicked.connect(panel.scroll_to_season)
        panel.table_view.chevron_clicked.connect(workspace._on_table_expand_requested)
        panel.table_view.expand_key_pressed.connect(workspace._on_table_expand_requested)
        panel.inline_row_action.connect(workspace._on_inline_row_action)
        panel.table_view.header_clicked.connect(workspace._on_table_section_toggled)
        panel.table_view.clicked.connect(workspace._on_table_row_clicked)
        panel.table_view.selectionModel().currentChanged.connect(workspace._on_table_current_changed)
        panel._delegate.expansion_card_provider = workspace._expansion_card_for_index

        panel.bulk_assign_requested.connect(workspace._enter_bulk_assign)
        panel.bulk_panel.apply_requested.connect(workspace._on_bulk_apply)
        panel.bulk_panel.cancelled.connect(workspace._on_bulk_cancel)

    def _restore_splitter_positions(self) -> None:
        workspace = self._workspace
        if workspace._settings:
            positions = workspace._settings.splitter_positions
            if positions and len(positions) == 2:
                workspace._splitter.setSizes(positions)
