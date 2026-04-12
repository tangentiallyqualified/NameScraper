"""Lifecycle and state-switching helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize


class MediaWorkspaceLifecycleCoordinator:
    def __init__(
        self,
        workspace: Any,
        *,
        empty_index: int,
        scanning_index: int,
        ready_index: int,
    ) -> None:
        self._workspace = workspace
        self._empty_index = empty_index
        self._scanning_index = scanning_index
        self._ready_index = ready_index

    def show_empty(self) -> None:
        workspace = self._workspace
        workspace._scan_progress.stop()
        workspace._detail_panel.clear_metadata_cache()
        workspace._stack.setCurrentIndex(self._empty_index)
        workspace._empty_state.refresh_recent_folders()

    def show_scanning(self) -> None:
        workspace = self._workspace
        workspace._scan_progress.start()
        workspace._detail_panel.clear_metadata_cache()
        workspace._stack.setCurrentIndex(self._scanning_index)

    def show_ready(self) -> None:
        workspace = self._workspace
        workspace._scan_progress.stop()
        workspace._stack.setCurrentIndex(self._ready_index)
        workspace.refresh_from_controller()

    def apply_settings(self) -> None:
        workspace = self._workspace
        compact = workspace._settings is not None and workspace._settings.view_mode == "compact"
        workspace._roster_list.setIconSize(QSize(32, 46) if compact else QSize(42, 60))
        workspace.refresh_from_controller()
        workspace._detail_panel.refresh_current()

    def on_folder_selected(self, path: str) -> None:
        workspace = self._workspace
        workspace.folder_selected.emit(path)
        self.show_scanning()

    def on_cancel_scan(self) -> None:
        workspace = self._workspace
        if workspace._media_ctrl is None:
            self.show_empty()
            return
        if workspace._media_ctrl.cancel_scan():
            workspace.status_message.emit("Cancelling scan...", 3000)
            return
        workspace.status_message.emit("No active scan to cancel.", 3000)

    def on_splitter_moved(self) -> None:
        workspace = self._workspace
        if workspace._settings:
            workspace._settings.splitter_positions = list(workspace._splitter.sizes())
