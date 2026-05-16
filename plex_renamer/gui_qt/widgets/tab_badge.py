"""Small tab badge widgets for queue and history counts."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget


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
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._count_label)

        self._pip = QLabel("")
        self._pip.setProperty("cssClass", "tab-badge-pip")
        self._pip.setFixedSize(8, 8)
        self._pip.setVisible(False)
        layout.addWidget(self._pip)

        # Pulse animation on the count label using opacity as a proxy
        # for a visible "bump" when the count changes.
        self._opacity_effect = QGraphicsOpacityEffect(self._count_label)
        self._opacity_effect.setOpacity(1.0)
        self._count_label.setGraphicsEffect(self._opacity_effect)
        self._pulse_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._pulse_anim.setDuration(200)
        self._pulse_anim.setKeyValueAt(0, 1.0)
        self._pulse_anim.setKeyValueAt(0.5, 0.4)
        self._pulse_anim.setKeyValueAt(1.0, 1.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def set_count(self, count: int) -> None:
        new_text = str(max(0, count))
        if new_text != self._count_label.text():
            self._count_label.setText(new_text)
            self._pulse_anim.stop()
            self._pulse_anim.start()

    def count_text(self) -> str:
        return self._count_label.text()

    def set_failure_visible(self, visible: bool) -> None:
        self._pip.setVisible(False)  # Pip is deprecated — use badge color instead
        if visible:
            self._count_label.setStyleSheet(
                "background-color: #d44040; color: #ffffff; border-color: #d44040;"
            )
        else:
            self._count_label.setStyleSheet("")  # Revert to QSS defaults

    def failure_visible(self) -> bool:
        return "d44040" in (self._count_label.styleSheet() or "")
