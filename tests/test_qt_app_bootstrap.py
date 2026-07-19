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

    def test_window_flag_names_renders_labels_for_known_flags(self):
        # The window-type flags share bits (Tool=0xb includes the
        # Dialog/Popup/Window bits, etc.), so the helper must compare the
        # resolved type exactly rather than bitwise-AND against each named
        # flag. Distinct window types resolve to distinct, correct labels.
        for flag, expected in (
            (Qt.WindowType.ToolTip, "ToolTip"),
            (Qt.WindowType.SplashScreen, "SplashScreen"),
            (Qt.WindowType.Tool, "Tool"),
            (Qt.WindowType.Popup, "Popup"),
            (Qt.WindowType.Dialog, "Dialog"),
            (Qt.WindowType.Sheet, "Sheet"),
            (Qt.WindowType.Drawer, "Drawer"),
        ):
            with self.subTest(flag=flag):
                self.assertEqual(_window_flag_names(flag), expected)

    def test_window_flag_names_appends_modifier_flags_outside_the_type_mask(self):
        combined = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        self.assertEqual(
            _window_flag_names(combined),
            f"Tool|{hex(int(Qt.WindowType.FramelessWindowHint))}",
        )

    def test_window_flag_names_keeps_unmatched_type_hex_alongside_modifiers(self):
        # A base type outside the known table (Window=0x1) must not be
        # silently discarded when modifier bits are present; the resolved
        # type's hex is reported alongside the modifier hex.
        combined = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        self.assertEqual(
            _window_flag_names(combined),
            f"{hex(int(Qt.WindowType.Window))}|{hex(int(Qt.WindowType.FramelessWindowHint))}",
        )

    def test_window_flag_names_falls_back_to_hex_for_no_known_flags(self):
        self.assertEqual(_window_flag_names(Qt.WindowType.Widget), "0x0")

    def test_debug_mode_logs_transient_candidates_and_still_suppresses(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QWidget

        import plex_renamer.gui_qt.app as app_module

        window = QWidget(None, Qt.WindowType.Tool)
        self.addCleanup(window.deleteLater)
        with (
            patch.object(app_module, "_DEBUG_TRANSIENT_WINDOWS", True),
            self.assertLogs("plex_renamer.gui_qt.app", level="DEBUG") as captured,
        ):
            handled = self.popup_filter.eventFilter(window, QEvent(QEvent.Type.Show))
        self.assertFalse(handled)
        self.assertEqual(window.windowOpacity(), 0.0)
        self.assertTrue(any("Qt transient candidate" in message for message in captured.output))
