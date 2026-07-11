"""Settings keys for the metadata/artwork export feature."""

from plex_renamer.app.services._settings_schema import (
    DEFAULT_SETTINGS,
    SETTINGS_SCHEMA,
    build_valid_settings_data,
)

METADATA_KEYS = {
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
}


def test_metadata_keys_in_schema_with_defaults():
    for key, default in METADATA_KEYS.items():
        assert SETTINGS_SCHEMA[key] == (bool,)
        assert DEFAULT_SETTINGS[key] is default


def test_bad_type_resets_to_default():
    data = build_valid_settings_data({"metadata_enabled": "yes"})
    assert data["metadata_enabled"] is False


def test_stored_value_round_trips():
    data = build_valid_settings_data({"metadata_enabled": True,
                                      "metadata_plex_naming": True})
    assert data["metadata_enabled"] is True
    assert data["metadata_plex_naming"] is True
