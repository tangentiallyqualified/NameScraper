"""Tests for the Qt bootstrap helpers in plex_renamer/gui_qt/app.py."""

from __future__ import annotations

from conftest_qt import QtSmokeBase
from PySide6.QtCore import QEvent, Qt

from plex_renamer.gui_qt.app import _SuppressTransientPopups, _window_flag_names


class QtAppBootstrapTests(QtSmokeBase):
    def setUp(self):
        super().setUp()
        self.popup_filter = _SuppressTransientPopups()

    def test_help_events_are_consumed(self):
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        for event_type in (
            QEvent.Type.WhatsThis,
            QEvent.Type.QueryWhatsThis,
            QEvent.Type.StatusTip,
        ):
            with self.subTest(event_type=event_type):
                self.assertTrue(self.popup_filter.eventFilter(widget, QEvent(event_type)))

    def test_tool_and_splash_windows_are_made_invisible(self):
        from PySide6.QtWidgets import QWidget

        for flag in (Qt.WindowType.Tool, Qt.WindowType.SplashScreen):
            with self.subTest(flag=flag):
                window = QWidget(None, flag)
                self.addCleanup(window.deleteLater)
                handled = self.popup_filter.eventFilter(window, QEvent(QEvent.Type.Show))
                self.assertFalse(handled)
                self.assertEqual(window.windowOpacity(), 0.0)

    def test_dialogs_menus_and_main_windows_are_never_suppressed(self):
        from PySide6.QtWidgets import QDialog, QMainWindow, QMenu

        for factory in (QDialog, QMenu, QMainWindow):
            with self.subTest(widget=factory.__name__):
                widget = factory()
                self.addCleanup(widget.deleteLater)
                self.assertFalse(self.popup_filter.eventFilter(widget, QEvent(QEvent.Type.Show)))
                self.assertEqual(widget.windowOpacity(), 1.0)

    def test_toast_windows_are_exempt(self):
        from PySide6.QtWidgets import QWidget

        toast = QWidget(None, Qt.WindowType.Tool)
        toast.setObjectName("toastManager")
        self.addCleanup(toast.deleteLater)
        self.assertFalse(self.popup_filter.eventFilter(toast, QEvent(QEvent.Type.Show)))
        self.assertEqual(toast.windowOpacity(), 1.0)

    def test_tooltip_windows_are_exempt(self):
        from PySide6.QtWidgets import QWidget

        tip = QWidget(None, Qt.WindowType.ToolTip)
        self.addCleanup(tip.deleteLater)
        self.assertFalse(self.popup_filter.eventFilter(tip, QEvent(QEvent.Type.Show)))
        self.assertEqual(tip.windowOpacity(), 1.0)

    def test_popup_windows_are_not_suppressed(self):
        from PySide6.QtWidgets import QWidget

        popup = QWidget(None, Qt.WindowType.Popup)
        self.addCleanup(popup.deleteLater)
        self.assertFalse(self.popup_filter.eventFilter(popup, QEvent(QEvent.Type.Show)))
        self.assertEqual(popup.windowOpacity(), 1.0)

    def test_child_widgets_are_ignored(self):
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        child = QWidget(parent)
        self.assertFalse(self.popup_filter.eventFilter(child, QEvent(QEvent.Type.Show)))
        self.assertEqual(child.windowOpacity(), 1.0)

    def test_window_flag_names_falls_back_to_hex_for_no_known_flags(self):
        self.assertEqual(_window_flag_names(Qt.WindowType.Widget), "0x0")
