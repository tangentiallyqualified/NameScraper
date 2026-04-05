"""PySide6 application bootstrap (GUI3 entry point).

Launch with:
    python -m plex_renamer --qt
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt

_log = logging.getLogger(__name__)

_THEME_PATH = Path(__file__).parent / "resources" / "theme.qss"
_DEBUG_TRANSIENT_WINDOWS = os.environ.get(
    "PLEX_RENAMER_DEBUG_TRANSIENT_WINDOWS", ""
).strip().lower() not in {"", "0", "false", "no"}

# Window flags that identify transient platform helper windows.
_TRANSIENT_FLAGS = (
    Qt.WindowType.SplashScreen
    | Qt.WindowType.Tool
)
_DIAGNOSTIC_FLAGS = _TRANSIENT_FLAGS | Qt.WindowType.Popup


def _window_flag_names(flags: Qt.WindowType) -> str:
    names: list[str] = []
    known_flags = (
        (Qt.WindowType.ToolTip, "ToolTip"),
        (Qt.WindowType.SplashScreen, "SplashScreen"),
        (Qt.WindowType.Tool, "Tool"),
        (Qt.WindowType.Popup, "Popup"),
        (Qt.WindowType.Dialog, "Dialog"),
        (Qt.WindowType.Sheet, "Sheet"),
        (Qt.WindowType.Drawer, "Drawer"),
    )
    for flag, label in known_flags:
        if flags & flag:
            names.append(label)
    return "|".join(names) if names else hex(int(flags))


class _SuppressTransientPopups(QObject):
    """Suppress unwanted transient windows in the Qt shell.

    Two suppression strategies:

     1. **Event-type suppression** — WhatsThis and StatusTip events are
         consumed before Qt creates any helper window.  No flicker.

    2. **Transient-window suppression** — On Windows, Qt's platform
    integration and style engine create short-lived native helper
    windows (typically ToolTip-, SplashScreen-, or Tool-flagged)
    during heavy widget operations like QListWidget rebuilds and
    setStyleSheet cascades.  These flash on screen for one or two
    compositor frames.  An earlier version tried calling
    ``obj.hide()`` on the Show event, but hide() itself triggers a
    second native message and the show → hide sequence is visible
    as flicker.

       The current approach sets the window opacity to 0 *before* the
       compositor can render the next frame (``setWindowOpacity`` maps
       to the synchronous Win32 ``SetLayeredWindowAttributes`` call),
       then schedules the window for deletion.  The window is never
       visible to the user.
    """

    def eventFilter(self, obj, event) -> bool:
        if event.type() in {
            QEvent.Type.WhatsThis,
            QEvent.Type.QueryWhatsThis,
            QEvent.Type.StatusTip,
        }:
            return True

        if event.type() == QEvent.Type.Show:
            from PySide6.QtWidgets import QWidget
            if not isinstance(obj, QWidget) or not obj.isWindow():
                return False
            # Never suppress real dialogs, menus, or our own widgets.
            from PySide6.QtWidgets import QDialog, QMenu, QMainWindow
            if isinstance(obj, (QDialog, QMenu, QMainWindow)):
                return False
            name = obj.objectName()
            if name in {"toastManager", "toastCard"}:
                return False
            flags = obj.windowFlags()
            if obj.windowType() == Qt.WindowType.ToolTip:
                return False
            if _DEBUG_TRANSIENT_WINDOWS and flags & _DIAGNOSTIC_FLAGS:
                _log.debug(
                    "Qt transient candidate: class=%s name=%r title=%r flags=%s size=%sx%s",
                    obj.metaObject().className(),
                    name,
                    obj.windowTitle(),
                    _window_flag_names(flags),
                    obj.width(),
                    obj.height(),
                )
            if not (flags & _TRANSIENT_FLAGS):
                return False
            # Make the window invisible synchronously.  setWindowOpacity(0)
            # maps to Win32 SetLayeredWindowAttributes — takes effect before
            # the compositor can render the next frame.  Do NOT close() or
            # deleteLater() — Qt's platform layer may still need the window.
            obj.setWindowOpacity(0)
            return False

        return False


def run() -> None:
    """Create the QApplication, main window, and enter the event loop."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        _log.error(
            "PySide6 is not installed.  Install with:  pip install plex-renamer[qt]"
        )
        sys.exit(1)

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Plex Renamer")
    popup_filter = _SuppressTransientPopups(app)
    app.installEventFilter(popup_filter)
    app._popup_filter = popup_filter

    # Load the global theme stylesheet
    if _THEME_PATH.exists():
        app.setStyleSheet(_THEME_PATH.read_text(encoding="utf-8"))
    else:
        _log.warning("Theme file not found at %s", _THEME_PATH)

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())
