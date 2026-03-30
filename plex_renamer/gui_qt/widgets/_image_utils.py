"""Shared image conversion helpers for Qt worker-thread handoff."""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap


def pil_to_raw(pil_image) -> tuple[bytes, int, int]:
    """Convert a PIL image into raw RGBA bytes for thread-safe transport."""
    rgba = pil_image.convert("RGBA")
    return (rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height)


def raw_to_pixmap(raw_data: tuple[bytes, int, int]) -> QPixmap:
    """Convert raw RGBA bytes into a QPixmap on the main Qt thread."""
    data, width, height = raw_data
    qimage = QImage(data, width, height, 4 * width, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)