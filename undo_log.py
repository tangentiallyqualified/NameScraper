"""
Atomic undo log for rename operations.

Stores rename history as a JSON array in a fixed location
(~/.plex_renamer/rename_log.json) so it is always findable
regardless of the working directory when the app is launched.
"""

import json
import os
import shutil
import tempfile

from .constants import LOG_DIR, LOG_FILE


def load_log() -> list[dict]:
    """Load the rename history log."""
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_log(entries: list[dict]) -> None:
    """
    Write the log atomically — write to a temp file first, then rename.
    This prevents a half-written log if the process is interrupted.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(dir=LOG_DIR, suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(entries, f, indent=2)
        shutil.move(tmp_path, LOG_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
