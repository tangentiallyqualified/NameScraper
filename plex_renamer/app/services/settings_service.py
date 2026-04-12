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
import logging
import threading
from pathlib import Path

from ...constants import LOG_DIR, ensure_log_dir
from ._settings_schema import (
    DEFAULT_SETTINGS,
    MAX_RECENT_FOLDERS,
    build_valid_settings_data,
)

_log = logging.getLogger(__name__)

_SETTINGS_FILE = LOG_DIR / "settings.json"


class SettingsService:
    """Read/write user preferences backed by a JSON file."""

    def __init__(self, path: Path = _SETTINGS_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, object] = dict(DEFAULT_SETTINGS)
        self._load()

    # ── Public API ────────────────────────────────────────────────────

    def get(self, key: str) -> object:
        """Return a setting value, falling back to the built-in default."""
        with self._lock:
            return self._data.get(key, DEFAULT_SETTINGS.get(key))

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

    # ── Display ────────────────────────────────────────────────────────

    @property
    def view_mode(self) -> str:
        """``"normal"`` or ``"compact"``."""
        val = self.get("view_mode")
        return val if val in ("normal", "compact") else "normal"

    @view_mode.setter
    def view_mode(self, value: str) -> None:
        if value not in ("normal", "compact"):
            raise ValueError(f"view_mode must be 'normal' or 'compact', got {value!r}")
        self.set("view_mode", value)

    @property
    def show_companion_files(self) -> bool:
        """Whether companion files are visible in the preview panel."""
        return bool(self.get("show_companion_files"))

    @show_companion_files.setter
    def show_companion_files(self, value: bool) -> None:
        self.set("show_companion_files", bool(value))

    @property
    def show_discovery_info(self) -> bool:
        """Whether the discovery info section is shown in the detail panel."""
        return bool(self.get("show_discovery_info"))

    @show_discovery_info.setter
    def show_discovery_info(self, value: bool) -> None:
        self.set("show_discovery_info", bool(value))

    # ── Matching ───────────────────────────────────────────────────────

    @property
    def auto_accept_threshold(self) -> float:
        """Confidence threshold for auto-accepting a TMDB match."""
        val = self.get("auto_accept_threshold")
        try:
            f = float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.55
        return max(0.50, min(1.00, f))

    @auto_accept_threshold.setter
    def auto_accept_threshold(self, value: float) -> None:
        self.set("auto_accept_threshold", max(0.50, min(1.00, float(value))))

    @property
    def show_confidence_bars(self) -> bool:
        """Whether per-episode confidence bars are shown in the preview."""
        return bool(self.get("show_confidence_bars"))

    @show_confidence_bars.setter
    def show_confidence_bars(self, value: bool) -> None:
        self.set("show_confidence_bars", bool(value))

    # ── Window state ───────────────────────────────────────────────────

    @property
    def window_geometry(self) -> list[int] | None:
        """``[x, y, width, height]`` or ``None`` if never persisted."""
        val = self.get("window_geometry")
        if isinstance(val, list) and len(val) == 4:
            try:
                return [int(v) for v in val]
            except (TypeError, ValueError):
                pass
        return None

    @window_geometry.setter
    def window_geometry(self, value: list[int] | None) -> None:
        if value is not None:
            if not (isinstance(value, list) and len(value) == 4):
                raise ValueError("window_geometry must be [x, y, width, height]")
            value = [int(v) for v in value]
        self.set("window_geometry", value)

    @property
    def splitter_positions(self) -> list[int] | None:
        """``[roster_width, preview_width, detail_width]`` or ``None``."""
        val = self.get("splitter_positions")
        if isinstance(val, list) and len(val) == 3:
            try:
                return [int(v) for v in val]
            except (TypeError, ValueError):
                pass
        return None

    @splitter_positions.setter
    def splitter_positions(self, value: list[int] | None) -> None:
        if value is not None:
            if not (isinstance(value, list) and len(value) == 3):
                raise ValueError("splitter_positions must be [roster, preview, detail]")
            value = [int(v) for v in value]
        self.set("splitter_positions", value)

    # ── Recent folders ─────────────────────────────────────────────────

    @property
    def recent_tv_folders(self) -> list[str]:
        """Most-recently-used TV library folders, newest first."""
        val = self.get("recent_tv_folders")
        if isinstance(val, list):
            return [str(v) for v in val[:MAX_RECENT_FOLDERS]]
        return []

    @property
    def recent_movie_folders(self) -> list[str]:
        """Most-recently-used movie folders, newest first."""
        val = self.get("recent_movie_folders")
        if isinstance(val, list):
            return [str(v) for v in val[:MAX_RECENT_FOLDERS]]
        return []

    def add_recent_tv_folder(self, path: str) -> None:
        """Push *path* to the front of the recent TV folders list."""
        self._push_recent("recent_tv_folders", path)

    def add_recent_movie_folder(self, path: str) -> None:
        """Push *path* to the front of the recent movie folders list."""
        self._push_recent("recent_movie_folders", path)

    def _push_recent(self, key: str, path: str) -> None:
        current = [str(v) for v in (self.get(key) or [])]  # type: ignore[union-attr]
        # Remove duplicates of this path (case-insensitive on Windows).
        normalized = path.replace("\\", "/").lower()
        current = [p for p in current
                   if p.replace("\\", "/").lower() != normalized]
        current.insert(0, path)
        self.set(key, current[:MAX_RECENT_FOLDERS])

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self._data = build_valid_settings_data(stored, logger=_log)
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt file — use defaults

    def _save(self) -> None:
        ensure_log_dir()
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        tmp.replace(self._path)
