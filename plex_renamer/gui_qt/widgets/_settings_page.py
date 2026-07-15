"""Shared leaf components for settings pages."""

from __future__ import annotations

from typing import Self

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QVBoxLayout,
    QWidget,
)

from .. import _scale

CACHE_SIZE_CHOICES: tuple[tuple[str, int], ...] = (
    ("256 MB", 256 * 1024 * 1024),
    ("512 MB", 512 * 1024 * 1024),
    ("1 GB", 1024 ** 3),
    ("2 GB", 2 * 1024 ** 3),
    ("4 GB", 4 * 1024 ** 3),
    ("8 GB", 8 * 1024 ** 3),
)


class SettingsSectionCard(QFrame):
    """A settings section card with a title header row and content area."""

    def __init__(
        self,
        title: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "settings-section")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            _scale.px(16),
            _scale.px(16),
            _scale.px(16),
            _scale.px(16),
        )
        self._layout.setSpacing(_scale.px(12))
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header_row = QHBoxLayout()
        header_row.setSpacing(_scale.px(8))

        self._heading = QLabel(title)
        self._heading.setProperty("cssClass", "heading")
        header_row.addWidget(self._heading)
        header_row.addStretch()
        self._layout.addLayout(header_row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        self._layout.addLayout(layout)

    @classmethod
    def page(cls, title: str) -> Self:
        card = cls(title)
        card.setProperty("sectionRole", "page")
        return card
