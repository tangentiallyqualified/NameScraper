"""Small tab badge widgets for queue and history counts."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class TabBadge(QWidget):
    """Tab-side count badge with optional failure pip."""

    def __init__(self, *, show_failure_pip: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "tab-badge")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._count_label = QLabel("0")
        self._count_label.setProperty("cssClass", "tab-badge-count")
        layout.addWidget(self._count_label)

        self._pip = QLabel("")
        self._pip.setProperty("cssClass", "tab-badge-pip")
        self._pip.setFixedSize(8, 8)
        self._pip.setVisible(show_failure_pip)
        layout.addWidget(self._pip)

    def set_count(self, count: int) -> None:
        self._count_label.setText(str(max(0, count)))

    def count_text(self) -> str:
        return self._count_label.text()

    def set_failure_visible(self, visible: bool) -> None:
        self._pip.setVisible(visible)

    def failure_visible(self) -> bool:
        return not self._pip.isHidden()