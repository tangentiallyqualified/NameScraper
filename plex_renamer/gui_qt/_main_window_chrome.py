"""Menu-bar and shortcut helpers for the main window."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence


class MainWindowChromeCoordinator:
    def __init__(self, window: Any, *, settings_index: int) -> None:
        self._window = window
        self._settings_index = settings_index

    def build_menu_bar(self) -> None:
        window = self._window
        menu_bar = window.menuBar()

        file_menu = menu_bar.addMenu("&File")

        open_tv = file_menu.addAction("Open TV Folder...")
        open_tv.setShortcut(QKeySequence("Ctrl+O"))
        open_tv.triggered.connect(lambda: window._open_folder("tv"))

        open_movie = file_menu.addAction("Open Movie Folder...")
        open_movie.triggered.connect(lambda: window._open_folder("movie"))

        file_menu.addSeparator()

        window._recent_tv_menu = file_menu.addMenu("Recent TV Folders")
        window._recent_movie_menu = file_menu.addMenu("Recent Movie Folders")
        window._rebuild_recent_menus()

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(window.close)

        edit_menu = menu_bar.addMenu("&Edit")

        undo_action = edit_menu.addAction("&Undo Last Rename")
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(window._on_undo)

        edit_menu.addSeparator()

        settings_action = edit_menu.addAction("&Settings")
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(
            lambda: window._tabs.setCurrentIndex(self._settings_index)
        )

        view_menu = menu_bar.addMenu("&View")

        window._compact_action = view_menu.addAction("Compact Mode")
        window._compact_action.setCheckable(True)
        window._compact_action.setChecked(
            window.settings_service.view_mode == "compact"
        )
        window._compact_action.toggled.connect(window._on_compact_toggled)

        window._companion_action = view_menu.addAction("Show Companion Files")
        window._companion_action.setCheckable(True)
        window._companion_action.setChecked(
            window.settings_service.show_companion_files
        )
        window._companion_action.toggled.connect(window._on_companion_toggled)

        help_menu = menu_bar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(window._on_about)

    def build_shortcuts(self) -> None:
        window = self._window

        for index in range(5):
            action = QAction(window)
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(
                lambda _=False, tab_index=index: window._tabs.setCurrentIndex(tab_index)
            )
            window.addAction(action)

        queue_selected = QAction(window)
        queue_selected.setShortcut(QKeySequence("Ctrl+Q"))
        queue_selected.triggered.connect(window._queue_selected_from_shortcut)
        window.addAction(queue_selected)

        queue_checked = QAction(window)
        queue_checked.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        queue_checked.triggered.connect(window._queue_checked_from_shortcut)
        window.addAction(queue_checked)

        toggle_check = QAction(window)
        toggle_check.setShortcut(QKeySequence(Qt.Key.Key_Space))
        toggle_check.triggered.connect(window._toggle_focused_check)
        window.addAction(toggle_check)

        escape_action = QAction(window)
        escape_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        escape_action.triggered.connect(window._on_escape)
        window.addAction(escape_action)

        force_rematch = QAction(window)
        force_rematch.setShortcut(QKeySequence(Qt.Key.Key_F5))
        force_rematch.triggered.connect(window._force_rematch_from_shortcut)
        window.addAction(force_rematch)

        delete_action = QAction(window)
        delete_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        delete_action.triggered.connect(window._delete_from_shortcut)
        window.addAction(delete_action)

        enter_action = QAction(window)
        enter_action.setShortcut(QKeySequence(Qt.Key.Key_Return))
        enter_action.triggered.connect(window._enter_from_shortcut)
        window.addAction(enter_action)
