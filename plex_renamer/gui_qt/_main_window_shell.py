"""Remaining shell helpers for the main window."""

from __future__ import annotations

from typing import Any

from . import _scale


class MainWindowShellCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        tv_index: int,
        movies_index: int,
    ) -> None:
        self._window = window
        self._tv_index = tv_index
        self._movies_index = movies_index

    def open_folder(self, media_type: str) -> None:
        """Switch to the appropriate tab and trigger its folder picker."""
        window = self._window
        if media_type == "tv":
            window._switch_to_tab(self._tv_index)
            window._tv_workspace.open_folder_dialog()
            return
        window._switch_to_tab(self._movies_index)
        window._movie_workspace.open_folder_dialog()

    def show_about(self, *, message_box_api: Any) -> None:
        message_box_api.about(
            self._window,
            "About NameScraper",
            "NameScraper — GUI4 (PySide6)\n\n"
            "Rename and organize media files into clean,\n"
            "server-friendly naming conventions.\n\n"
            "Metadata provided by TMDB.",
        )

    def restore_window_state(self) -> None:
        window = self._window
        geometry = window.settings_service.window_geometry
        if geometry and len(geometry) == 4:
            window.setGeometry(*geometry)
            return
        window.resize(_scale.px(1440), _scale.px(900))

    def save_window_state(self) -> None:
        window = self._window
        geometry = window.geometry()
        window.settings_service.window_geometry = [
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        ]

    def handle_resize(self) -> None:
        self._window._toast_manager._reposition()

    def prepare_close(self) -> None:
        window = self._window
        self.save_window_state()
        window._persist_tmdb_cache_snapshot()
        window.media_ctrl.clear_listeners()
        window.queue_ctrl.clear_listeners()
        window.queue_ctrl.close()
