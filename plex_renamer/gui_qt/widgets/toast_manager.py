"""Lightweight toast notifications for the Qt shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_BORDER_COLORS = {
    "success": "#3ea463",
    "error": "#d44040",
    "accent": "#4a9eda",
}


class _ToastCard(QFrame):
    dismissed = Signal(object)

    def __init__(
        self,
        *,
        title: str,
        message: str,
        tone: str,
        duration_ms: int,
        action_text: str | None = None,
        action_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._duration_ms = max(0, duration_ms)
        self._remaining_ms = self._duration_ms
        self._action_callback = action_callback
        border = _BORDER_COLORS.get(tone, _BORDER_COLORS["accent"])
        self.setObjectName("toastCard")
        self.setStyleSheet(
            "QFrame#toastCard {"
            f"background-color: #181818; border: 1px solid #2a2a2a; border-left: 4px solid {border};"
            "border-radius: 10px; }"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_label = QLabel(title)
        title_label.setProperty("cssClass", "heading")
        title_label.setWordWrap(True)
        header.addWidget(title_label, stretch=1)

        close_btn = QPushButton("x")
        close_btn.setProperty("cssClass", "secondary")
        close_btn.setFixedSize(26, 26)
        close_btn.clicked.connect(self.dismiss)
        header.addWidget(close_btn)
        root.addLayout(header)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        root.addWidget(message_label)

        if action_text and action_callback is not None:
            action_btn = QPushButton(action_text)
            action_btn.setProperty("cssClass", "secondary")
            action_btn.clicked.connect(self._run_action)
            root.addWidget(action_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)
        self._progress.setStyleSheet(
            "QProgressBar { background: #2a2a2a; border: 0; border-radius: 1px; }"
            f"QProgressBar::chunk {{ background: {border}; border-radius: 1px; }}"
        )
        if self._duration_ms > 0:
            self._progress.setRange(0, self._duration_ms)
            self._progress.setValue(self._duration_ms)
            root.addWidget(self._progress)

            self._timer = QTimer(self)
            self._timer.setInterval(50)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
        else:
            self._progress.hide()

    def _run_action(self) -> None:
        if self._action_callback is not None:
            self._action_callback()
        self.dismiss()

    def _tick(self) -> None:
        self._remaining_ms -= self._timer.interval()
        if self._remaining_ms <= 0:
            self.dismiss()
            return
        self._progress.setValue(self._remaining_ms)

    def dismiss(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        self.dismissed.emit(self)


class ToastManager(QWidget):
    """Bottom-right stacked toast notification container."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setObjectName("toastManager")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch()
        self.hide()

    def show_toast(
        self,
        *,
        title: str,
        message: str,
        tone: str = "accent",
        duration_ms: int = 3000,
        action_text: str | None = None,
        action_callback: Callable[[], None] | None = None,
    ) -> None:
        toast = _ToastCard(
            title=title,
            message=message,
            tone=tone,
            duration_ms=duration_ms,
            action_text=action_text,
            action_callback=action_callback,
            parent=self,
        )
        toast.dismissed.connect(self._remove_toast)
        self._layout.insertWidget(0, toast)
        self.show()
        self.raise_()
        self._reposition()

    def toast_count(self) -> int:
        return sum(1 for index in range(self._layout.count()) if self._layout.itemAt(index).widget() is not None)

    def _remove_toast(self, toast: _ToastCard) -> None:
        self._layout.removeWidget(toast)
        toast.deleteLater()
        if self.toast_count() == 0:
            self.hide()
        else:
            self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(380, max(280, parent.width() // 3))
        height = self.sizeHint().height()
        margin = 16
        self.setGeometry(parent.width() - width - margin, parent.height() - height - margin, width, height)
