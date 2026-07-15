"""Shared image conversion helpers for Qt worker-thread handoff."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap

from .. import theme


def pil_to_raw(pil_image) -> tuple[bytes, int, int]:
    """Convert a PIL image into raw RGBA bytes for thread-safe transport."""
    rgba = pil_image.convert("RGBA")
    return (rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height)


def raw_to_pixmap(raw_data: tuple[bytes, int, int]) -> QPixmap:
    """Convert raw RGBA bytes into a QPixmap on the main Qt thread."""
    data, width, height = raw_data
    qimage = QImage(data, width, height, 4 * width, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def scale_pixmap_for_device(
    pixmap: QPixmap,
    size: QSize,
    *,
    device_pixel_ratio: float = 1.0,
    aspect_mode: Qt.AspectRatioMode = Qt.AspectRatioMode.KeepAspectRatio,
) -> QPixmap:
    """Return a pixmap scaled for the target logical size on a HiDPI display."""
    if pixmap.isNull() or not size.isValid():
        return QPixmap()
    ratio = max(1.0, float(device_pixel_ratio or 1.0))
    pixel_size = QSize(
        max(1, int(round(size.width() * ratio))),
        max(1, int(round(size.height() * ratio))),
    )
    scaled = pixmap.scaled(
        pixel_size,
        aspect_mode,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(ratio)
    return scaled


def build_placeholder_pixmap(
    size: QSize,
    *,
    title: str,
    subtitle: str = "",
    accent: str | None = None,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Create a styled placeholder artwork card for empty poster slots."""
    accent = accent or theme.color("accent")
    ratio = max(1.0, float(device_pixel_ratio or 1.0))
    width = max(1, int(round(size.width() * ratio)))
    height = max(1, int(round(size.height() * ratio)))
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(1, 1, width - 2, height - 2)
    path = QPainterPath()
    path.addRoundedRect(rect, 10, 10)

    gradient = QLinearGradient(0, 0, 0, float(height))
    gradient.setColorAt(0.0, theme.qcolor("card_hover"))
    gradient.setColorAt(1.0, theme.qcolor("surface"))
    painter.fillPath(path, gradient)

    painter.setPen(theme.qcolor("border"))
    painter.drawPath(path)

    accent_rect = QRectF(rect.left() + 8, rect.top() + 8, 4, max(20.0, rect.height() * 0.35))
    accent_path = QPainterPath()
    accent_path.addRoundedRect(accent_rect, 2, 2)
    painter.fillPath(accent_path, QColor(accent))

    painter.setPen(theme.qcolor("text"))
    title_font = QFont("Segoe UI", max(8, min(18, height // 7)))
    title_font.setBold(True)
    painter.setFont(title_font)
    text_rect = QRectF(rect.left() + 20, rect.top() + 16, rect.width() - 28, rect.height() - 32)
    painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), title)

    if subtitle:
        subtitle_font = QFont("Segoe UI", max(7, min(11, height // 11)))
        painter.setFont(subtitle_font)
        painter.setPen(theme.qcolor("text_dim"))
        subtitle_rect = QRectF(text_rect.left(), text_rect.top() + max(18.0, rect.height() * 0.28), text_rect.width(), text_rect.height() - 18)
        painter.drawText(subtitle_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), subtitle)

    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap
