"""Centralized scale helpers for the PySide6 GUI.

All sizing constants in widget code should flow through this module rather
than appearing as bare integer literals.  ``px(n)`` converts logical 4px-grid
values into physical pixels using the primary screen's logical DPI; the
returned values match the visual sizes intended by the original literals when
the screen is at 96 DPI (100% scale) and grow proportionally on HiDPI.
"""
from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import QMargins, QSize
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication

_LOGICAL_DPI_BASE = 96.0

_ICON_TOKENS: Mapping[str, int] = {
    "sm": 16,
    "md": 24,
    "lg": 32,
    "xl": 48,
}


def _dpi_scale() -> float:
    screen = QGuiApplication.primaryScreen() if QGuiApplication.instance() else None
    if screen is None:
        return 1.0
    dpi = screen.logicalDotsPerInch()
    if dpi <= 0:
        return 1.0
    return dpi / _LOGICAL_DPI_BASE


def px(n: int) -> int:
    """Convert logical 4px-grid units to physical pixels."""
    if n == 0:
        return 0
    return int(round(n * _dpi_scale()))


def row_height(rows: int = 1, padding: int = 0) -> int:
    """Return a row height derived from the application font's line spacing.

    ``rows`` is a multiplier; ``padding`` is in grid units (passed through ``px``).
    """
    metrics = QFontMetrics(QFont())
    return metrics.lineSpacing() * max(1, rows) + px(padding)


def icon(token: str) -> QSize:
    """Return a named, DPI-scaled icon size as a ``QSize``."""
    base = _ICON_TOKENS[token]
    side = px(base)
    return QSize(side, side)


def margins(*tokens: int) -> QMargins:
    """Build a ``QMargins`` from 1, 2, or 4 grid-unit tokens.

    - ``margins(8)``               -> uniform 8 on all sides
    - ``margins(8, 12)``           -> vertical 8, horizontal 12
    - ``margins(l, t, r, b)``      -> left, top, right, bottom
    """
    if len(tokens) == 1:
        v = px(tokens[0])
        return QMargins(v, v, v, v)
    if len(tokens) == 2:
        vert = px(tokens[0])
        horz = px(tokens[1])
        return QMargins(horz, vert, horz, vert)
    if len(tokens) == 4:
        return QMargins(px(tokens[0]), px(tokens[1]), px(tokens[2]), px(tokens[3]))
    raise ValueError(f"margins() expects 1, 2, or 4 tokens; got {len(tokens)}")
