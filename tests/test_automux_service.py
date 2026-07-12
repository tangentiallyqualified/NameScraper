"""Session AutoMux planning: settings snapshot, probing, plan attachment."""
from pathlib import Path

from plex_renamer._mkv_probe import MediaTrack, ProbeResult
from plex_renamer.app.services import automux_service as svc_mod
from plex_renamer.app.services.automux_service import (
    automux_active,
    companion_subs_for_item,
    effective_mux_plans,
    ensure_state_plans,
    file_mux_active,
    mux_settings_from_service,
    plan_has_actions,
    state_has_mux_actions,
    state_mux_eligible,
)
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.engine.models import CompanionFile, PreviewItem, ScanState


def _settings(tmp_path, *, merge=True, mkvmerge=True):
    svc = SettingsService(tmp_path / "settings.json")
    svc.automux_merge_subs = merge
    svc.automux_merge_sub_languages = ["eng"]
    if mkvmerge:
        exe = tmp_path / "mkvmerge.exe"
        exe.write_bytes(b"")
        svc.mkvmerge_path = str(exe)
    return svc


def _item(tmp_path, *, companions=()):
    return PreviewItem(
        original=tmp_path / "lib" / "Show" / "a.mkv",
        new_name="Show - S01E01 - Pilot.mkv",
        target_dir=tmp_path / "out" / "Show (2020)" / "Season 01",
        season=1, episodes=[1], status="OK", media_type="tv",
        companions=list(companions),
    )


def _state(tmp_path, item):
    return ScanState(
        folder=tmp_path / "lib" / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[item],
        scanned=True,
    )


def _probe_ok():
    return ProbeResult(path="a.mkv", ok=True, tracks=[
        MediaTrack(track_id=0, track_type="video", codec="h264",
                   language="und", name="", is_default=True, is_forced=False),
        MediaTrack(track_id=1, track_type="audio", codec="aac",
                   language="eng", name="", is_default=True, is_forced=False),
    ])


def test_mux_settings_snapshot(tmp_path):
    svc = _settings(tmp_path)
    settings = mux_settings_from_service(svc)
    assert settings.merge_subs is True
    assert settings.merge_sub_languages == ["eng"]
    assert settings.no_fear is False


def test_automux_active_requires_toggle_and_binary(tmp_path):
    assert automux_active(None) is False
    assert automux_active(_settings(tmp_path, merge=False)) is False
    (tmp_path / "nb").mkdir()
    no_bin = _settings(tmp_path / "nb", mkvmerge=False)
    no_bin.mkvmerge_path = str(tmp_path / "nb" / "missing.exe")
    assert automux_active(no_bin) is False
    assert automux_active(_settings(tmp_path)) is True


def test_companion_subs_derive_raw_tags(tmp_path):
    comps = [
        CompanionFile(original=tmp_path / "lib" / "Show" / "a.eng.srt",
                      new_name="Show - S01E01 - Pilot.eng.srt",
                      file_type="subtitle"),
        CompanionFile(original=tmp_path / "lib" / "Show" / "a.srt",
                      new_name="Show - S01E01 - Pilot.srt",
                      file_type="subtitle"),
    ]
    item = _item(tmp_path, companions=comps)
    pairs = companion_subs_for_item(item, tmp_path / "lib")
    assert pairs == [
        (str(Path("Show/a.eng.srt")), ".eng"),
        (str(Path("Show/a.srt")), ""),
    ]


def test_ensure_state_plans_attaches_plan(tmp_path, monkeypatch):
    svc = _settings(tmp_path)
    comp = CompanionFile(original=tmp_path / "lib" / "Show" / "a.eng.srt",
                         new_name="Show - S01E01 - Pilot.eng.srt",
                         file_type="subtitle")
    state = _state(tmp_path, _item(tmp_path, companions=[comp]))
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path: _probe_ok())
    ensure_state_plans(state, svc, tmp_path / "lib")
    assert 0 in state.mux_plans
    assert plan_has_actions(state.mux_plans[0])
    assert state_has_mux_actions(state)
    assert effective_mux_plans(state) == state.mux_plans


