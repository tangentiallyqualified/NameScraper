"""Scanning progress widget shown while a folder scan is running.

Displays structured progress: phase name, progress bar with N/M count,
current item, elapsed timer, and a phase checklist.

The checklist tracks ``ScanLifecycle`` enum values emitted by
``MediaController``, not free-text phase strings.  The prose ``phase``
field is displayed as-is in the phase label.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QElapsedTimer, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...app.models import ScanLifecycle


# Checklist uses lifecycle enum values, not prose phase strings.
# Order matches the typical scan flow.
_LIFECYCLE_CHECKLIST = [
    ScanLifecycle.DISCOVERING,
    ScanLifecycle.MATCHING,
    ScanLifecycle.SCANNING,
]

_LIFECYCLE_LABELS = {
    ScanLifecycle.DISCOVERING: "Folder discovery",
    ScanLifecycle.MATCHING: "Matching on TMDB",
    ScanLifecycle.SCANNING: "Episode / file scanning",
}

# Terminal states that mean "all phases done"
_TERMINAL = {ScanLifecycle.READY, ScanLifecycle.WARNING, ScanLifecycle.FAILED}


class ScanProgressWidget(QWidget):
    """Centered structured progress view for active scans."""

    cancel_requested = Signal()

    def __init__(self, media_type: str = "tv", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._elapsed = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._current_lifecycle: ScanLifecycle | None = None
        self._completed_lifecycles: set[ScanLifecycle] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Container card
        card = QFrame()
        card.setProperty("cssClass", "panel")
        card.setFixedWidth(480)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(32, 24, 32, 24)

        # Title
        kind = "TV Library" if self._media_type == "tv" else "Movie Folder"
        self._title = QLabel(f"Scanning {kind}")
        self._title.setProperty("cssClass", "heading")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._title)

        # Phase label (displays the prose phase string from the controller)
        self._phase_label = QLabel("Phase: Initializing...")
        self._phase_label.setProperty("cssClass", "text-dim")
        card_layout.addWidget(self._phase_label)

        # Progress bar + count
        bar_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        bar_row.addWidget(self._progress_bar, stretch=1)

        self._count_label = QLabel("0/0")
        self._count_label.setFixedWidth(56)
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar_row.addWidget(self._count_label)
        card_layout.addLayout(bar_row)

        # Current item
        self._current_label = QLabel("Current: —")
        card_layout.addWidget(self._current_label)

        # Elapsed
        self._elapsed_label = QLabel("Elapsed: 0:00")
        self._elapsed_label.setProperty("cssClass", "text-dim")
        card_layout.addWidget(self._elapsed_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setProperty("cssClass", "separator")
        sep.setFixedHeight(1)
        card_layout.addWidget(sep)

        # Phase checklist — keyed by ScanLifecycle enum values
        self._phase_rows: dict[ScanLifecycle, QLabel] = {}
        self._phase_labels: dict[ScanLifecycle, QLabel] = {}
        for lc in _LIFECYCLE_CHECKLIST:
            row = QHBoxLayout()
            row.setSpacing(8)
            icon = QLabel("\u25CB")  # hollow circle (pending)
            icon.setProperty("cssClass", "scan-phase-icon")
            icon.setProperty("phaseState", "pending")
            icon.setFixedWidth(16)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(icon)

            label = QLabel(_LIFECYCLE_LABELS.get(lc, str(lc)))
            label.setProperty("cssClass", "scan-phase-label")
            label.setProperty("phaseState", "pending")
            row.addWidget(label)
            row.addStretch()

            card_layout.addLayout(row)
            self._phase_rows[lc] = icon
            self._phase_labels[lc] = label

        # Cancel button
        card_layout.addSpacing(8)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("cssClass", "secondary")
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        btn_row.addWidget(self._cancel_btn)
        card_layout.addLayout(btn_row)

        outer.addWidget(card)

    # ── Public API ───────────────────────────────────────────────

    def start(self) -> None:
        """Reset and start the elapsed timer."""
        self._elapsed.start()
        self._elapsed_timer.start()
        self._completed_lifecycles.clear()
        self._current_lifecycle = None
        self._reset_checklist()
        self._progress_bar.setValue(0)
        self._count_label.setText("0/0")
        self._current_label.setText("Current: —")
        self._elapsed_label.setText("Elapsed: 0:00")

    def stop(self) -> None:
        """Stop the elapsed timer."""
        self._elapsed_timer.stop()

    def update_progress(
        self,
        lifecycle: str = "",
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str = "",
        message: str = "",
    ) -> None:
        """Update progress display from a ScanProgress payload.

        *lifecycle* is a ``ScanLifecycle`` enum value (e.g. "discovering",
        "matching", "scanning", "ready").  The checklist tracks these.
        *phase* is a human-readable prose string displayed in the phase label.
        """
        # Lifecycle tracking for checklist
        if lifecycle and lifecycle != self._current_lifecycle:
            if self._current_lifecycle and self._current_lifecycle not in _TERMINAL:
                self._completed_lifecycles.add(self._current_lifecycle)
            self._current_lifecycle = lifecycle
            self._update_checklist()

        # Phase label (prose string from controller)
        if phase:
            self._phase_label.setText(f"Phase: {phase}")

        # Progress bar
        if total > 0:
            pct = int((done / total) * 100)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(pct)
            self._count_label.setText(f"{done}/{total}")
        else:
            self._progress_bar.setRange(0, 0)  # indeterminate
            self._count_label.setText("")

        # Current item
        if current_item:
            self._current_label.setText(f"Current: {current_item}")
        elif message:
            self._current_label.setText(message)

    def finish(self) -> None:
        """Mark scan as complete — all phases done."""
        self.stop()
        self._completed_lifecycles.update(_LIFECYCLE_CHECKLIST)
        self._current_lifecycle = None
        self._update_checklist()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)

    # ── Internals ────────────────────────────────────────────────

    def _update_elapsed(self) -> None:
        secs = self._elapsed.elapsed() // 1000
        minutes = secs // 60
        seconds = secs % 60
        self._elapsed_label.setText(f"Elapsed: {minutes}:{seconds:02d}")

    def _reset_checklist(self) -> None:
        for lifecycle, icon in self._phase_rows.items():
            icon.setText("\u25CB")
            self._set_phase_state(lifecycle, "pending")

    def _update_checklist(self) -> None:
        for lc, icon in self._phase_rows.items():
            if lc in self._completed_lifecycles:
                icon.setText("\u2713")  # check mark
                self._set_phase_state(lc, "done")
            elif lc == self._current_lifecycle:
                icon.setText("\u25CF")  # filled circle (active)
                self._set_phase_state(lc, "active")
            else:
                icon.setText("\u25CB")  # hollow circle (pending)
                self._set_phase_state(lc, "pending")

    def _set_phase_state(self, lifecycle: ScanLifecycle, state: str) -> None:
        icon = self._phase_rows[lifecycle]
        icon.setProperty("phaseState", state)
        label = self._phase_labels[lifecycle]
        label.setProperty("phaseState", state)
        _repolish(label)
        _repolish(icon)


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
