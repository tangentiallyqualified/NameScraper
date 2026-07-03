"""Menu-bar and shortcut safety checks (GUI V4 §14)."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence

from conftest_qt import QtSmokeBase


def _all_actions(window):
    # PySide6/shiboken note: the top-level QMenu actions returned by
    # menu_action.menu() only stay valid Python-side while something keeps
    # menu_bar.actions() alive. Anchor the keep-alive list on `window` so it
    # survives as long as the caller holds `window` (matches every call site).
    actions = list(window.actions())
    top_level_actions = list(window.menuBar().actions())
    window._test_menu_keepalive = top_level_actions
    for menu_action in top_level_actions:
        menu = menu_action.menu()
        if menu is not None:
            actions.extend(menu.actions())
    return actions


class QtChromeTests(QtSmokeBase):
    def test_no_ctrl_z_shortcut_registered(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        ctrl_z = QKeySequence("Ctrl+Z")
        for action in _all_actions(window):
            self.assertNotEqual(
                action.shortcut(), ctrl_z, f"Ctrl+Z still bound to {action.text()!r}"
            )
        window.close()

    def test_edit_menu_has_no_undo_entry(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        edit_action = next(
            a for a in window.menuBar().actions() if "Edit" in a.text()
        )
        edit_menu = edit_action.menu()
        labels = [a.text() for a in edit_menu.actions() if a.text()]
        self.assertFalse(any("undo" in label.lower() for label in labels))
        window.close()
