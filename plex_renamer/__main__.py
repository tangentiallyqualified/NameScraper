"""
Entry point for Plex Renamer.

Usage:
    python -m plex_renamer
"""

from .gui import PlexRenamerApp


def main():
    app = PlexRenamerApp()
    app.run()


if __name__ == "__main__":
    main()
