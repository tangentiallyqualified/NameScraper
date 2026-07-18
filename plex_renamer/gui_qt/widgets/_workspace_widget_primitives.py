"""Primitive widgets shared by media workspace roster and preview rows."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QLabel, QSizePolicy, QWidget

from .. import _scale, theme


def _check_palette(state: Qt.CheckState) -> tuple[QColor, QColor]:
    if state == Qt.CheckState.Checked:
        return theme.qcolor("success"), theme.qcolor("success_dim")
    if state == Qt.CheckState.PartiallyChecked:
        return theme.qcolor("info"), theme.qcolor("info")
    return theme.qcolor("border_light"), theme.qcolor("border_light")


def paint_check_indicator(painter: QPainter, rect: QRectF, state: Qt.CheckState) -> None:
    """Paint the rounded indicator shared by MasterCheckBox and the roster delegate."""
    bg, border = _check_palette(state)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(bg)
    painter.setPen(QPen(border, 1.5))
    painter.drawRoundedRect(rect, 4, 4)
    pen = QPen(theme.qcolor("on_accent"), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    size = rect.width()
    left, top = rect.x(), rect.y()
    if state == Qt.CheckState.Checked:
        painter.drawLine(
            int(left + size * 0.25),
            int(top + size * 0.50),
            int(left + size * 0.43),
            int(top + size * 0.68),
        )
        painter.drawLine(
            int(left + size * 0.43),
            int(top + size * 0.68),
            int(left + size * 0.75),
            int(top + size * 0.32),
        )
    elif state == Qt.CheckState.PartiallyChecked:
        y = int(top + size / 2)
        painter.drawLine(int(left + size * 0.28), y, int(left + size * 0.72), y)
    painter.restore()


def paint_mini_progress(painter: QPainter, rect: QRect, *, value: int, color: QColor) -> None:
    """Paint the roster delegate's compact track-and-fill progress bar."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.qcolor("border"))
    painter.drawRoundedRect(rect, 2, 2)
    clamped = max(0, min(100, value))
    fill_width = int(rect.width() * (clamped / 100.0))
    if fill_width > 0:
        fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
        painter.setBrush(color)
        painter.drawRoundedRect(fill_rect, 2, 2)
    painter.restore()


class _CheckBinding:
    """Small checkbox binding used to reuse engine/controller helpers in Qt."""

    def __init__(self, value: bool) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


class RosterPosterBridge(QObject):
    poster_ready = Signal(object, object)


class MasterCheckBox(QCheckBox):
    """Tri-state display checkbox that toggles like a normal binary control."""

    _INDICATOR_GRID_UNITS = 18
    _RADIUS = 4

    @property
    def _INDICATOR_SIZE(self) -> int:
        return _scale.px(self._INDICATOR_GRID_UNITS)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("cssClass", "master-check")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def nextCheckState(self) -> None:
        self.setCheckState(
            Qt.CheckState.Unchecked
            if self.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(self._INDICATOR_SIZE + 12 + text_width, max(24, self._INDICATOR_SIZE + 6))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)

        state = self.checkState()
        indicator_y = (self.height() - self._INDICATOR_SIZE) / 2
        rect_f = QRectF(1.5, indicator_y, self._INDICATOR_SIZE - 3.0, self._INDICATOR_SIZE - 3.0)
        paint_check_indicator(painter, rect_f, state)

        text_rect = self.rect().adjusted(self._INDICATOR_SIZE + 8, 0, 0, 0)
        painter.setPen(theme.qcolor("text_dim") if not self.isEnabled() else theme.qcolor("text"))
        painter.drawText(
            text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text()
        )
        painter.end()


class ElidedLabel(QLabel):
    def __init__(
        self,
        text: str = "",
        *,
        elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = text
        self._elide_mode = elide_mode
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._apply_elision()

    def setText(self, text: str) -> None:
        self._full_text = text
        self._apply_elision()

    def text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        if not self._full_text:
            super().setText("")
            self.setToolTip("")
            return
        available_width = max(0, self.contentsRect().width())
        if available_width <= 0:
            display_text = self._full_text
        else:
            display_text = self.fontMetrics().elidedText(
                self._full_text,
                self._elide_mode,
                available_width,
            )
        super().setText(display_text)
        self.setToolTip(self._full_text if display_text != self._full_text else "")
