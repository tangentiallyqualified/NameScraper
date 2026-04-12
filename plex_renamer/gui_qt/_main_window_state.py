"""State and settings helpers for the main window."""

from __future__ import annotations

from logging import Logger
from pathlib import Path
from typing import Any


class MainWindowStateCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        tv_index: int,
        movies_index: int,
        queue_index: int,
        history_index: int,
        logger: Logger,
    ) -> None:
        self._window = window
        self._tv_index = tv_index
        self._movies_index = movies_index
        self._queue_index = queue_index
        self._history_index = history_index
        self._logger = logger

    def refresh_media_workspaces(self) -> None:
        window = self._window
        window._tv_workspace.apply_settings()
        window._movie_workspace.apply_settings()

    def apply_view_mode(self, mode: str) -> None:
        window = self._window
        checked = mode == "compact"
        window.settings_service.view_mode = mode
        window._compact_action.blockSignals(True)
        window._compact_action.setChecked(checked)
        window._compact_action.blockSignals(False)
        window._settings_tab.sync_view_mode(mode)
        self.refresh_media_workspaces()

    def apply_companion_visibility(self, checked: bool) -> None:
        window = self._window
        window.settings_service.show_companion_files = checked
        window._companion_action.blockSignals(True)
        window._companion_action.setChecked(checked)
        window._companion_action.blockSignals(False)
        window._settings_tab.sync_companion_visibility(checked)
        self.refresh_media_workspaces()

    def apply_discovery_visibility(self, checked: bool) -> None:
        window = self._window
        window.settings_service.show_discovery_info = checked
        window._settings_tab.sync_discovery_visibility(checked)
        self.refresh_media_workspaces()

    def on_language_changed(self, tag: str) -> None:
        window = self._window
        window.settings_service.match_language = tag
        window._settings_tab.sync_language(tag)
        window._invalidate_tmdb()
        self.refresh_media_workspaces()
        window.statusBar().showMessage(f"TMDB language updated to {tag}.", 3000)

    def on_threshold_changed(self, value: float) -> None:
        window = self._window
        window.settings_service.auto_accept_threshold = value
        window.media_ctrl.apply_runtime_settings()
        self.refresh_media_workspaces()
        window.statusBar().showMessage(f"Auto-accept threshold updated to {value:.2f}.", 3000)

    def switch_to_tab(self, index: int) -> None:
        self._window._tabs.setCurrentIndex(index)

    def rebuild_recent_menus(self) -> None:
        window = self._window

        window._recent_tv_menu.clear()
        for folder in window.settings_service.recent_tv_folders:
            path = Path(folder)
            action = window._recent_tv_menu.addAction(f"{path.name}  ({path})")
            action.triggered.connect(
                lambda _=False, selected_folder=folder: window._tv_workspace.load_folder(selected_folder)
            )
        window._recent_tv_menu.setEnabled(bool(window.settings_service.recent_tv_folders))

        window._recent_movie_menu.clear()
        for folder in window.settings_service.recent_movie_folders:
            path = Path(folder)
            action = window._recent_movie_menu.addAction(f"{path.name}  ({path})")
            action.triggered.connect(
                lambda _=False, selected_folder=folder: window._movie_workspace.load_folder(selected_folder)
            )
        window._recent_movie_menu.setEnabled(bool(window.settings_service.recent_movie_folders))

    def on_tab_changed(self, index: int) -> None:
        window = self._window
        self.capture_active_snapshot()

        if index == self._queue_index:
            window._queue_tab._model.clear_checked()
            window._queue_tab.refresh()
        elif index == self._history_index:
            window._history_tab._model.clear_checked()
            window._history_tab.refresh()
        elif index == self._tv_index:
            if window._tv_snapshot is not None:
                window.media_ctrl.restore_tv_from_tab_switch(window._tv_snapshot)
                window._tv_workspace.refresh_from_controller()
            elif window._tv_needs_queue_refresh and window._tv_workspace.is_showing_ready():
                window._tv_workspace.refresh_from_controller()
            window._tv_needs_queue_refresh = False
        elif index == self._movies_index:
            if window._movie_snapshot is not None:
                window.media_ctrl.restore_movie_from_tab_switch(window._movie_snapshot)
                window._movie_workspace.refresh_from_controller()
            elif window._movie_needs_queue_refresh and window._movie_workspace.is_showing_ready():
                window._movie_workspace.refresh_from_controller()
            window._movie_needs_queue_refresh = False

        self._logger.debug("Tab switched to %d", index)

    def capture_active_snapshot(self) -> None:
        window = self._window
        if window.media_ctrl.active_content_mode == "tv":
            window._tv_snapshot = window.media_ctrl.snapshot_tv_for_tab_switch()
        elif window.media_ctrl.active_content_mode == "movie":
            window._movie_snapshot = window.media_ctrl.snapshot_movie_for_tab_switch()
