"""Shared image conversion helpers for Qt worker-thread handoff."""

from __future__ import annotations

from PySide6.QtCore import Property, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget


def pil_to_raw(pil_image) -> tuple[bytes, int, int]:
    """Convert a PIL image into raw RGBA bytes for thread-safe transport."""
    rgba = pil_image.convert("RGBA")
    return (rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height)


def raw_to_pixmap(raw_data: tuple[bytes, int, int]) -> QPixmap:
    """Convert raw RGBA bytes into a QPixmap on the main Qt thread."""
    data, width, height = raw_data
    qimage = QImage(data, width, height, 4 * width, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def build_placeholder_pixmap(
    size: QSize,
    *,
    title: str,
    subtitle: str = "",
    accent: str = "#e5a00d",
) -> QPixmap:
    """Create a styled placeholder artwork card for empty poster slots."""
    width = max(1, size.width())
    height = max(1, size.height())
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(1, 1, width - 2, height - 2)
    path = QPainterPath()
    path.addRoundedRect(rect, 10, 10)

    gradient = QLinearGradient(0, 0, 0, float(height))
    gradient.setColorAt(0.0, QColor("#262626"))
    gradient.setColorAt(1.0, QColor("#151515"))
    painter.fillPath(path, gradient)

    painter.setPen(QColor("#2a2a2a"))
    painter.drawPath(path)

    accent_rect = QRectF(rect.left() + 8, rect.top() + 8, 4, max(20.0, rect.height() * 0.35))
    accent_path = QPainterPath()
    accent_path.addRoundedRect(accent_rect, 2, 2)
    painter.fillPath(accent_path, QColor(accent))

    painter.setPen(QColor("#e0e0e0"))
    title_font = QFont("Segoe UI", max(8, min(18, height // 7)))
    title_font.setBold(True)
    painter.setFont(title_font)
    text_rect = QRectF(rect.left() + 20, rect.top() + 16, rect.width() - 28, rect.height() - 32)
    painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), title)

    if subtitle:
        subtitle_font = QFont("Segoe UI", max(7, min(11, height // 11)))
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#777777"))
        subtitle_rect = QRectF(text_rect.left(), text_rect.top() + max(18.0, rect.height() * 0.28), text_rect.width(), text_rect.height() - 18)
        painter.drawText(subtitle_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), subtitle)

    painter.end()
    return pixmap


class ShimmerOverlay(QWidget):
    """Translucent animated shimmer drawn over a parent widget while content loads."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = 0.0

        self._anim = QPropertyAnimation(self, b"phase", self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1200)
        self._anim.setLoopCount(-1)
        self._anim.start()

    def _get_phase(self) -> float:
        return self._phase

    def _set_phase(self, value: float) -> None:
        self._phase = value
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def paintEvent(self, _event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        if w < 1 or h < 1:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Sweeping highlight band
        band_w = w * 0.6
        x = -band_w + (w + band_w) * self._phase
        grad = QLinearGradient(x, 0, x + band_w, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, 18))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(0, 0, w, h, grad)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.resize(self.parentWidget().size())

    def stop(self) -> None:
        self._anim.stop()
        self.hide()
        self.deleteLater()