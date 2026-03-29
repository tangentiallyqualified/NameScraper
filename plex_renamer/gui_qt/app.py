"""PySide6 application bootstrap (GUI3 entry point).

Launch with:
    python -m plex_renamer --qt
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt

_log = logging.getLogger(__name__)

_THEME_PATH = Path(__file__).parent / "resources" / "theme.qss"


class _SuppressTransientHelpPopups(QObject):
    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtWidgets import QDialog, QMenu, QWidget

        if event.type() in {
            QEvent.Type.ToolTip,
            QEvent.Type.WhatsThis,
            QEvent.Type.QueryWhatsThis,
            QEvent.Type.StatusTip,
        }:
            return True
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget):
            if isinstance(obj, (QDialog, QMenu)):
                return False
            if obj.objectName() in {"toastManager", "toastCard"}:
                return False
            if not obj.isWindow():
                return False
            flags = obj.windowFlags()
            transient_flags = (
                Qt.WindowType.ToolTip
                | Qt.WindowType.Popup
                | Qt.WindowType.Tool
                | Qt.WindowType.SplashScreen
            )
            if flags & transient_flags:
                size = obj.size()
                if size.width() <= 480 and size.height() <= 320:
                    event.accept()
                    obj.hide()
                    return True
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
    help_popup_filter = _SuppressTransientHelpPopups(app)
    app.installEventFilter(help_popup_filter)
    app._help_popup_filter = help_popup_filter

    # Load the global theme stylesheet
    if _THEME_PATH.exists():
        app.setStyleSheet(_THEME_PATH.read_text(encoding="utf-8"))
    else:
        _log.warning("Theme file not found at %s", _THEME_PATH)

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())
