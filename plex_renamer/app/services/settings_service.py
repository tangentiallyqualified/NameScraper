"""
Lightweight JSON-backed user preferences.

Stores settings in ``~/.plex_renamer/settings.json``.  Provides typed
accessors for known keys with sensible defaults, plus generic get/set
for future extensibility.

Thread-safe: reads/writes are protected by a lock so the service can
be shared across worker threads and the UI thread.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ...constants import LOG_DIR, ensure_log_dir

_SETTINGS_FILE = LOG_DIR / "settings.json"

# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULTS: dict[str, object] = {
    # ISO 639-1 language + ISO 3166-1 country code used for TMDB API requests
    # and alternative-title prioritisation.  "en-US" is the TMDB default.
    "match_language": "en-US",
    # Hide shows/movies that are already properly named ("Plex Ready") from
    # the library roster.  True by default so the user focuses on items that
    # actually need action.
    "hide_already_named": True,
}


class SettingsService:
    """Read/write user preferences backed by a JSON file."""

    def __init__(self, path: Path = _SETTINGS_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, object] = dict(_DEFAULTS)
        self._load()

    # ── Public API ────────────────────────────────────────────────────

    def get(self, key: str) -> object:
        """Return a setting value, falling back to the built-in default."""
        with self._lock:
            return self._data.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value: object) -> None:
        """Update a setting and persist to disk."""
        with self._lock:
            self._data[key] = value
            self._save()

    # ── Typed accessors ───────────────────────────────────────────────

    @property
    def match_language(self) -> str:
        """TMDB language tag, e.g. ``"en-US"``, ``"fr-FR"``, ``"ja-JP"``."""
        return str(self.get("match_language"))

    @match_language.setter
    def match_language(self, value: str) -> None:
        self.set("match_language", value)

    @property
    def hide_already_named(self) -> bool:
        """Whether to hide Plex-ready items from the library roster."""
        return bool(self.get("hide_already_named"))

    @hide_already_named.setter
    def hide_already_named(self, value: bool) -> None:
        self.set("hide_already_named", value)

    @property
    def match_country(self) -> str:
        """ISO 3166-1 country code extracted from the language tag."""
        lang = self.match_language
        if "-" in lang:
            return lang.split("-", 1)[1]
        return lang.upper()

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self._data.update(stored)
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt file — use defaults

    def _save(self) -> None:
        ensure_log_dir()
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        tmp.replace(self._path)
