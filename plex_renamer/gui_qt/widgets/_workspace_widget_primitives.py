"""Primitive widgets shared by media workspace roster and preview rows."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QSizePolicy, QWidget


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

    _INDICATOR_SIZE = 18
    _RADIUS = 4
    _BG_OFF = QColor("#3a3a3a")
    _BG_ON = QColor("#3ea463")
    _BG_PARTIAL = QColor("#4a9eda")
    _BORDER_OFF = QColor("#555555")
    _BORDER_ON = QColor("#2d7a4a")
    _CHECK_COLOR = QColor("#ffffff")

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

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        state = self.checkState()
        if state == Qt.CheckState.Checked:
            bg, border = self._BG_ON, self._BORDER_ON
        elif state == Qt.CheckState.PartiallyChecked:
            bg, border = self._BG_PARTIAL, self._BG_PARTIAL
        else:
            bg, border = self._BG_OFF, self._BORDER_OFF

        indicator_y = (self.height() - self._INDICATOR_SIZE) / 2
        rect_f = QRectF(1.5, indicator_y, self._INDICATOR_SIZE - 3.0, self._INDICATOR_SIZE - 3.0)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(rect_f, self._RADIUS, self._RADIUS)

        pen = QPen(self._CHECK_COLOR, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        size = self._INDICATOR_SIZE
        if state == Qt.CheckState.Checked:
            painter.drawLine(int(size * 0.25), int(indicator_y + size * 0.50), int(size * 0.43), int(indicator_y + size * 0.68))
            painter.drawLine(int(size * 0.43), int(indicator_y + size * 0.68), int(size * 0.75), int(indicator_y + size * 0.32))
        elif state == Qt.CheckState.PartiallyChecked:
            y = int(indicator_y + size / 2)
            painter.drawLine(int(size * 0.28), y, int(size * 0.72), y)

        text_rect = self.rect().adjusted(self._INDICATOR_SIZE + 8, 0, 0, 0)
        painter.setPen(QColor("#8d8d8d") if not self.isEnabled() else QColor("#e0e0e0"))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
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

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self._apply_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elision()

    def showEvent(self, event) -> None:  # noqa: N802
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


class ClickableRow(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class ToggleSwitch(QCheckBox):
    _SIZE = 20
    _RADIUS = 4
    _BG_OFF = QColor("#3a3a3a")
    _BG_ON = QColor("#3ea463")
    _BG_PARTIAL = QColor("#4a9eda")
    _BORDER_OFF = QColor("#555555")
    _BORDER_ON = QColor("#2d7a4a")
    _CHECK_COLOR = QColor("#ffffff")

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._SIZE, self._SIZE)

    def sizeHint(self) -> QSize:
        return QSize(self._SIZE, self._SIZE)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        state = self.checkState()
        if state == Qt.CheckState.Checked:
            bg, border = self._BG_ON, self._BORDER_ON
        elif state == Qt.CheckState.PartiallyChecked:
            bg, border = self._BG_PARTIAL, self._BG_PARTIAL
        else:
            bg, border = self._BG_OFF, self._BORDER_OFF

        size = self._SIZE
        margin = 1.5
        rect_f = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(rect_f, self._RADIUS, self._RADIUS)

        pen = QPen(self._CHECK_COLOR, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if state == Qt.CheckState.Checked:
            painter.drawLine(int(size * 0.25), int(size * 0.50), int(size * 0.43), int(size * 0.68))
            painter.drawLine(int(size * 0.43), int(size * 0.68), int(size * 0.75), int(size * 0.32))
        elif state == Qt.CheckState.PartiallyChecked:
            y = size // 2
            painter.drawLine(int(size * 0.28), y, int(size * 0.72), y)

        painter.end()


class MiniProgressBar(QWidget):
    def __init__(self, *, color: str, value: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._value = max(0, min(100, value))
        self.setFixedHeight(4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setValue(self, value: int) -> None:  # noqa: N802
        self._value = max(0, min(100, value))
        self.update()

    def setColor(self, color: str) -> None:  # noqa: N802
        self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(120, 4)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        rect = self.rect()
        if not rect.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(rect, 2, 2)
        fill_width = int(rect.width() * (self._value / 100.0))
        if fill_width <= 0:
            return
        fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
        painter.setBrush(self._color)
        painter.drawRoundedRect(fill_rect, 2, 2)