"""PySide6 application bootstrap (GUI3 entry point).

Launch with:
    python -m plex_renamer --qt
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

_THEME_PATH = Path(__file__).parent / "resources" / "theme.qss"


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

    # Load the global theme stylesheet
    if _THEME_PATH.exists():
        app.setStyleSheet(_THEME_PATH.read_text(encoding="utf-8"))
    else:
        _log.warning("Theme file not found at %s", _THEME_PATH)

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())
