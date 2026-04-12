"""Remaining shell helpers for the main window."""

from __future__ import annotations

from typing import Any


class MainWindowShellCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        tv_index: int,
        movies_index: int,
        history_index: int,
    ) -> None:
        self._window = window
        self._tv_index = tv_index
        self._movies_index = movies_index
        self._history_index = history_index

    def open_folder(self, media_type: str) -> None:
        """Switch to the appropriate tab and trigger its folder picker."""
        window = self._window
        if media_type == "tv":
            window._switch_to_tab(self._tv_index)
            window._tv_workspace.open_folder_dialog()
            return
        window._switch_to_tab(self._movies_index)
        window._movie_workspace.open_folder_dialog()

    def undo_last_rename(self, *, message_box_api: Any) -> None:
        window = self._window
        job = window.queue_ctrl.get_latest_revertible_job()
        if job is None:
            window.statusBar().showMessage("Nothing to undo", 3000)
            return

        undo_data = job.undo_data or {}
        rename_count = len(undo_data.get("renames", []))
        description = f"Undo {rename_count} rename(s) for '{job.media_name}'?"
        removed_dirs = undo_data.get("removed_dirs") or []
        if removed_dirs:
            description += "\n\nRemoved folders will also be restored where possible."

        if message_box_api.question(
            window,
            "Undo Last Rename",
            description,
        ) != message_box_api.StandardButton.Yes:
            return

        success, errors = window.queue_ctrl.revert_job(job.job_id)
        window._on_queue_changed()
        window._history_tab.select_job(job.job_id)
        window._switch_to_tab(self._history_index)

        if errors:
            message_box_api.warning(window, "Partial Undo", "\n".join(errors[:8]))
        elif success:
            window.statusBar().showMessage(f"Reverted '{job.media_name}'", 4000)
        else:
            message_box_api.warning(
                window,
                "Undo Failed",
                "Unable to revert the selected rename job.",
            )

    def show_about(self, *, message_box_api: Any) -> None:
        message_box_api.about(
            self._window,
            "About Plex Renamer",
            "Plex Renamer — GUI3 (PySide6)\n\n"
            "Automatically rename and organize media files\n"
            "into Plex-compatible naming conventions.\n\n"
            "Metadata provided by TMDB.",
        )

    def restore_window_state(self) -> None:
        window = self._window
        geometry = window.settings_service.window_geometry
        if geometry and len(geometry) == 4:
            window.setGeometry(*geometry)
            return
        window.resize(1440, 900)

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
