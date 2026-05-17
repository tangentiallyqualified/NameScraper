"""Scanning progress dashboard shown while batch scans are running."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QElapsedTimer, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import _scale
from ...app.models import ScanLifecycle


_TV_CHECKLIST = [
    ScanLifecycle.DISCOVERING,
    ScanLifecycle.MATCHING,
    ScanLifecycle.BUILDING_PREVIEWS,
    ScanLifecycle.RECONCILING,
    ScanLifecycle.PREPARING_REVIEW,
]

_MOVIE_CHECKLIST = [
    ScanLifecycle.DISCOVERING,
    ScanLifecycle.MATCHING,
    ScanLifecycle.BUILDING_PREVIEWS,
    ScanLifecycle.PREPARING_REVIEW,
]

_LIFECYCLE_LABELS = {
    ScanLifecycle.DISCOVERING: "Discover folders",
    ScanLifecycle.MATCHING: "Match on TMDB",
    ScanLifecycle.SCANNING: "Scan files",
    ScanLifecycle.BUILDING_PREVIEWS: "Build previews",
    ScanLifecycle.RECONCILING: "Reconcile scan results",
    ScanLifecycle.PREPARING_REVIEW: "Prepare review list",
}

_TERMINAL = {
    ScanLifecycle.READY,
    ScanLifecycle.WARNING,
    ScanLifecycle.FAILED,
    ScanLifecycle.CANCELLED,
}


class _ScannerAnimation(QWidget):
    """Minimal geometric animation for active scan work."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tick = 0
        self._active = False
        self.setMinimumHeight(_scale.px(220))

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def set_lifecycle(self, lifecycle: ScanLifecycle | None) -> None:
        del lifecycle
        self.update()

    def advance(self) -> None:
        if not self._active:
            return
        self._tick = (self._tick + 1) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(_scale.px(10), _scale.px(6), -_scale.px(10), -_scale.px(6))
        if rect.width() <= 0:
            return

        center = QPointF(rect.center())
        base_radius = min(rect.width(), rect.height()) * 0.43
        pulse = (math.sin(self._tick / 18.0) + 1.0) / 2.0 if self._active else 0.0
        ring_color = QColor("#3a3a3a")
        accent = QColor("#e5a00d")
        accent.setAlpha(110 + int(80 * pulse))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ring_color, _scale.px(4)))
        painter.drawEllipse(center, base_radius, base_radius)
        painter.drawEllipse(center, base_radius * 0.58, base_radius * 0.58)

        painter.setPen(QPen(accent, _scale.px(5)))
        for index in range(6):
            angle = (self._tick * 1.6 + index * 60) * math.pi / 180.0
            orbit = base_radius * (0.76 + 0.08 * math.sin((self._tick + index * 12) / 20.0))
            point = QPointF(
                center.x() + math.cos(angle) * orbit,
                center.y() + math.sin(angle) * orbit,
            )
            dot_radius = _scale.px(5 + (index % 2))
            painter.setBrush(accent if index == 0 else QColor("#242424"))
            painter.drawEllipse(point, dot_radius, dot_radius)

        core = QColor("#1f1a0e")
        painter.setBrush(core)
        painter.setPen(QPen(QColor("#e5a00d"), _scale.px(4)))
        painter.drawEllipse(center, _scale.px(8 + int(2 * pulse)), _scale.px(8 + int(2 * pulse)))


