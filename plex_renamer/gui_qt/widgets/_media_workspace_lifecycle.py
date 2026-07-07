"""Lifecycle and state-switching helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer

# Poster warmup gate (LD3): hold the SCANNING view up while matched posters
# finish loading so the READY transition doesn't reveal empty placeholders.
_POSTER_WARMUP_MAX_MS = 4000
_POSTER_WARMUP_POLL_MS = 120


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
        workspace._work_panel.clear()
        workspace._stack.setCurrentIndex(self._empty_index)
        workspace._empty_state.refresh_recent_folders()

    def show_scanning(self) -> None:
        workspace = self._workspace
        workspace._scan_progress.start()
        workspace._work_panel.clear()
        workspace._stack.setCurrentIndex(self._scanning_index)

    def show_ready(self) -> None:
        workspace = self._workspace
        workspace._scan_progress.stop()
        workspace._stack.setCurrentIndex(self._ready_index)
        workspace.refresh_from_controller()

    def show_ready_when_posters_warm(self) -> None:
        """Populate the roster while SCANNING stays up, feed the conveyor
        (LD2), and switch to READY once posters settle or a max wait fires
        (LD3)."""
        workspace = self._workspace
        # Populate the roster (kicks off poster loads) while the loading
        # screen stays visible.
        workspace.refresh_from_controller()
        model = workspace._roster_panel.model
        conveyor = workspace._scan_progress
        conveyor.set_posters(model.loaded_posters())

        elapsed = [0]
        finalized = [False]

        def _finalize() -> None:
            if finalized[0]:
                return
            finalized[0] = True
            try:
                model.poster_loaded.disconnect(_on_poster)
            except (RuntimeError, TypeError):
                pass
            poll.stop()
            workspace._scan_progress.finish()
            self.show_ready()

        def _on_poster() -> None:
            conveyor.set_posters(model.loaded_posters())
            if model.pending_poster_count() == 0:
                _finalize()

        def _tick() -> None:
            elapsed[0] += _POSTER_WARMUP_POLL_MS
            conveyor.set_posters(model.loaded_posters())
            if model.pending_poster_count() == 0 or elapsed[0] >= _POSTER_WARMUP_MAX_MS:
                _finalize()

        model.poster_loaded.connect(_on_poster)
        poll = QTimer(workspace)
        poll.setInterval(_POSTER_WARMUP_POLL_MS)
        poll.timeout.connect(_tick)
        poll.start()
        self._warmup_poll = poll
        # Handle the already-warm case (no posters or all cached synchronously).
        if model.pending_poster_count() == 0:
            _finalize()

    def apply_settings(self) -> None:
        workspace = self._workspace
        compact = workspace._settings is not None and workspace._settings.view_mode == "compact"
        workspace._roster_panel.set_compact(compact)
        workspace.refresh_from_controller()
        selected_state = workspace._selected_state()
        if selected_state is not None:
            workspace._populate_preview(selected_state)

    def on_folder_selected(self, path: str) -> None:
        workspace = self._workspace
        workspace.folder_selected.emit(path)

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
