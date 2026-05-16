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

from ._toast_manager_layout import (
    count_direct_toasts,
    plan_toast_manager_geometry,
    summary_toast_copy,
)

_BORDER_COLORS = {
    "success": "#3ea463",
    "error": "#d44040",
    "accent": "#4a9eda",
}
_MAX_VISIBLE_TOASTS = 4
_MAX_DIRECT_TOASTS = 3


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
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._title_label = QLabel(title)
        self._title_label.setProperty("cssClass", "heading")
        self._title_label.setWordWrap(True)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self._title_label, stretch=1)

        close_btn = QPushButton("x")
        close_btn.setProperty("cssClass", "secondary")
        close_btn.setFixedSize(26, 26)
        close_btn.clicked.connect(self.dismiss)
        header.addWidget(close_btn)
        root.addLayout(header)

        self._message_label = QLabel(message)
        self._message_label.setWordWrap(True)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root.addWidget(self._message_label)

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

    def update_message(self, *, title: str, message: str) -> None:
        self._title_label.setText(title)
        self._message_label.setText(message)


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
        self._summary_toast: _ToastCard | None = None
        self._overflow_count = 0
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
        if self._direct_toast_count() >= _MAX_DIRECT_TOASTS:
            self._overflow_count += 1
            self._show_or_update_summary()
            return
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

    def dismiss_topmost(self) -> bool:
        """Dismiss the newest visible toast. Returns True if one was dismissed."""
        for index in range(self._layout.count()):
            widget = self._layout.itemAt(index).widget()
            if isinstance(widget, _ToastCard):
                widget.dismiss()
                return True
        return False

    def toast_count(self) -> int:
        return len(self._toast_widgets())

    def _remove_toast(self, toast: _ToastCard) -> None:
        self._layout.removeWidget(toast)
        if toast is self._summary_toast:
            self._summary_toast = None
            self._overflow_count = 0
        toast.deleteLater()
        if self.toast_count() == 0:
            self.hide()
        else:
            self._reposition()

    def _direct_toast_count(self) -> int:
        return count_direct_toasts(
            self._toast_widgets(),
            summary_toast=self._summary_toast,
        )

    def _show_or_update_summary(self) -> None:
        title, message = summary_toast_copy(self._overflow_count)
        if self._summary_toast is None:
            self._summary_toast = _ToastCard(
                title=title,
                message=message,
                tone="accent",
                duration_ms=0,
                parent=self,
            )
            self._summary_toast.dismissed.connect(self._remove_toast)
            self._layout.insertWidget(0, self._summary_toast)
        else:
            self._summary_toast.update_message(title=title, message=message)
        self.show()
        self.raise_()
        self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        toast_heights: list[int] = []
        spacing = self._layout.spacing()
        geometry = plan_toast_manager_geometry(
            parent.width(),
            parent.height(),
            toast_heights=[],
            spacing=spacing,
        )
        for toast in self._toast_widgets():
            toast.setFixedWidth(geometry.width)
            toast.layout().activate()
            toast_heights.append(toast.sizeHint().height())
        geometry = plan_toast_manager_geometry(
            parent.width(),
            parent.height(),
            toast_heights=toast_heights,
            spacing=spacing,
        )
        self.setGeometry(geometry.x, geometry.y, geometry.width, geometry.height)

    def _toast_widgets(self) -> list[_ToastCard]:
        toasts: list[_ToastCard] = []
        for index in range(self._layout.count()):
            item = self._layout.itemAt(index)
            toast = item.widget() if item is not None else None
            if toast is None:
                continue
            toasts.append(toast)
        return toasts
