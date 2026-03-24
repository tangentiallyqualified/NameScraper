"""
Entry point for Plex Renamer.

Usage:
    python -m plex_renamer
"""

import logging

from .gui import PlexRenamerApp


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s %(levelname)s: %(message)s",
    )
    app = PlexRenamerApp()
    app.run()


if __name__ == "__main__":
    main()
