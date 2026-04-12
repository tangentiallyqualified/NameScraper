"""Schema, defaults, and validation helpers for SettingsService."""

from __future__ import annotations

import logging
from collections.abc import Mapping

SETTINGS_SCHEMA: dict[str, tuple[type, ...]] = {
    "match_language": (str,),
    "hide_already_named": (bool,),
    "view_mode": (str,),
    "show_companion_files": (bool,),
    "show_discovery_info": (bool,),
    "auto_accept_threshold": (int, float),
    "show_confidence_bars": (bool,),
    "window_geometry": (list, type(None)),
    "splitter_positions": (list, type(None)),
    "recent_tv_folders": (list,),
    "recent_movie_folders": (list,),
}

MAX_RECENT_FOLDERS = 10

DEFAULT_SETTINGS: dict[str, object] = {
    "match_language": "en-US",
    "hide_already_named": True,
    "view_mode": "normal",
    "show_companion_files": True,
    "show_discovery_info": False,
    "auto_accept_threshold": 0.55,
    "show_confidence_bars": True,
    "window_geometry": None,
    "splitter_positions": None,
    "recent_tv_folders": [],
    "recent_movie_folders": [],
}


def build_valid_settings_data(
    stored: Mapping[str, object] | None,
    *,
    logger: logging.Logger | None = None,
) -> dict[str, object]:
    data = dict(DEFAULT_SETTINGS)
    if stored is None:
        return data

    for key, value in stored.items():
        if key not in SETTINGS_SCHEMA:
            if logger is not None:
                logger.warning("settings: unknown key %r (ignored)", key)
            continue
        data[key] = value

    for key, allowed in SETTINGS_SCHEMA.items():
        value = data[key]
        if isinstance(value, allowed):
            continue
        if logger is not None:
            logger.warning(
                "settings: bad type for %r — expected %s, got %s (reset to default)",
                key,
                "/".join(item.__name__ for item in allowed),
                type(value).__name__,
            )
        data[key] = DEFAULT_SETTINGS[key]

    return data
