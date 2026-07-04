"""BusyOverlay: translucent scrim + spinner + label over any panel (spec §7).

``busy_scope()`` guarantees removal via ``finally`` — a stuck overlay is
impossible by construction.  ``immediate=True`` is for GUI-thread operations
that block the event loop: the overlay is shown and painted synchronously up
front (a deferred QTimer show can never fire while the loop is blocked).  The
default deferred mode is for waits where the loop stays alive (off-thread
work): the overlay appears only if the wait exceeds ``delay_ms``.
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import _scale, theme

_DEFAULT_SHOW_DELAY_MS = 120
_SPINNER_DIAMETER_U = 32
_SPINNER_STEP_DEGREES = 8
_SPINNER_INTERVAL_MS = 16
_SPINNER_SPAN_DEGREES = 100
_SCRIM_ALPHA = 170


class Spinner(QWidget):
    """Rotating accent arc.  Plan 6's loading screen reuses this widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        size = _scale.px(_SPINNER_DIAMETER_U)
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(_SPINNER_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._angle = (self._angle + _SPINNER_STEP_DEGREES) % 360
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = painter.pen()
        pen_width = max(2, _scale.px(3))
        pen.setWidth(pen_width)
        pen.setColor(QColor(theme.color("accent")))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inset = pen_width // 2 + 1
        arc_rect = self.rect().adjusted(inset, inset, -inset, -inset)
        # drawArc takes 1/16th-degree units.
        painter.drawArc(arc_rect, -self._angle * 16, -_SPINNER_SPAN_DEGREES * 16)


class BusyOverlay(QWidget):
    def __init__(self, target: QWidget, text: str) -> None:
        super().__init__(target)
        self._target = target
        self._show_timer: QTimer | None = None
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(_scale.px(8))
        self._spinner = Spinner(self)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._label = QLabel(text, self)
        self._label.setStyleSheet(f"color: {theme.color('text_dim')};")
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignHCenter)
        target.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._target and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self._target.rect())
        return False

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        scrim = QColor(theme.color("bg"))
        scrim.setAlpha(_SCRIM_ALPHA)
        painter.fillRect(self.rect(), scrim)

    def show_now(self) -> None:
        self._cancel_timer()
        self.setGeometry(self._target.rect())
        self.show()
        self.raise_()
        # One synchronous paint so work that blocks the event loop right
        # after this call still gets a visible overlay.
        self.repaint()

    def show_after(self, delay_ms: int) -> None:
        self._cancel_timer()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(0, delay_ms))
        timer.timeout.connect(self.show_now)
        self._show_timer = timer
        timer.start()

    def dismiss(self) -> None:
        self._cancel_timer()
        self._target.removeEventFilter(self)
        self.hide()
        self.setParent(None)
        self.deleteLater()

    def _cancel_timer(self) -> None:
        if self._show_timer is not None:
            self._show_timer.stop()
            self._show_timer = None


@contextmanager
def busy_scope(
    target: QWidget,
    text: str = "Working…",
    *,
    delay_ms: int = _DEFAULT_SHOW_DELAY_MS,
    immediate: bool = False,
):
    overlay = BusyOverlay(target, text)
    try:
        if immediate:
            overlay.show_now()
        else:
            overlay.show_after(delay_ms)
        yield overlay
    finally:
        overlay.dismiss()
