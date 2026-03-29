"""Main application window — Phase 3 shell.

Owns the menu bar, tab bar, and status bar.  Tab content widgets are
created here but their internal logic lives in their own modules.

Controller wiring: MainWindow registers a MediaController listener
that marshals progress/completion callbacks from worker threads to
the main thread via Qt signals, then forwards them to the active
workspace widget.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMenuBar,
    QTabWidget,
)

from ..app.models import ScanLifecycle, ScanProgress
from ..app.services.cache_service import PersistentCacheService
from ..app.services.command_gating_service import CommandGatingService
from ..app.services.refresh_policy_service import RefreshPolicyService
from ..app.services.settings_service import SettingsService
from ..app.controllers.queue_controller import QueueController
from ..app.controllers.media_controller import MediaController
from ..job_store import JobStore
from ..tmdb import TMDBClient
from ..keys import get_api_key

from .widgets.media_workspace import MediaWorkspace
from .widgets.queue_tab import QueueTab
from .widgets.history_tab import HistoryTab
from .widgets.settings_tab import SettingsTab

_log = logging.getLogger(__name__)

# Tab indices
_TV = 0
_MOVIES = 1
_QUEUE = 2
_HISTORY = 3
_SETTINGS = 4


class _ControllerBridge(QObject):
    """Thread-safe bridge from MediaController callbacks to Qt signals.

    MediaController fires callbacks from background threads.  This bridge
    converts them into Qt signals that are dispatched on the main thread.
    """

    progress_received = Signal(object)   # ScanProgress
    scan_complete = Signal()
    library_changed = Signal()

    def on_progress(self, progress: ScanProgress) -> None:
        self.progress_received.emit(progress)

    def on_scan_complete(self, _state) -> None:
        self.scan_complete.emit()

    def on_library_changed(self, _states) -> None:
        self.library_changed.emit()


class _QueueBridge(QObject):
    """Thread-safe bridge from QueueController callbacks to Qt signals."""

    changed = Signal(object)

    def on_job_started(self, _job) -> None:
        self.changed.emit(None)

    def on_job_completed(self, _job, _result) -> None:
        self.changed.emit(None)

    def on_job_failed(self, _job, _error) -> None:
        self.changed.emit(None)

    def on_queue_finished(self) -> None:
        self.changed.emit(None)


class MainWindow(QMainWindow):
    """Top-level window with menu bar, tab bar, and status bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Plex Renamer")
        self.setMinimumSize(960, 600)

        # ── TMDB client (lazily created) ─────────────────────────
        self._tmdb: TMDBClient | None = None
        self._tv_snapshot: dict | None = None
        self._movie_snapshot: dict | None = None

        # ── Services and controllers ─────────────────────────────
        self.settings_service = SettingsService()
        self._job_store = JobStore()
        self._command_gating = CommandGatingService()
        self._cache_service = PersistentCacheService()
        self._refresh_policy = RefreshPolicyService()

        self.queue_ctrl = QueueController(self._job_store)
        self.media_ctrl = MediaController(
            job_store=self._job_store,
            command_gating=self._command_gating,
            settings=self.settings_service,
            cache_service=self._cache_service,
            refresh_policy=self._refresh_policy,
        )

        # ── Controller → Qt bridge ───────────────────────────────
        self._bridge = _ControllerBridge(self)
        self.media_ctrl.add_listener(
            on_progress=self._bridge.on_progress,
            on_scan_complete=self._bridge.on_scan_complete,
            on_library_changed=self._bridge.on_library_changed,
        )
        self._bridge.progress_received.connect(self._on_scan_progress)
        self._bridge.scan_complete.connect(self._on_scan_complete)
        self._bridge.library_changed.connect(self._on_library_changed)

        self._queue_bridge = _QueueBridge(self)
        self.queue_ctrl.add_listener(
            on_job_started=self._queue_bridge.on_job_started,
            on_job_completed=self._queue_bridge.on_job_completed,
            on_job_failed=self._queue_bridge.on_job_failed,
            on_queue_finished=self._queue_bridge.on_queue_finished,
        )
        self._queue_bridge.changed.connect(self._on_queue_changed)

        # ── Tab widget ───────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.setCentralWidget(self._tabs)

        # ── Tab content ──────────────────────────────────────────
        self._tv_workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self.media_ctrl,
            queue_controller=self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
            settings_service=self.settings_service,
        )
        self._movie_workspace = MediaWorkspace(
            media_type="movie",
            media_controller=self.media_ctrl,
            queue_controller=self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
            settings_service=self.settings_service,
        )
        self._queue_tab = QueueTab(
            self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
            navigate_to_media=self._switch_to_tab,
        )
        self._history_tab = HistoryTab(
            self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
        )
        self._settings_tab = SettingsTab(
            settings_service=self.settings_service,
        )

        self._tabs.addTab(self._tv_workspace, "TV Shows")
        self._tabs.addTab(self._movie_workspace, "Movies")
        self._tabs.addTab(self._queue_tab, "Queue")
        self._tabs.addTab(self._history_tab, "History")
        self._tabs.addTab(self._settings_tab, "Settings")

        # ── Menu bar ─────────────────────────────────────────────
        self._build_menu_bar()

        # ── Keyboard shortcuts ───────────────────────────────────
        self._build_shortcuts()

        # ── Signals ──────────────────────────────────────────────
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tv_workspace.folder_selected.connect(self._on_tv_folder_selected)
        self._movie_workspace.folder_selected.connect(self._on_movie_folder_selected)
        self._tv_workspace.queue_changed.connect(self._on_queue_changed)
        self._movie_workspace.queue_changed.connect(self._on_queue_changed)
        self._tv_workspace.status_message.connect(self.statusBar().showMessage)
        self._movie_workspace.status_message.connect(self.statusBar().showMessage)

        # ── Restore geometry ─────────────────────────────────────
        self._restore_window_state()
        self._refresh_job_views()

    # ── TMDB client ──────────────────────────────────────────────

    def _ensure_tmdb(self) -> TMDBClient | None:
        """Get or lazily create the shared TMDB client."""
        if self._tmdb is not None:
            return self._tmdb
        api_key = get_api_key("TMDB")
        if not api_key:
            self.statusBar().showMessage(
                "No TMDB API key — set one in Settings first.", 5000,
            )
            return None
        self._tmdb = TMDBClient(
            api_key,
            language=self.settings_service.match_language,
        )
        return self._tmdb

    # ── Menu bar ─────────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")

        open_tv = file_menu.addAction("Open TV Folder...")
        open_tv.setShortcut(QKeySequence("Ctrl+O"))
        open_tv.triggered.connect(lambda: self._open_folder("tv"))

        open_movie = file_menu.addAction("Open Movie Folder...")
        open_movie.triggered.connect(lambda: self._open_folder("movie"))

        file_menu.addSeparator()

        # Recent TV folders submenu
        self._recent_tv_menu = file_menu.addMenu("Recent TV Folders")
        self._recent_movie_menu = file_menu.addMenu("Recent Movie Folders")
        self._rebuild_recent_menus()

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)

        # Edit
        edit_menu = mb.addMenu("&Edit")

        undo_action = edit_menu.addAction("&Undo Last Rename")
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(self._on_undo)

        edit_menu.addSeparator()

        settings_action = edit_menu.addAction("&Settings")
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(
            lambda: self._tabs.setCurrentIndex(_SETTINGS)
        )

        # View
        view_menu = mb.addMenu("&View")

        self._compact_action = view_menu.addAction("Compact Mode")
        self._compact_action.setCheckable(True)
        self._compact_action.setChecked(
            self.settings_service.view_mode == "compact"
        )
        self._compact_action.toggled.connect(self._on_compact_toggled)

        self._companion_action = view_menu.addAction("Show Companion Files")
        self._companion_action.setCheckable(True)
        self._companion_action.setChecked(
            self.settings_service.show_companion_files
        )
        self._companion_action.toggled.connect(self._on_companion_toggled)

        # Help
        help_menu = mb.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about)

    def _build_shortcuts(self) -> None:
        """Register keyboard shortcuts that aren't menu-bound."""
        for i in range(5):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            idx = i
            action.triggered.connect(lambda _=False, n=idx: self._tabs.setCurrentIndex(n))
            self.addAction(action)

    # ── Folder selection → controller scan ───────────────────────

    def _on_tv_folder_selected(self, path: str) -> None:
        self.settings_service.add_recent_tv_folder(path)
        self._rebuild_recent_menus()
        self._start_tv_scan(path)

    def _on_movie_folder_selected(self, path: str) -> None:
        self.settings_service.add_recent_movie_folder(path)
        self._rebuild_recent_menus()
        self._start_movie_scan(path)

    def _start_tv_scan(self, path: str) -> None:
        tmdb = self._ensure_tmdb()
        if tmdb is None:
            self._tv_workspace.show_empty()
            return
        self.media_ctrl.start_tv_batch(Path(path), tmdb)

    def _start_movie_scan(self, path: str) -> None:
        tmdb = self._ensure_tmdb()
        if tmdb is None:
            self._movie_workspace.show_empty()
            return
        self.media_ctrl.start_movie_batch(Path(path), tmdb)

    # ── Controller callback handlers (main thread via bridge) ────

    def _active_workspace(self) -> MediaWorkspace:
        """Return the workspace matching the controller's active mode."""
        mode = self.media_ctrl.active_content_mode
        if mode == "movie":
            return self._movie_workspace
        return self._tv_workspace

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        ws = self._active_workspace()
        ws.scan_progress_widget.update_progress(
            lifecycle=progress.lifecycle,
            phase=progress.phase,
            done=progress.done,
            total=progress.total,
            current_item=progress.current_item or "",
            message=progress.message,
        )
        self.statusBar().showMessage(progress.message, 2000)

    def _on_scan_complete(self) -> None:
        ws = self._active_workspace()
        if (
            self.media_ctrl.active_content_mode == "tv"
            and self.media_ctrl.batch_mode
            and any(
                not state.scanned and not state.queued and state.show_id is not None
                for state in self.media_ctrl.batch_states
            )
        ):
            self.media_ctrl.scan_all_shows()
            return

        ws.scan_progress_widget.finish()
        ws.show_ready()
        ws.refresh_from_controller()
        self.statusBar().showMessage("Scan complete", 3000)

    def _on_library_changed(self) -> None:
        ws = self._active_workspace()
        ws.refresh_from_controller()

        states = self.media_ctrl.library_states
        needs_tv_bulk_scan = (
            self.media_ctrl.active_content_mode == "tv"
            and self.media_ctrl.batch_mode
            and any(
                not state.scanned and not state.queued and state.show_id is not None
                for state in states
            )
        )

        if self.media_ctrl.scan_progress.lifecycle == ScanLifecycle.READY and states and not needs_tv_bulk_scan:
            ws.scan_progress_widget.finish()
            ws.show_ready()
        elif self.media_ctrl.scan_progress.lifecycle in {
            ScanLifecycle.WARNING,
            ScanLifecycle.FAILED,
            ScanLifecycle.CANCELLED,
        } and not states:
            ws.show_empty()

    def _on_queue_changed(self, _unused=None) -> None:
        self._refresh_job_views()
        self._tv_workspace.refresh_from_controller()
        self._movie_workspace.refresh_from_controller()

    def _refresh_job_views(self) -> None:
        self._queue_tab.refresh()
        self._history_tab.refresh()
        counts = self.queue_ctrl.count_by_status()
        pending = counts.get("pending", 0) + counts.get("running", 0)
        history = sum(counts.get(status, 0) for status in ("completed", "failed", "cancelled", "reverted"))
        self._tabs.setTabText(_QUEUE, f"Queue ({pending})")
        self._tabs.setTabText(_HISTORY, f"History ({history})")

    # ── Other actions ────────────────────────────────────────────

    def _open_folder(self, media_type: str) -> None:
        """Switch to the appropriate tab and trigger its folder picker."""
        if media_type == "tv":
            self._switch_to_tab(_TV)
            self._tv_workspace.open_folder_dialog()
        else:
            self._switch_to_tab(_MOVIES)
            self._movie_workspace.open_folder_dialog()

    def _switch_to_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    def _rebuild_recent_menus(self) -> None:
        self._recent_tv_menu.clear()
        for folder in self.settings_service.recent_tv_folders:
            p = Path(folder)
            action = self._recent_tv_menu.addAction(p.name)
            action.setToolTip(str(p))
            action.triggered.connect(
                lambda _=False, f=folder: self._tv_workspace.load_folder(f)
            )
        self._recent_tv_menu.setEnabled(bool(self.settings_service.recent_tv_folders))

        self._recent_movie_menu.clear()
        for folder in self.settings_service.recent_movie_folders:
            p = Path(folder)
            action = self._recent_movie_menu.addAction(p.name)
            action.setToolTip(str(p))
            action.triggered.connect(
                lambda _=False, f=folder: self._movie_workspace.load_folder(f)
            )
        self._recent_movie_menu.setEnabled(bool(self.settings_service.recent_movie_folders))

    def _on_tab_changed(self, index: int) -> None:
        self._capture_active_snapshot()

        if index == _TV and self._tv_snapshot is not None:
            self.media_ctrl.restore_tv_from_tab_switch(self._tv_snapshot)
            self._tv_workspace.refresh_from_controller()
        elif index == _MOVIES and self._movie_snapshot is not None:
            self.media_ctrl.restore_movie_from_tab_switch(self._movie_snapshot)
            self._movie_workspace.refresh_from_controller()

        _log.debug("Tab switched to %d", index)

    def _capture_active_snapshot(self) -> None:
        if self.media_ctrl.active_content_mode == "tv":
            self._tv_snapshot = self.media_ctrl.snapshot_tv_for_tab_switch()
        elif self.media_ctrl.active_content_mode == "movie":
            self._movie_snapshot = self.media_ctrl.snapshot_movie_for_tab_switch()

    def _on_undo(self) -> None:
        job = self.queue_ctrl.get_latest_revertible_job()
        if job is None:
            self.statusBar().showMessage("Nothing to undo", 3000)
            return
        # Full undo UI will be wired in Phase 4
        self.statusBar().showMessage(
            f"Undo not yet wired — would revert '{job.media_name}'", 3000
        )

    def _on_compact_toggled(self, checked: bool) -> None:
        mode = "compact" if checked else "normal"
        self.settings_service.view_mode = mode

    def _on_companion_toggled(self, checked: bool) -> None:
        self.settings_service.show_companion_files = checked

    def _on_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            "About Plex Renamer",
            "Plex Renamer — GUI3 (PySide6)\n\n"
            "Automatically rename and organize media files\n"
            "into Plex-compatible naming conventions.\n\n"
            "Metadata provided by TMDB.",
        )

    # ── Window state persistence ─────────────────────────────────

    def _restore_window_state(self) -> None:
        geo = self.settings_service.window_geometry
        if geo and len(geo) == 4:
            self.setGeometry(*geo)
        else:
            self.resize(1280, 800)

    def _save_window_state(self) -> None:
        g = self.geometry()
        self.settings_service.window_geometry = [g.x(), g.y(), g.width(), g.height()]

    # ── Close ────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._save_window_state()
        self.media_ctrl.clear_listeners()
        self.queue_ctrl.clear_listeners()
        self.queue_ctrl.close()
        super().closeEvent(event)
