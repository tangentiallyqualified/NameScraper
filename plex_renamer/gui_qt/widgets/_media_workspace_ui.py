"""UI construction helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QStackedWidget, QVBoxLayout, QWidget

from ._media_workspace_preview import MediaWorkspacePreviewPanel
from ._media_workspace_roster import MediaWorkspaceRosterPanel
from .empty_state import EmptyStateWidget
from .media_detail_panel import MediaDetailPanel
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
        self._build_preview_panel()
        self._build_detail_panel()

        workspace._splitter.addWidget(workspace._roster_panel)
        workspace._splitter.addWidget(workspace._preview_panel)
        workspace._splitter.addWidget(workspace._detail_panel)
        workspace._splitter.setSizes([320, 540, 380])
        workspace._splitter.setChildrenCollapsible(False)

        ready_layout.addWidget(workspace._splitter, stretch=1)
        workspace._stack.addWidget(ready_container)

    def _build_roster_panel(self) -> None:
        workspace = self._workspace
        workspace._roster_panel = MediaWorkspaceRosterPanel(
            media_type=workspace._media_type,
            settings_service=workspace._settings,
            tmdb_provider=workspace._tmdb_provider,
            set_item_check_state_callback=lambda item, checked: workspace._set_item_check_state(
                item,
                checked,
                preview=False,
            ),
            prompt_assign_season_callback=workspace._prompt_assign_season,
        )
        workspace._roster_list = workspace._roster_panel.list_widget
        workspace._roster_master_check = workspace._roster_panel.master_check
        workspace._roster_selection_summary = workspace._roster_panel.selection_summary
        workspace._roster_queue_btn = workspace._roster_panel.queue_button
        workspace._roster_master_check.stateChanged.connect(workspace._on_roster_master_changed)
        workspace._roster_queue_btn.clicked.connect(workspace._queue_checked)
        workspace._roster_list.itemChanged.connect(workspace._on_roster_item_changed)
        workspace._roster_list.itemClicked.connect(workspace._on_roster_item_clicked)
        workspace._roster_list.currentItemChanged.connect(workspace._on_roster_current_item_changed)
        workspace._set_roster_queue_button_text("Queue Checked")

    def _build_preview_panel(self) -> None:
        workspace = self._workspace
        workspace._preview_panel = MediaWorkspacePreviewPanel(
            media_type=workspace._media_type,
            settings_service=workspace._settings,
            set_item_check_state_callback=lambda item, checked: workspace._set_item_check_state(
                item,
                checked,
                preview=True,
            ),
            episode_filter_changed_callback=lambda: (
                workspace._populate_preview(workspace._selected_state())
                if workspace._selected_state() is not None
                else None
            ),
            approve_episode_callback=workspace._approve_episode_mapping,
            fix_episode_callback=workspace._prompt_fix_episode_mapping,
            approve_all_episode_callback=workspace._approve_all_episode_mappings,
            episode_guide_provider=(
                workspace._media_ctrl.episode_guide_for_state
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "episode_guide_for_state")
                else None
            ),
        )
        workspace._preview_list = workspace._preview_panel.list_widget
        workspace._preview_master_check = workspace._preview_panel.master_check
        workspace._preview_check_summary = workspace._preview_panel.check_summary
        workspace._fix_match_btn = workspace._preview_panel.fix_match_button
        workspace._queue_inline_btn = workspace._preview_panel.primary_action_button
        workspace._folder_plan_label = workspace._preview_panel.folder_plan_label
        workspace._preview_summary = workspace._preview_panel.summary_label
        workspace._sticky_header = workspace._preview_panel.sticky_header
        workspace._preview_master_check.stateChanged.connect(workspace._on_preview_master_changed)
        workspace._fix_match_btn.clicked.connect(workspace._fix_match)
        workspace._queue_inline_btn.clicked.connect(workspace._activate_selected_primary_action)
        workspace._queue_inline_btn.setText(workspace._queue_selected_label())
        workspace._sync_action_button_metrics()
        workspace._preview_list.itemChanged.connect(workspace._on_preview_item_changed)
        workspace._preview_list.currentItemChanged.connect(workspace._on_preview_current_item_changed)
        workspace._preview_list.itemClicked.connect(workspace._on_preview_item_clicked)

    def _build_detail_panel(self) -> None:
        workspace = self._workspace
        workspace._detail_panel = MediaDetailPanel(
            tmdb_provider=workspace._tmdb_provider,
            settings_service=workspace._settings,
        )
        workspace._detail_panel.setProperty("panelVariant", "square")
        workspace._detail_panel.setMinimumWidth(340)
        workspace._preview_panel.fix_match_button.hide()
        workspace._preview_panel.primary_action_button.hide()
        workspace._fix_match_btn = workspace._detail_panel.fix_match_button
        workspace._queue_inline_btn = workspace._detail_panel.primary_action_button
        workspace._queue_preflight_label = workspace._detail_panel.queue_preflight_label
        workspace._fix_match_btn.clicked.connect(workspace._fix_match)
        workspace._queue_inline_btn.clicked.connect(workspace._activate_selected_primary_action)
        workspace._queue_inline_btn.setText(workspace._queue_selected_label())
        workspace._sync_action_button_metrics()

    def _restore_splitter_positions(self) -> None:
        workspace = self._workspace
        if workspace._settings:
            positions = workspace._settings.splitter_positions
            if positions and len(positions) == 3:
                workspace._splitter.setSizes(positions)
