"""Lightweight toast notifications for the Qt shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import _scale
from ._toast_manager_layout import (
    count_direct_toasts,
    plan_toast_manager_geometry,
    summary_toast_copy,
)

_TONES = ("success", "error", "accent")
_TONE_ICONS = {"success": "✓", "error": "!", "accent": "i"}
_CLAMP_LINES = 3
_EXPAND_WINDOW_FRACTION = 0.4
_DEFAULT_DURATION_MS = 3000
_MAX_VISIBLE_TOASTS = 4
_MAX_DIRECT_TOASTS = 3


def _normalize_tone(tone: str) -> str:
    return tone if tone in _TONES else "accent"


def _default_duration(tone: str, duration_ms: int | None) -> int:
    if duration_ms is not None:
        return max(0, duration_ms)
    return 0 if tone == "error" else _DEFAULT_DURATION_MS


class _ToastCard(QFrame):
    dismissed = Signal(object)
    layout_changed = Signal()

    def __init__(
        self,
        *,
        title: str,
        message: str,
        tone: str,
        duration_ms: int | None = None,
        action_text: str | None = None,
        action_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        tone = _normalize_tone(tone)
        self._duration_ms = _default_duration(tone, duration_ms)
        self._remaining_ms = self._duration_ms
        self._action_callback = action_callback
        self._full_message = message
        self._title_text = title
        self._expanded = False
        self.setObjectName("toastCard")
        self.setProperty("tone", tone)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        pad = _scale.px(12)
        root.setContentsMargins(pad, _scale.px(10), pad, _scale.px(10))
        root.setSpacing(_scale.px(8))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(_scale.px(8))

        self._icon_label = QLabel(_TONE_ICONS[tone])
        self._icon_label.setProperty("cssClass", "toast-icon")
        self._icon_label.setProperty("tone", tone)
        self._icon_label.setFixedWidth(_scale.px(16))
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        header.addWidget(self._icon_label)

        self._title_label = QLabel(title)
        self._title_label.setProperty("cssClass", "heading")
        self._title_label.setWordWrap(True)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self._title_label, stretch=1)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setProperty("cssClass", "toast-inline")
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        header.addWidget(self._copy_btn)

        self._close_btn = QPushButton("✕")
        self._close_btn.setProperty("cssClass", "toast-close")
        self._close_btn.setFixedSize(_scale.px(24), _scale.px(24))
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("Dismiss")
        self._close_btn.clicked.connect(self.dismiss)
        header.addWidget(self._close_btn)
        root.addLayout(header)

        self._message_label = QLabel(message)
        self._message_label.setWordWrap(True)
        self._message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._body = QScrollArea()
        self._body.setProperty("cssClass", "toast-body")
        self._body.setWidgetResizable(True)
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body.setWidget(self._message_label)
        root.addWidget(self._body)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self._show_more_btn = QPushButton("Show more")
        self._show_more_btn.setProperty("cssClass", "toast-inline")
        self._show_more_btn.clicked.connect(self._toggle_expanded)
        self._show_more_btn.hide()
        controls.addWidget(self._show_more_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        if action_text and action_callback is not None:
            action_btn = QPushButton(action_text)
            action_btn.setProperty("cssClass", "toast-inline")
            action_btn.clicked.connect(self._run_action)
            controls.addWidget(action_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        controls.addStretch()
        root.addLayout(controls)

        self._progress = QProgressBar()
        self._progress.setProperty("cssClass", "toast-countdown")
        self._progress.setProperty("tone", tone)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(_scale.px(3))
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

    # -- clamp / expand ----------------------------------------------------

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._show_more_btn.setText("Show less" if expanded else "Show more")
        self._sync_clamp()
        self.layout_changed.emit()

    def _toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _line_height(self) -> int:
        return max(1, self._message_label.fontMetrics().lineSpacing())

    def _full_text_height(self) -> int:
        width = self._message_label.width()
        if width <= 1:
            width = max(1, self._body.viewport().width())
        return max(self._line_height(), self._message_label.heightForWidth(width))

    def _sync_clamp(self) -> None:
        before = self._body.height()
        collapsed = self._line_height() * _CLAMP_LINES + _scale.px(4)
        full = self._full_text_height()
        needs_clamp = full > collapsed
        self._show_more_btn.setVisible(needs_clamp)
        if not needs_clamp:
            self._expanded = False
            self._show_more_btn.setText("Show more")
            self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            applied = full
        elif self._expanded:
            window = self.window()
            cap = full
            if window is not None and window is not self:
                cap = max(collapsed, int(window.height() * _EXPAND_WINDOW_FRACTION))
            self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            applied = min(full, cap)
        else:
            self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            applied = collapsed
        self._body.setFixedHeight(applied)
        if self._body.height() != before:
            self.layout_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_clamp()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_clamp()

    # -- actions / countdown -------------------------------------------------

    def _copy_to_clipboard(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(f"{self._title_text}\n{self._full_message}")

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

    def enterEvent(self, event) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None and self._remaining_ms > 0:
            timer.start()
        super().leaveEvent(event)

    def dismiss(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        self.dismissed.emit(self)

    def update_message(self, *, title: str, message: str) -> None:
        self._title_text = title
        self._full_message = message
        self._title_label.setText(title)
        self._message_label.setText(message)
        self._expanded = False
        self._show_more_btn.setText("Show more")
        self._sync_clamp()
        self.layout_changed.emit()


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
        self._keyed_toasts: dict[str, _ToastCard] = {}
        self._overflow_count = 0
        self.hide()

    def show_toast(
        self,
        *,
        title: str,
        message: str,
        tone: str = "accent",
        duration_ms: int | None = None,
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
        toast.layout_changed.connect(self._reposition)
        self._layout.insertWidget(0, toast)
        self.show()
        self.raise_()
        self._reposition()

    def show_or_update_toast(
        self,
        *,
        key: str,
        title: str,
        message: str,
        tone: str = "accent",
        duration_ms: int | None = None,
        action_text: str | None = None,
        action_callback: Callable[[], None] | None = None,
    ) -> None:
        toast = self._keyed_toasts.get(key)
        if toast is not None:
            toast.update_message(title=title, message=message)
            self.show()
            self.raise_()
            self._reposition()
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
        self._keyed_toasts[key] = toast
        toast.dismissed.connect(self._remove_toast)
        toast.layout_changed.connect(self._reposition)
        self._layout.insertWidget(0, toast)
        self.show()
        self.raise_()
        self._reposition()

    def dismiss_toast(self, key: str) -> bool:
        toast = self._keyed_toasts.get(key)
        if toast is None:
            return False
        toast.dismiss()
        return True

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
        for key, keyed_toast in list(self._keyed_toasts.items()):
            if keyed_toast is toast:
                del self._keyed_toasts[key]
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
            self._summary_toast.layout_changed.connect(self._reposition)
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
