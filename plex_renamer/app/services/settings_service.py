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
from .output_destination_service import (
    OutputDestinationStatus,
    validate_output_folder,
    validate_scan_output_relationship,
)

_log = logging.getLogger(__name__)

_SETTINGS_FILE = LOG_DIR / "settings.json"

_CACHE_MIN_BYTES = 64 * 1024 * 1024  # 64 MiB floor
_CACHE_MAX_BYTES = 8 * 1024**3  # 8 GiB ceiling (S2)


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
    def tv_metadata_source(self) -> str:
        """Active TV metadata provider name ("tmdb" or "tvdb")."""
        return str(self.get("tv_metadata_source"))

    @tv_metadata_source.setter
    def tv_metadata_source(self, value: str) -> None:
        self.set("tv_metadata_source", value)

    @property
    def hide_already_named(self) -> bool:
        """Whether to hide fully-ready items from the library roster."""
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

    @property
    def tv_output_folder(self) -> str:
        """Configured output root for completed TV show jobs."""
        return str(self.get("tv_output_folder") or "")

    @tv_output_folder.setter
    def tv_output_folder(self, value: str) -> None:
        self.set("tv_output_folder", str(value or ""))

    @property
    def movie_output_folder(self) -> str:
        """Configured output root for completed movie jobs."""
        return str(self.get("movie_output_folder") or "")

    @movie_output_folder.setter
    def movie_output_folder(self, value: str) -> None:
        self.set("movie_output_folder", str(value or ""))

    @property
    def valid_tv_output_folder(self) -> Path | None:
        status = validate_output_folder(self.tv_output_folder)
        return status.path if status.valid else None

    @property
    def valid_movie_output_folder(self) -> Path | None:
        status = validate_output_folder(self.movie_output_folder)
        return status.path if status.valid else None

    def validate_output_folder(self, path_value: str | Path | None) -> OutputDestinationStatus:
        return validate_output_folder(path_value)

    def validate_tv_output_folder(self) -> OutputDestinationStatus:
        return validate_output_folder(self.tv_output_folder)

    def validate_movie_output_folder(self) -> OutputDestinationStatus:
        return validate_output_folder(self.movie_output_folder)

    def validate_scan_output_relationship(
        self,
        source_folder: str | Path,
        output_folder: str | Path,
    ) -> OutputDestinationStatus:
        return validate_scan_output_relationship(source_folder, output_folder)

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
    def cache_max_size_bytes(self) -> int:
        """On-disk metadata cache byte cap, clamped to [64 MiB, 8 GiB]."""
        raw = int(self.get("cache_max_size_bytes") or (1024**3))
        return max(_CACHE_MIN_BYTES, min(_CACHE_MAX_BYTES, raw))

    @cache_max_size_bytes.setter
    def cache_max_size_bytes(self, value: int) -> None:
        clamped = max(_CACHE_MIN_BYTES, min(_CACHE_MAX_BYTES, int(value)))
        self.set("cache_max_size_bytes", clamped)

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
    def episode_auto_accept_threshold(self) -> float:
        """Confidence threshold for auto-accepting episode mappings."""
        val = self.get("episode_auto_accept_threshold")
        try:
            f = float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.85
        return max(0.50, min(1.00, f))

    @episode_auto_accept_threshold.setter
    def episode_auto_accept_threshold(self, value: float) -> None:
        self.set("episode_auto_accept_threshold", max(0.50, min(1.00, float(value))))

    @property
    def show_confidence_bars(self) -> bool:
        """Whether per-episode confidence bars are shown in the preview."""
        return bool(self.get("show_confidence_bars"))

    @show_confidence_bars.setter
    def show_confidence_bars(self, value: bool) -> None:
        self.set("show_confidence_bars", bool(value))

    # ── AutoMux (mkvmerge) ────────────────────────────────────────────

    @property
    def mkvmerge_path(self) -> str:
        return str(self.get("mkvmerge_path"))

    @mkvmerge_path.setter
    def mkvmerge_path(self, value: str) -> None:
        self.set("mkvmerge_path", value)

    @property
    def automux_merge_subs(self) -> bool:
        return bool(self.get("automux_merge_subs"))

    @automux_merge_subs.setter
    def automux_merge_subs(self, value: bool) -> None:
        self.set("automux_merge_subs", bool(value))

    @property
    def automux_merge_sub_languages(self) -> list[str]:
        return [str(v) for v in self.get("automux_merge_sub_languages")]

    @automux_merge_sub_languages.setter
    def automux_merge_sub_languages(self, value: list[str]) -> None:
        self.set("automux_merge_sub_languages", list(value))

    @property
    def automux_default_sub_language(self) -> str:
        return str(self.get("automux_default_sub_language"))

    @automux_default_sub_language.setter
    def automux_default_sub_language(self, value: str) -> None:
        self.set("automux_default_sub_language", value)

    @property
    def automux_untagged_sub_language(self) -> str:
        return str(self.get("automux_untagged_sub_language"))

    @automux_untagged_sub_language.setter
    def automux_untagged_sub_language(self, value: str) -> None:
        self.set("automux_untagged_sub_language", value)

    @property
    def automux_strip_subs(self) -> bool:
        return bool(self.get("automux_strip_subs"))

    @automux_strip_subs.setter
    def automux_strip_subs(self, value: bool) -> None:
        self.set("automux_strip_subs", bool(value))

    @property
    def automux_retain_sub_languages(self) -> list[str]:
        return [str(v) for v in self.get("automux_retain_sub_languages")]

    @automux_retain_sub_languages.setter
    def automux_retain_sub_languages(self, value: list[str]) -> None:
        self.set("automux_retain_sub_languages", list(value))

    @property
    def automux_strip_audio(self) -> bool:
        return bool(self.get("automux_strip_audio"))

    @automux_strip_audio.setter
    def automux_strip_audio(self, value: bool) -> None:
        self.set("automux_strip_audio", bool(value))

    @property
    def automux_retain_audio_languages(self) -> list[str]:
        return [str(v) for v in self.get("automux_retain_audio_languages")]

    @automux_retain_audio_languages.setter
    def automux_retain_audio_languages(self, value: list[str]) -> None:
        self.set("automux_retain_audio_languages", list(value))

    @property
    def automux_default_audio_language(self) -> str:
        return str(self.get("automux_default_audio_language"))

    @automux_default_audio_language.setter
    def automux_default_audio_language(self, value: str) -> None:
        self.set("automux_default_audio_language", value)

    @property
    def automux_strip_track_names(self) -> bool:
        return bool(self.get("automux_strip_track_names"))

    @automux_strip_track_names.setter
    def automux_strip_track_names(self, value: bool) -> None:
        self.set("automux_strip_track_names", bool(value))

    @property
    def automux_no_fear(self) -> bool:
        return bool(self.get("automux_no_fear"))

    @automux_no_fear.setter
    def automux_no_fear(self, value: bool) -> None:
        self.set("automux_no_fear", bool(value))

    @property
    def automux_exclude_commentary(self) -> bool:
        return bool(self.get("automux_exclude_commentary"))

    @automux_exclude_commentary.setter
    def automux_exclude_commentary(self, value: bool) -> None:
        self.set("automux_exclude_commentary", bool(value))

    @property
    def automux_convert_containers(self) -> bool:
        return bool(self.get("automux_convert_containers"))

    @automux_convert_containers.setter
    def automux_convert_containers(self, value: bool) -> None:
        self.set("automux_convert_containers", bool(value))

    # ── Metadata export ───────────────────────────────────────────────────

    @property
    def metadata_enabled(self) -> bool:
        return bool(self.get("metadata_enabled"))

    @metadata_enabled.setter
    def metadata_enabled(self, value: bool) -> None:
        self.set("metadata_enabled", bool(value))

    @property
    def metadata_prefer_local(self) -> bool:
        return bool(self.get("metadata_prefer_local"))

    @metadata_prefer_local.setter
    def metadata_prefer_local(self, value: bool) -> None:
        self.set("metadata_prefer_local", bool(value))

    @property
    def metadata_write_nfo(self) -> bool:
        return bool(self.get("metadata_write_nfo"))

    @metadata_write_nfo.setter
    def metadata_write_nfo(self, value: bool) -> None:
        self.set("metadata_write_nfo", bool(value))

    @property
    def metadata_write_episode_nfo(self) -> bool:
        return bool(self.get("metadata_write_episode_nfo"))

    @metadata_write_episode_nfo.setter
    def metadata_write_episode_nfo(self, value: bool) -> None:
        self.set("metadata_write_episode_nfo", bool(value))

    @property
    def metadata_write_poster(self) -> bool:
        return bool(self.get("metadata_write_poster"))

    @metadata_write_poster.setter
    def metadata_write_poster(self, value: bool) -> None:
        self.set("metadata_write_poster", bool(value))

    @property
    def metadata_write_fanart(self) -> bool:
        return bool(self.get("metadata_write_fanart"))

    @metadata_write_fanart.setter
    def metadata_write_fanart(self, value: bool) -> None:
        self.set("metadata_write_fanart", bool(value))

    @property
    def metadata_write_season_posters(self) -> bool:
        return bool(self.get("metadata_write_season_posters"))

    @metadata_write_season_posters.setter
    def metadata_write_season_posters(self, value: bool) -> None:
        self.set("metadata_write_season_posters", bool(value))

    @property
    def metadata_write_episode_thumbs(self) -> bool:
        return bool(self.get("metadata_write_episode_thumbs"))

    @metadata_write_episode_thumbs.setter
    def metadata_write_episode_thumbs(self, value: bool) -> None:
        self.set("metadata_write_episode_thumbs", bool(value))

    @property
    def metadata_write_clearlogo(self) -> bool:
        return bool(self.get("metadata_write_clearlogo"))

    @metadata_write_clearlogo.setter
    def metadata_write_clearlogo(self, value: bool) -> None:
        self.set("metadata_write_clearlogo", bool(value))

    @property
    def metadata_plex_naming(self) -> bool:
        return bool(self.get("metadata_plex_naming"))

    @metadata_plex_naming.setter
    def metadata_plex_naming(self, value: bool) -> None:
        self.set("metadata_plex_naming", bool(value))

    @property
    def metadata_embed_title(self) -> bool:
        return bool(self.get("metadata_embed_title"))

    @metadata_embed_title.setter
    def metadata_embed_title(self, value: bool) -> None:
        self.set("metadata_embed_title", bool(value))

    @property
    def metadata_embed_cover(self) -> bool:
        return bool(self.get("metadata_embed_cover"))

    @metadata_embed_cover.setter
    def metadata_embed_cover(self, value: bool) -> None:
        self.set("metadata_embed_cover", bool(value))

    @property
    def metadata_embed_tags(self) -> bool:
        return bool(self.get("metadata_embed_tags"))

    @metadata_embed_tags.setter
    def metadata_embed_tags(self, value: bool) -> None:
        self.set("metadata_embed_tags", bool(value))

    @property
    def automux_any_enabled(self) -> bool:
        """True when at least one AutoMux action toggle is on (spec §8.1)."""
        return self.automux_merge_subs or self.automux_strip_subs or self.automux_strip_audio

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
        current = [p for p in current if p.replace("\\", "/").lower() != normalized]
        current.insert(0, path)
        self.set(key, current[:MAX_RECENT_FOLDERS])

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
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