class ScanProgressWidget(QWidget):
    """Structured progress dashboard for active batch scans."""

    cancel_requested = Signal()

    def __init__(self, media_type: str = "tv", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._elapsed = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(90)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._text_update_timer = QElapsedTimer()
        self._current_lifecycle: ScanLifecycle | None = None
        self._completed_lifecycles: set[ScanLifecycle] = set()
        self._checklist = _TV_CHECKLIST if media_type == "tv" else _MOVIE_CHECKLIST
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.setContentsMargins(_scale.px(24), _scale.px(24), _scale.px(24), _scale.px(24))

        card = QFrame()
        card.setProperty("cssClass", "panel")
        card.setFixedWidth(_scale.px(680))
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(_scale.px(10))
        card_layout.setContentsMargins(_scale.px(32), _scale.px(18), _scale.px(32), _scale.px(18))

        kind = "TV Library" if self._media_type == "tv" else "Movie Folder"
        self._title = QLabel(f"Scanning {kind}")
        self._title.setProperty("cssClass", "heading")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._title)

        self._animation = _ScannerAnimation()
        self._animation.setFixedHeight(_scale.px(260))
        card_layout.addWidget(self._animation)

        self._phase_label = QLabel("Initializing scan...")
        self._phase_label.setProperty("cssClass", "heading")
        card_layout.addWidget(self._phase_label)

        self._message_label = QLabel("Preparing the scanner.")
        self._message_label.setProperty("cssClass", "text-dim")
        self._message_label.setWordWrap(False)
        self._message_label.setFixedHeight(_scale.px(22))
        card_layout.addWidget(self._message_label)

        bar_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(_scale.px(8))
        self._progress_bar.setTextVisible(False)
        bar_row.addWidget(self._progress_bar, stretch=1)

        self._count_label = QLabel("0/0")
        self._count_label.setFixedWidth(_scale.px(64))
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count_label.setProperty("cssClass", "text-dim")
        bar_row.addWidget(self._count_label)
        card_layout.addLayout(bar_row)

        details = QGridLayout()
        details.setHorizontalSpacing(_scale.px(16))
        details.setVerticalSpacing(_scale.px(4))
        details.setColumnStretch(0, 1)
        details.setColumnStretch(1, 0)
        self._current_label = QLabel("Current: -")
        self._current_label.setWordWrap(False)
        self._current_label.setMinimumWidth(_scale.px(360))
        self._current_label.setFixedHeight(_scale.px(22))
        self._current_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._elapsed_label = QLabel("Elapsed: 0:00")
        self._elapsed_label.setProperty("cssClass", "text-dim")
        self._elapsed_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        details.addWidget(self._current_label, 0, 0)
        details.addWidget(self._elapsed_label, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        card_layout.addLayout(details)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setProperty("cssClass", "separator")
        sep.setFixedHeight(_scale.px(1))
        card_layout.addWidget(sep)

        self._phase_rows: dict[ScanLifecycle, QLabel] = {}
        self._phase_labels: dict[ScanLifecycle, QLabel] = {}
        checklist_grid = QGridLayout()
        checklist_grid.setHorizontalSpacing(_scale.px(18))
        checklist_grid.setVerticalSpacing(_scale.px(8))
        for index, lifecycle in enumerate(self._checklist):
            icon = QLabel("○")
            icon.setProperty("cssClass", "scan-phase-icon")
            icon.setProperty("phaseState", "pending")
            icon.setFixedWidth(_scale.px(18))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

            label = QLabel(_LIFECYCLE_LABELS.get(lifecycle, str(lifecycle)))
            label.setProperty("cssClass", "scan-phase-label")
            label.setProperty("phaseState", "pending")

            row = index // 2
            column = (index % 2) * 2
            checklist_grid.addWidget(icon, row, column)
            checklist_grid.addWidget(label, row, column + 1)
            self._phase_rows[lifecycle] = icon
            self._phase_labels[lifecycle] = label
        card_layout.addLayout(checklist_grid)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("cssClass", "secondary")
        self._cancel_btn.setFixedWidth(_scale.px(100))
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        outer.addWidget(card)

    def start(self) -> None:
        """Reset the dashboard and start active timers."""
        self._elapsed.start()
        self._elapsed_timer.start()
        self._animation_timer.start()
        self._animation.set_active(True)
        self._completed_lifecycles.clear()
        self._current_lifecycle = None
        self._reset_checklist()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._count_label.setText("0/0")
        self._phase_label.setText("Initializing scan...")
        self._message_label.setText("Preparing the scanner.")
        self._current_label.setText("Current: -")
        self._elapsed_label.setText("Elapsed: 0:00")
        self._text_update_timer.invalidate()

    def stop(self) -> None:
        """Stop elapsed and animation timers."""
        self._elapsed_timer.stop()
        self._animation_timer.stop()
        self._animation.set_active(False)

    def update_progress(
        self,
        lifecycle: str = "",
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str = "",
        message: str = "",
    ) -> None:
        """Update progress display from a ScanProgress payload."""
        parsed_lifecycle = _parse_lifecycle(lifecycle)
        previous_lifecycle = self._current_lifecycle
        if parsed_lifecycle is not None:
            self._set_lifecycle(parsed_lifecycle)
        lifecycle_changed = parsed_lifecycle is not None and parsed_lifecycle != previous_lifecycle

        if total > 0:
            pct = int((max(0, min(done, total)) / total) * 100)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(pct)
            self._count_label.setText(f"{done}/{total}")
        else:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)
            self._count_label.setText("Working")

        if self._should_update_text(
            lifecycle_changed=lifecycle_changed,
            parsed_lifecycle=parsed_lifecycle,
            done=done,
            total=total,
        ):
            if phase:
                self._phase_label.setText(phase)
            if message:
                self._set_elided_text(self._message_label, message)
            if current_item:
                self._set_elided_text(self._current_label, f"Current: {current_item}")
            elif message:
                self._set_elided_text(self._current_label, message)
            self._text_update_timer.restart()

        if parsed_lifecycle in _TERMINAL:
            self.stop()

    def finish(self) -> None:
        """Mark scan as complete."""
        self.stop()
        self._completed_lifecycles.update(self._checklist)
        self._current_lifecycle = None
        self._update_checklist()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._count_label.setText("Done")
        self._phase_label.setText("Scan complete")

    def _set_lifecycle(self, lifecycle: ScanLifecycle) -> None:
        if lifecycle == self._current_lifecycle:
            return
        if lifecycle in _TERMINAL:
            self._completed_lifecycles.update(self._checklist)
            self._current_lifecycle = None
        else:
            self._current_lifecycle = lifecycle
            self._complete_prior_lifecycles(lifecycle)
        self._animation.set_lifecycle(self._current_lifecycle)
        self._update_checklist()

    def _complete_prior_lifecycles(self, lifecycle: ScanLifecycle) -> None:
        if lifecycle not in self._checklist:
            return
        active_index = self._checklist.index(lifecycle)
        self._completed_lifecycles.update(self._checklist[:active_index])

    def _advance_animation(self) -> None:
        self._animation.advance()

    def _set_elided_text(self, label: QLabel, text: str) -> None:
        available_width = _label_text_width(label)
        label.setToolTip(
            text if label.fontMetrics().horizontalAdvance(text) > available_width else ""
        )
        label.setText(_elided_text(label, text))

    def _should_update_text(
        self,
        *,
        lifecycle_changed: bool,
        parsed_lifecycle: ScanLifecycle | None,
        done: int,
        total: int,
    ) -> bool:
        if lifecycle_changed or parsed_lifecycle in _TERMINAL:
            return True
        if not self._text_update_timer.isValid():
            return True
        if total and done in {0, total}:
            return True
        return self._text_update_timer.elapsed() >= 650

    def _update_elapsed(self) -> None:
        secs = self._elapsed.elapsed() // 1000
        minutes = secs // 60
        seconds = secs % 60
        self._elapsed_label.setText(f"Elapsed: {minutes}:{seconds:02d}")

    def _reset_checklist(self) -> None:
        for lifecycle, icon in self._phase_rows.items():
            icon.setText("○")
            self._set_phase_state(lifecycle, "pending")

    def _update_checklist(self) -> None:
        for lifecycle, icon in self._phase_rows.items():
            if lifecycle in self._completed_lifecycles:
                icon.setText("✓")
                self._set_phase_state(lifecycle, "done")
            elif lifecycle == self._current_lifecycle:
                icon.setText("●")
                self._set_phase_state(lifecycle, "active")
            else:
                icon.setText("○")
                self._set_phase_state(lifecycle, "pending")

    def _set_phase_state(self, lifecycle: ScanLifecycle, state: str) -> None:
        icon = self._phase_rows[lifecycle]
        label = self._phase_labels[lifecycle]
        icon.setProperty("phaseState", state)
        label.setProperty("phaseState", state)
        _repolish(icon)
        _repolish(label)


def _parse_lifecycle(lifecycle: str | ScanLifecycle) -> ScanLifecycle | None:
    if isinstance(lifecycle, ScanLifecycle):
        return lifecycle
    if not lifecycle:
        return None
    try:
        return ScanLifecycle(lifecycle)
    except ValueError:
        return None


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _label_text_width(label: QLabel) -> int:
    width = label.contentsRect().width()
    if width <= 0:
        width = label.width()
    return max(1, width)


def _elided_text(label: QLabel, text: str) -> str:
    return label.fontMetrics().elidedText(
        text,
        Qt.TextElideMode.ElideRight,
        _label_text_width(label),
    )