def test_ensure_skips_user_modified_and_disabled(tmp_path, monkeypatch):
    svc = _settings(tmp_path)
    comp = CompanionFile(original=tmp_path / "lib" / "Show" / "a.eng.srt",
                         new_name="Show - S01E01 - Pilot.eng.srt",
                         file_type="subtitle")
    state = _state(tmp_path, _item(tmp_path, companions=[comp]))
    sentinel = {"output_name": "X.mkv", "track_decisions": [],
                "subtitle_merges": [], "strip_track_names": False,
                "no_fear": False, "mkvmerge_path": "", "warnings": [],
                "user_modified": True}
    state.mux_plans[0] = dict(sentinel)
    calls = []
    monkeypatch.setattr(
        svc_mod, "probe_file",
        lambda mkv, path: calls.append(path) or _probe_ok())
    ensure_state_plans(state, svc, tmp_path / "lib")
    assert state.mux_plans[0] == sentinel        # untouched (spec §5.1)
    assert calls == []                           # not even probed

    state.automux_disabled = True
    assert effective_mux_plans(state) is None
    assert state_has_mux_actions(state) is False


def test_probe_failure_records_error_and_no_plan(tmp_path, monkeypatch):
    svc = _settings(tmp_path)
    comp = CompanionFile(original=tmp_path / "lib" / "Show" / "a.eng.srt",
                         new_name="Show - S01E01 - Pilot.eng.srt",
                         file_type="subtitle")
    state = _state(tmp_path, _item(tmp_path, companions=[comp]))
    monkeypatch.setattr(
        svc_mod, "probe_file",
        lambda mkv, path: ProbeResult(path=str(path), ok=False, error="boom"))
    ensure_state_plans(state, svc, tmp_path / "lib")
    assert state.mux_plans == {}
    assert state.mux_probe_errors[0] == "boom"


def test_no_action_plan_not_stored(tmp_path, monkeypatch):
    svc = _settings(tmp_path)
    state = _state(tmp_path, _item(tmp_path))     # no companions → no merge
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path: _probe_ok())
    ensure_state_plans(state, svc, tmp_path / "lib")
    assert state.mux_plans == {}
    assert effective_mux_plans(state) is None


def test_reset_gui_state_clears_automux_session(tmp_path):
    state = _state(tmp_path, _item(tmp_path))
    state.automux_disabled = True
    state.mux_plans[0] = {"user_modified": False}
    state.mux_probe_errors[0] = "x"
    state.reset_gui_state()
    assert state.automux_disabled is False
    assert state.mux_plans == {}
    assert state.mux_probe_errors == {}


def test_mux_opt_outs_excluded_from_state_has_mux_actions(tmp_path):
    action_plan = {"track_decisions": [{"track_id": 1, "keep": False}],
                   "subtitle_merges": []}
    state = _state(tmp_path, _item(tmp_path))
    state.mux_plans[0] = action_plan
    assert state_has_mux_actions(state) is True
    state.mux_opt_outs.add(0)
    assert state_has_mux_actions(state) is False
    # show-level eligibility ignores opt-outs (button stays reachable)
    assert state_mux_eligible(state) is True


def test_effective_mux_plans_drops_opted_out_indices(tmp_path):
    action_plan = {"track_decisions": [{"track_id": 1, "keep": False}],
                   "subtitle_merges": []}
    state = _state(tmp_path, _item(tmp_path))
    state.mux_plans[0] = action_plan
    state.mux_plans[1] = dict(action_plan)
    state.mux_opt_outs.add(0)
    plans = effective_mux_plans(state)
    assert set(plans) == {1}


def test_file_mux_active(tmp_path):
    action_plan = {"track_decisions": [{"track_id": 1, "keep": False}],
                   "subtitle_merges": []}
    state = _state(tmp_path, _item(tmp_path))
    state.mux_plans[0] = action_plan
    assert file_mux_active(state, 0) is True
    assert file_mux_active(state, 1) is False   # no plan
    state.mux_opt_outs.add(0)
    assert file_mux_active(state, 0) is False
    state.mux_opt_outs.discard(0)
    state.automux_disabled = True
    assert file_mux_active(state, 0) is False


def test_session_reset_clears_opt_outs(tmp_path):
    state = _state(tmp_path, _item(tmp_path))
    state.mux_opt_outs.add(3)
    state.reset_gui_state()
    assert state.mux_opt_outs == set()
