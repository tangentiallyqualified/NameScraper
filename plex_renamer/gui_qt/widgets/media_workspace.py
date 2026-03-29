"""Media workspace widget for TV Shows and Movies tabs.

Manages the EMPTY -> SCANNING -> READY state machine via a
QStackedWidget.  The READY state shows the 3-panel splitter layout
with placeholder panels (roster, preview, detail) and a bottom
action bar.

State transitions are driven by the MainWindow in response to
MediaController callbacks — the workspace does not call the
controller directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .empty_state import EmptyStateWidget
from .scan_progress import ScanProgressWidget

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService

# Stack indices
_EMPTY = 0
_SCANNING = 1
_READY = 2


class MediaWorkspace(QWidget):
    """TV or Movie tab workspace with state-driven content switching."""

    # Emitted when a folder is selected — MainWindow handles the
    # controller call and state transitions.
    folder_selected = Signal(str)

    def __init__(
        self,
        media_type: str = "tv",
        settings_service: "SettingsService | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Page 0: Empty state ──────────────────────────────────
        self._empty_state = EmptyStateWidget(
            media_type=self._media_type,
            settings_service=self._settings,
        )
        self._empty_state.folder_selected.connect(self._on_folder_selected)
        self._stack.addWidget(self._empty_state)

        # ── Page 1: Scanning state ───────────────────────────────
        self._scan_progress = ScanProgressWidget(
            media_type=self._media_type,
        )
        self._scan_progress.cancel_requested.connect(self._on_cancel_scan)
        self._stack.addWidget(self._scan_progress)

        # ── Page 2: Ready state (3-panel + action bar) ───────────
        ready_container = QWidget()
        ready_layout = QVBoxLayout(ready_container)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(0)

        # 3-panel splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._roster_panel = _PlaceholderPanel("Roster")
        self._preview_panel = _PlaceholderPanel("Preview")
        self._detail_panel = _PlaceholderPanel("Detail")

        self._splitter.addWidget(self._roster_panel)
        self._splitter.addWidget(self._preview_panel)
        self._splitter.addWidget(self._detail_panel)

        # Default proportions: ~20% roster, ~50% preview, ~30% detail
        self._splitter.setSizes([250, 600, 370])
        self._splitter.setChildrenCollapsible(False)

        ready_layout.addWidget(self._splitter, stretch=1)

        # Bottom action bar
        self._action_bar = _ActionBar(media_type=self._media_type)
        ready_layout.addWidget(self._action_bar)

        self._stack.addWidget(ready_container)

        # ── Restore splitter positions ───────────────────────────
        if self._settings:
            positions = self._settings.splitter_positions
            if positions and len(positions) == 3:
                self._splitter.setSizes(positions)

        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        # Start in empty state
        self._stack.setCurrentIndex(_EMPTY)

    # ── Public API ───────────────────────────────────────────────

    def open_folder_dialog(self) -> None:
        """Trigger the empty state's folder picker dialog."""
        self._empty_state.open_folder_dialog()

    def load_folder(self, path: str) -> None:
        """Load a specific folder path (e.g. from recent folders menu)."""
        self._on_folder_selected(path)

    def show_empty(self) -> None:
        """Switch to the empty state."""
        self._scan_progress.stop()
        self._stack.setCurrentIndex(_EMPTY)
        self._empty_state.refresh_recent_folders()

    def show_scanning(self) -> None:
        """Switch to the scanning state and start the timer."""
        self._scan_progress.start()
        self._stack.setCurrentIndex(_SCANNING)

    def show_ready(self) -> None:
        """Switch to the 3-panel ready state."""
        self._scan_progress.stop()
        self._stack.setCurrentIndex(_READY)

    @property
    def scan_progress_widget(self) -> ScanProgressWidget:
        return self._scan_progress

    @property
    def splitter(self) -> QSplitter:
        return self._splitter

    # ── Internals ────────────────────────────────────────────────

    def _on_folder_selected(self, path: str) -> None:
        # Emit the signal — MainWindow will call the controller and
        # transition us to scanning via show_scanning().
        self.folder_selected.emit(path)
        # Transition to scanning immediately.  If the controller
        # cannot start (e.g. no API key), MainWindow calls show_empty().
        self.show_scanning()

    def _on_cancel_scan(self) -> None:
        # Will be wired to MediaController.cancel_scan in Phase 5
        self.show_empty()

    def _on_splitter_moved(self) -> None:
        if self._settings:
            self._settings.splitter_positions = list(self._splitter.sizes())


class _PlaceholderPanel(QFrame):
    """Temporary placeholder for roster/preview/detail panels."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "panel")

        layout = QVBoxLayout(self)
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setProperty("cssClass", "text-muted")
        layout.addWidget(lbl)

        hint = QLabel("Wired in Phase 5-6")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setProperty("cssClass", "caption")
        layout.addWidget(hint)


class _ActionBar(QFrame):
    """Bottom action bar for the ready state workspace."""

    def __init__(
        self,
        media_type: str = "tv",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self.setStyleSheet(
            "background-color: #151515; border-top: 1px solid #2a2a2a;"
        )
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)

        self._summary_label = QLabel("0 of 0 items checked")
        layout.addWidget(self._summary_label)

        layout.addStretch()

        self._check_all_btn = QPushButton("Check All")
        self._check_all_btn.setProperty("cssClass", "secondary")
        layout.addWidget(self._check_all_btn)

        self._uncheck_all_btn = QPushButton("Uncheck All")
        self._uncheck_all_btn.setProperty("cssClass", "secondary")
        layout.addWidget(self._uncheck_all_btn)

        self._queue_btn = QPushButton("Add to Queue")
        layout.addWidget(self._queue_btn)

    def update_summary(self, checked: int, total: int) -> None:
        noun = "items" if self._media_type == "movie" else "shows"
        self._summary_label.setText(f"{checked} of {total} {noun} checked")
        if checked:
            self._queue_btn.setText(f"Add {checked} to Queue")
            self._queue_btn.setEnabled(True)
        else:
            self._queue_btn.setText("Add to Queue")
            self._queue_btn.setEnabled(False)
