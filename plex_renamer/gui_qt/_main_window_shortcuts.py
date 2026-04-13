"""Shortcut behavior helpers for the main window."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit


class MainWindowShortcutCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        tv_index: int,
        movies_index: int,
        queue_index: int,
    ) -> None:
        self._window = window
        self._tv_index = tv_index
        self._movies_index = movies_index
        self._queue_index = queue_index

    def active_media_workspace(self):
        window = self._window
        current = window._tabs.currentIndex()
        if current == self._tv_index:
            return window._tv_workspace
        if current == self._movies_index:
            return window._movie_workspace
        return None

    @staticmethod
    def text_input_focused() -> bool:
        focused = QApplication.focusWidget()
        return isinstance(focused, (QLineEdit, QTextEdit))

    def queue_selected(self) -> None:
        workspace = self.active_media_workspace()
        if workspace is not None:
            workspace.queue_selected()

    def queue_checked(self) -> None:
        workspace = self.active_media_workspace()
        if workspace is not None:
            workspace.queue_checked()

    def toggle_focused_check(self) -> None:
        if self.text_input_focused():
            return
        workspace = self.active_media_workspace()
        if workspace is not None:
            workspace.toggle_focused_check()

    def on_escape(self) -> None:
        workspace = self.active_media_workspace()
        if workspace is not None and workspace.cancel_scan():
            return
        self._window._toast_manager.dismiss_topmost()

    def force_rematch(self) -> None:
        if self.text_input_focused():
            return
        workspace = self.active_media_workspace()
        if workspace is not None:
            workspace.force_rematch()

    def delete_from_shortcut(self) -> None:
        window = self._window
        if self.text_input_focused():
            return
        if window._tabs.currentIndex() == self._queue_index:
            window._queue_tab.remove_focused_checked()

    def enter_from_shortcut(self) -> None:
        window = self._window
        if self.text_input_focused():
            return
        if window._tabs.currentIndex() == self._queue_index:
            window._queue_tab.execute_focused()
