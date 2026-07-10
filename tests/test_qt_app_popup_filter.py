"""The transient-window suppressor must never touch Popup windows
(combobox dropdowns, completers) — only Tool/SplashScreen helpers."""
from __future__ import annotations

from conftest_qt import QtSmokeBase


class PopupFilterTest(QtSmokeBase):
    def _run_show_filter(self, window_type):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QWidget

        from plex_renamer.gui_qt.app import _SuppressTransientPopups

        filt = _SuppressTransientPopups()
        widget = QWidget(None, window_type)
        self.addCleanup(widget.deleteLater)
        widget.setWindowOpacity(1.0)
        filt.eventFilter(widget, QEvent(QEvent.Type.Show))
        return widget.windowOpacity()

    def test_popup_window_keeps_opacity(self):
        from PySide6.QtCore import Qt
        self.assertEqual(self._run_show_filter(Qt.WindowType.Popup), 1.0)

    def test_tool_window_is_suppressed(self):
        from PySide6.QtCore import Qt
        self.assertEqual(self._run_show_filter(Qt.WindowType.Tool), 0.0)

    def test_splash_window_is_suppressed(self):
        from PySide6.QtCore import Qt
        self.assertEqual(self._run_show_filter(Qt.WindowType.SplashScreen), 0.0)
