"""AutoMux settings keys round-trip through SettingsService."""

from plex_renamer.app.services.settings_service import SettingsService


def _svc(tmp_path):
    return SettingsService(tmp_path / "settings.json")


def test_automux_defaults(tmp_path):
    svc = _svc(tmp_path)
    assert svc.mkvmerge_path == ""
    assert svc.automux_merge_subs is False
    assert svc.automux_merge_sub_languages == []
    assert svc.automux_default_sub_language == ""
    assert svc.automux_untagged_sub_language == ""
    assert svc.automux_strip_subs is False
    assert svc.automux_retain_sub_languages == []
    assert svc.automux_strip_audio is False
    assert svc.automux_retain_audio_languages == []
    assert svc.automux_default_audio_language == ""
    assert svc.automux_strip_track_names is False
    assert svc.automux_no_fear is False
    assert svc.automux_exclude_commentary is False
    assert svc.automux_any_enabled is False


def test_automux_settings_persist(tmp_path):
    svc = _svc(tmp_path)
    svc.automux_merge_subs = True
    svc.automux_merge_sub_languages = ["eng", "jpn"]
    svc.mkvmerge_path = "C:/tools/mkvmerge.exe"
    reloaded = _svc(tmp_path)
    assert reloaded.automux_merge_subs is True
    assert reloaded.automux_merge_sub_languages == ["eng", "jpn"]
    assert reloaded.mkvmerge_path == "C:/tools/mkvmerge.exe"
    assert reloaded.automux_any_enabled is True


def test_bad_type_resets_to_default(tmp_path):
    svc = _svc(tmp_path)
    svc.set("automux_merge_sub_languages", ["eng"])
    # Corrupt the stored value type, reload — schema validation resets it.
    import json

    path = tmp_path / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["automux_merge_sub_languages"] = "eng"
    path.write_text(json.dumps(data), encoding="utf-8")
    reloaded = _svc(tmp_path)
    assert reloaded.automux_merge_sub_languages == []


def test_exclude_commentary_persists_and_maps(tmp_path):
    from plex_renamer.app.services.automux_service import mux_settings_from_service

    svc = _svc(tmp_path)
    svc.automux_exclude_commentary = True
    reloaded = _svc(tmp_path)
    assert reloaded.automux_exclude_commentary is True
    assert mux_settings_from_service(reloaded).exclude_commentary is True


def test_dedupe_settings_defaults(tmp_path):
    svc = _svc(tmp_path)
    assert svc.automux_dedupe_audio is False
    assert svc.automux_dedupe_keep_per_layout is True
    assert svc.automux_lossless_policy == "quality"
    assert svc.automux_tie_prefer_smaller is True
    assert svc.automux_tie_tolerance_pct == 15
    assert svc.automux_transparency_kbps_per_channel == 160
    assert svc.automux_codec_weights == {}


def test_dedupe_settings_persist(tmp_path):
    svc = _svc(tmp_path)
    svc.automux_dedupe_audio = True
    svc.automux_dedupe_keep_per_layout = False
    svc.automux_lossless_policy = "space"
    svc.automux_tie_prefer_smaller = False
    svc.automux_tie_tolerance_pct = 25
    svc.automux_transparency_kbps_per_channel = 192
    svc.automux_codec_weights = {"opus": 1.8}
    reloaded = _svc(tmp_path)
    assert reloaded.automux_dedupe_audio is True
    assert reloaded.automux_dedupe_keep_per_layout is False
    assert reloaded.automux_lossless_policy == "space"
    assert reloaded.automux_tie_prefer_smaller is False
    assert reloaded.automux_tie_tolerance_pct == 25
    assert reloaded.automux_transparency_kbps_per_channel == 192
    assert reloaded.automux_codec_weights == {"opus": 1.8}


def test_dedupe_settings_reach_mux_settings(tmp_path) -> None:
    from plex_renamer.app.services.automux_service import mux_settings_from_service

    settings_service = _svc(tmp_path)
    settings_service.automux_dedupe_audio = True
    settings_service.automux_lossless_policy = "space"
    settings_service.automux_codec_weights = {"opus": 1.8}
    mux = mux_settings_from_service(settings_service)
    assert mux.dedupe_audio is True
    assert mux.lossless_policy == "space"
    assert mux.codec_weights == {"opus": 1.8}
    assert mux.dedupe_keep_per_layout is True
    assert mux.tie_prefer_smaller is True
    assert mux.tie_tolerance_pct == 15
    assert mux.transparency_kbps_per_channel == 160
