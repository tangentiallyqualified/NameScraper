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
    "episode_auto_accept_threshold": (int, float),
    "tv_output_folder": (str,),
    "movie_output_folder": (str,),
    "show_confidence_bars": (bool,),
    "window_geometry": (list, type(None)),
    "splitter_positions": (list, type(None)),
    "recent_tv_folders": (list,),
    "recent_movie_folders": (list,),
    "cache_max_size_bytes": (int,),
    "mkvmerge_path": (str,),
    "automux_merge_subs": (bool,),
    "automux_merge_sub_languages": (list,),
    "automux_default_sub_language": (str,),
    "automux_untagged_sub_language": (str,),
    "automux_strip_subs": (bool,),
    "automux_retain_sub_languages": (list,),
    "automux_strip_audio": (bool,),
    "automux_retain_audio_languages": (list,),
    "automux_default_audio_language": (str,),
    "automux_strip_track_names": (bool,),
    "automux_no_fear": (bool,),
    "automux_exclude_commentary": (bool,),
    "automux_convert_containers": (bool,),
    "metadata_enabled": (bool,),
    "metadata_prefer_local": (bool,),
    "metadata_write_nfo": (bool,),
    "metadata_write_episode_nfo": (bool,),
    "metadata_write_poster": (bool,),
    "metadata_write_fanart": (bool,),
    "metadata_write_season_posters": (bool,),
    "metadata_write_episode_thumbs": (bool,),
    "metadata_write_clearlogo": (bool,),
    "metadata_plex_naming": (bool,),
    "metadata_embed_title": (bool,),
    "metadata_embed_cover": (bool,),
    "metadata_embed_tags": (bool,),
    "tv_metadata_source": (str,),
    "tv_fallback_enabled": (bool,),
    "tv_id_tag_routing_enabled": (bool,),
    "tv_provider_overrides": (dict,),
}

MAX_RECENT_FOLDERS = 10

DEFAULT_SETTINGS: dict[str, object] = {
    "match_language": "en-US",
    "hide_already_named": True,
    "view_mode": "normal",
    "show_companion_files": True,
    "show_discovery_info": False,
    "auto_accept_threshold": 0.55,
    "episode_auto_accept_threshold": 0.85,
    "tv_output_folder": "",
    "movie_output_folder": "",
    "show_confidence_bars": True,
    "window_geometry": None,
    "splitter_positions": None,
    "recent_tv_folders": [],
    "recent_movie_folders": [],
    "cache_max_size_bytes": 1024**3,  # 1 GiB (GUI-V4 R2, S2)
    "mkvmerge_path": "",
    "automux_merge_subs": False,
    "automux_merge_sub_languages": [],
    "automux_default_sub_language": "",
    "automux_untagged_sub_language": "",
    "automux_strip_subs": False,
    "automux_retain_sub_languages": [],
    "automux_strip_audio": False,
    "automux_retain_audio_languages": [],
    "automux_default_audio_language": "",
    "automux_strip_track_names": False,
    "automux_no_fear": False,
    "automux_exclude_commentary": False,
    "automux_convert_containers": True,
    "metadata_enabled": False,
    "metadata_prefer_local": False,
    "metadata_write_nfo": True,
    "metadata_write_episode_nfo": True,
    "metadata_write_poster": True,
    "metadata_write_fanart": True,
    "metadata_write_season_posters": True,
    "metadata_write_episode_thumbs": True,
    "metadata_write_clearlogo": True,
    "metadata_plex_naming": False,
    "metadata_embed_title": True,
    "metadata_embed_cover": True,
    "metadata_embed_tags": True,
    "tv_metadata_source": "tmdb",
    "tv_fallback_enabled": False,
    "tv_id_tag_routing_enabled": True,
    "tv_provider_overrides": {},
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
