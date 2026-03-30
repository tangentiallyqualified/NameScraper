"""
Entry point for Plex Renamer.

Usage:
    python -m plex_renamer          # tkinter shell (current default)
    python -m plex_renamer --qt     # PySide6 shell (GUI3)
"""

import logging
import os
import sys


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() not in {"", "0", "false", "no"}


def _log_level() -> int:
    configured = os.environ.get("PLEX_RENAMER_LOG_LEVEL", "").strip().upper()
    if configured:
        return getattr(logging, configured, logging.INFO)
    if _env_flag("PLEX_RENAMER_DEBUG_TRANSIENT_WINDOWS"):
        return logging.DEBUG
    return logging.INFO


def main():
    logging.basicConfig(
        level=_log_level(),
        format="%(name)s %(levelname)s: %(message)s",
    )

    if "--qt" in sys.argv:
        from .gui_qt.app import run
        run()
    else:
        from .gui import PlexRenamerApp
        app = PlexRenamerApp()
        app.run()


if __name__ == "__main__":
    main()
