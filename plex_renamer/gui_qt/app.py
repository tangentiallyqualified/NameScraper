"""PySide6 application bootstrap.

Launch with:
    python -m plex_renamer --qt
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt

_log = logging.getLogger(__name__)

_DEBUG_TRANSIENT_WINDOWS = os.environ.get(
    "PLEX_RENAMER_DEBUG_TRANSIENT_WINDOWS", ""
).strip().lower() not in {"", "0", "false", "no"}

# Window flags that identify transient platform helper windows.
_TRANSIENT_FLAGS = Qt.WindowType.SplashScreen | Qt.WindowType.Tool
_DIAGNOSTIC_FLAGS = _TRANSIENT_FLAGS | Qt.WindowType.Popup


def _window_flag_names(flags: Qt.WindowType) -> str:
    # Window-type flags share bits (e.g. Popup=0x9 is a bit-subset of
    # Tool=0xb and SplashScreen=0xf), so a bitwise AND against each named
    # type would match every entry for any single flag. Resolve the actual
    # window type first (mirrors the exact-equality comparison in
    # eventFilter below) and only report genuine extra bits separately.
    known_types = (
        (Qt.WindowType.ToolTip, "ToolTip"),
        (Qt.WindowType.SplashScreen, "SplashScreen"),
        (Qt.WindowType.Tool, "Tool"),
        (Qt.WindowType.Popup, "Popup"),
        (Qt.WindowType.Dialog, "Dialog"),
        (Qt.WindowType.Sheet, "Sheet"),
        (Qt.WindowType.Drawer, "Drawer"),
    )
    resolved_type = flags & Qt.WindowType.WindowType_Mask
    type_label = next(
        (label for flag, label in known_types if resolved_type == flag),
        hex(int(resolved_type)),
    )
    names = [type_label]
    modifier_bits = int(flags) & ~int(Qt.WindowType.WindowType_Mask)
    if modifier_bits:
        names.append(hex(modifier_bits))
    return "|".join(names)


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

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
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
            from PySide6.QtWidgets import QDialog, QMainWindow, QMenu

            if isinstance(obj, (QDialog, QMenu, QMainWindow)):
                return False
            name = obj.objectName()
            if name in {"toastManager", "toastCard"}:
                return False
            flags = obj.windowFlags()
            window_type = obj.windowType()
            if window_type == Qt.WindowType.ToolTip:
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
            # Window-type flags share bits (Popup=0x9 is a subset of Tool=0xb
            # and SplashScreen=0xf), so a bitwise AND also matches combobox
            # dropdowns. Compare the resolved type exactly.
            if window_type not in (Qt.WindowType.Tool, Qt.WindowType.SplashScreen):
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
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
    except ImportError:
        _log.error("PySide6 is not installed.  Install with:  pip install PySide6")
        sys.exit(1)

    from .main_window import MainWindow

    # Must be called BEFORE QApplication is constructed; ensures fractional
    # screen scales (125%, 150%) are not snapped to the nearest integer.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("NameScraper")
    popup_filter = _SuppressTransientPopups(app)
    app.installEventFilter(popup_filter)

    # Load the global theme stylesheet (rendered from theme.qss.tmpl)
    from . import theme as _theme

    try:
        app.setStyleSheet(_theme.load_stylesheet())
    except (OSError, KeyError) as exc:
        _log.warning("Theme stylesheet failed to load: %s", exc)

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())
