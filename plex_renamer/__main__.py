"""
Entry point for Plex Renamer.

Usage:
    python -m plex_renamer          # tkinter shell (current default)
    python -m plex_renamer --qt     # PySide6 shell (GUI3)
"""

import logging
import sys


def main():
    logging.basicConfig(
        level=logging.INFO,
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
