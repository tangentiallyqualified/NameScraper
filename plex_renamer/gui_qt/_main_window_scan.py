"""Scan and workspace refresh helpers for the main window."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..app.models import ScanLifecycle, ScanProgress


class MainWindowScanCoordinator:
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

    def start_tv_scan(self, path: str) -> None:
        self._start_scan(path, media_type="tv")

    def start_movie_scan(self, path: str) -> None:
        self._start_scan(path, media_type="movie")

    def active_workspace(self):
        window = self._window
        if window.media_ctrl.active_content_mode == "movie":
            return window._movie_workspace
        return window._tv_workspace

    def on_scan_progress(self, progress: ScanProgress) -> None:
        workspace = self.active_workspace()
        workspace.scan_progress_widget.update_progress(
            lifecycle=progress.lifecycle,
            phase=progress.phase,
            done=progress.done,
            total=progress.total,
            current_item=progress.current_item or "",
            message=progress.message,
        )
        self._window.statusBar().showMessage(progress.message, 2000)

    def on_scan_complete(self) -> None:
        window = self._window
        workspace = self.active_workspace()
        if window.media_ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
            workspace.scan_progress_widget.stop()
            if window.media_ctrl.library_states:
                workspace.show_ready()
            else:
                workspace.show_empty()
                window._show_scan_feedback(
                    title="Scan cancelled",
                    message="The scan was cancelled before any results were produced.",
                    tone="accent",
                )
            window.statusBar().showMessage("Scan cancelled", 3000)
            return

        if self._needs_tv_bulk_scan(window.media_ctrl.batch_states):
            window.media_ctrl.scan_all_shows()
            return

        workspace.show_ready_when_posters_warm()
        window._scan_feedback_token = None
        window.statusBar().showMessage("Scan complete", 3000)

    def on_library_changed(self) -> None:
        window = self._window
        workspace = self.active_workspace()
        states = window.media_ctrl.library_states
        window._update_media_badges(states)

        if window.media_ctrl.scan_progress.lifecycle == ScanLifecycle.READY and states:
            workspace.show_ready_when_posters_warm()
        elif window.media_ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
            workspace.scan_progress_widget.stop()
            if states:
                workspace.show_ready()
            else:
                workspace.show_empty()
        elif (
            window.media_ctrl.scan_progress.lifecycle
            in {
                ScanLifecycle.WARNING,
                ScanLifecycle.FAILED,
            }
            and not states
        ):
            workspace.show_empty()
            message = (
                window.media_ctrl.scan_progress.message
                or "The scan ended before any results were produced."
            )
            window._show_scan_feedback(
                title="Scan did not finish cleanly",
                message=message,
                tone="error",
            )
        elif workspace.is_showing_ready():
            workspace.refresh_from_controller()

    def on_queue_changed(self) -> None:
        window = self._window
        window._refresh_job_views()
        active_index = window._tabs.currentIndex()
        if active_index == self._tv_index and window._tv_workspace.is_showing_ready():
            window._tv_workspace.refresh_from_controller()
        elif active_index == self._movies_index and window._movie_workspace.is_showing_ready():
            window._movie_workspace.refresh_from_controller()
        window._tv_needs_queue_refresh = active_index != self._tv_index
        window._movie_needs_queue_refresh = active_index != self._movies_index

    def _start_scan(self, path: str, *, media_type: str) -> None:
        window = self._window
        window._scan_feedback_token = None
        folder = Path(path)
        workspace = self._workspace_for_media_type(media_type)
        if not self._validate_destination_for_scan(folder, media_type=media_type):
            return
        client = window._ensure_tv_provider() if media_type == "tv" else window._ensure_tmdb()
        if client is None:
            workspace.show_empty()
            return
        workspace.show_scanning()
        if media_type == "movie":
            window.media_ctrl.start_movie_batch(folder, client)
            return
        window.media_ctrl.start_tv_batch(folder, client)

    def _validate_destination_for_scan(self, folder: Path, *, media_type: str) -> bool:
        window = self._window
        if media_type == "movie":
            output_status = window.settings_service.validate_movie_output_folder()
            workspace = window._movie_workspace
            label = "Movies"
        else:
            output_status = window.settings_service.validate_tv_output_folder()
            workspace = window._tv_workspace
            label = "TV Shows"

        if not output_status.valid or output_status.path is None:
            workspace.show_empty()
            window._show_scan_feedback(
                title=f"{label} output folder required",
                message=output_status.reason
                or f"Set a {label} output folder in Settings before scanning.",
                tone="error",
            )
            window.statusBar().showMessage(
                "Set an output folder in Settings before scanning.", 5000
            )
            return False

        relationship = window.settings_service.validate_scan_output_relationship(
            folder, output_status.path
        )
        if not relationship.valid:
            workspace.show_empty()
            window._show_scan_feedback(
                title="Output folder cannot be inside the scan folder",
                message=relationship.reason,
                tone="error",
            )
            window.statusBar().showMessage(relationship.reason, 5000)
            return False

        return True

    def _workspace_for_media_type(self, media_type: str):
        window = self._window
        if media_type == "movie":
            return window._movie_workspace
        return window._tv_workspace

    def _needs_tv_bulk_scan(self, states) -> bool:
        window = self._window
        return (
            window.media_ctrl.active_content_mode == "tv"
            and window.media_ctrl.batch_mode
            and any(not state.scanned and state.show_id is not None for state in states)
        )
