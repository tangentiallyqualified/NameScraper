"""Merge planning: probing all parts, gating, offsets, toggle independence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plex_renamer._mkv_probe import MediaTrack, ProbeResult
from plex_renamer.app.services.automux_service import ensure_state_plans
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.engine.models import PreviewItem, ScanState


def _track(track_type: str, track_id: int) -> MediaTrack:
    return MediaTrack(
        track_id=track_id,
        track_type=track_type,
        codec="AVC" if track_type == "video" else "AAC",
        language="und" if track_type == "video" else "eng",
        name="",
        is_default=True,
        is_forced=False,
        channels=2 if track_type == "audio" else 0,
        sample_rate=48000 if track_type == "audio" else 0,
    )


def _probe_for(path: Path, *, duration_ms: int = 600_000, codec: str = "AVC") -> ProbeResult:
    tracks = [_track("video", 0), _track("audio", 1)]
    if codec != "AVC":
        tracks[0] = MediaTrack(
            track_id=0,
            track_type="video",
            codec=codec,
            language="und",
            name="",
            is_default=True,
            is_forced=False,
        )
    return ProbeResult(
        path=str(path),
        ok=True,
        tracks=tracks,
        container_type="Matroska",
        duration_ms=duration_ms,
    )


def _merge_state(tmp_path: Path) -> ScanState:
    parts: list[Path] = []
    for index in (1, 2, 3):
        part = tmp_path / f"Show S01E05 ({index}).mkv"
        part.write_bytes(b"0")
        parts.append(part)
    item = PreviewItem(
        original=parts[0],
        new_name="Show - S01E05 - Five.mkv",
        target_dir=tmp_path / "Season 01",
        season=1,
        episodes=[5],
        status="OK",
        merge_part_paths=list(parts),
        merge_part_file_ids=[0, 1, 2],
    )
    state = ScanState(folder=tmp_path, media_info={})
    state.preview_items = [item]
    return state


def _svc(tmp_path: Path, *, automux_on: bool) -> SettingsService:
    svc = SettingsService(tmp_path / "settings.json")
    exe = tmp_path / "mkvmerge.exe"
    exe.write_bytes(b"")
    svc.mkvmerge_path = str(exe)
    if automux_on:
        svc.automux_merge_subs = True
        svc.automux_merge_sub_languages = ["eng"]
    return svc


def test_merge_plan_built_with_automux_off(tmp_path: Path) -> None:
    """Merging is toggle-independent: plain append, all tracks kept."""
    state = _merge_state(tmp_path)
    calls: list[Path] = []

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        calls.append(path)
        return _probe_for(path)

    ensure_state_plans(state, _svc(tmp_path, automux_on=False), tmp_path, prober=prober)
    plan: dict[str, Any] = state.mux_plans[0]
    assert [Path(p).name for p in plan["append_sources"]] == [
        "Show S01E05 (2).mkv",
        "Show S01E05 (3).mkv",
    ]
    assert len(calls) == 3  # every part probed
    assert state.merge_gate_errors == {}
    assert all(d["keep"] for d in plan["track_decisions"])  # nothing stripped


def test_gate_failure_blocks_and_names_reason(tmp_path: Path) -> None:
    state = _merge_state(tmp_path)

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        codec = "HEVC" if "(3)" in path.name else "AVC"
        return _probe_for(path, codec=codec)

    ensure_state_plans(state, _svc(tmp_path, automux_on=False), tmp_path, prober=prober)
    assert 0 not in state.mux_plans
    assert "codec mismatch" in state.merge_gate_errors[0]


def test_part_sub_offsets_are_cumulative_durations(tmp_path: Path) -> None:
    state = _merge_state(tmp_path)
    # External sub next to part 2: offset must equal part 1's duration.
    (tmp_path / "Show S01E05 (2).eng.srt").write_text("", encoding="utf-8")
    durations = {"(1)": 600_000, "(2)": 540_000, "(3)": 480_000}

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        for token, ms in durations.items():
            if token in path.name:
                return _probe_for(path, duration_ms=ms)
        return _probe_for(path)

    ensure_state_plans(state, _svc(tmp_path, automux_on=True), tmp_path, prober=prober)
    plan: dict[str, Any] = state.mux_plans[0]
    merges: list[Any] = [m for m in plan["subtitle_merges"] if m["action"] == "merge"]
    offsets = {Path(m["source_relative"]).name: m["sync_offset_ms"] for m in merges}
    assert offsets["Show S01E05 (2).eng.srt"] == 600_000


def test_unknown_duration_skips_later_part_sub_with_warning(tmp_path: Path) -> None:
    state = _merge_state(tmp_path)
    (tmp_path / "Show S01E05 (2).eng.srt").write_text("", encoding="utf-8")

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        return _probe_for(path, duration_ms=0)  # duration unknown

    ensure_state_plans(state, _svc(tmp_path, automux_on=True), tmp_path, prober=prober)
    plan: dict[str, Any] = state.mux_plans[0]
    assert all(
        m["action"] != "merge" or "(2)" not in m["source_relative"] for m in plan["subtitle_merges"]
    )
    assert any("no reliable duration for offset" in w for w in plan["warnings"])


def test_merge_subs_disabled_leaves_later_part_sub_with_distinct_warning(tmp_path: Path) -> None:
    """Merging disabled and unknown duration must produce distinguishable
    warnings (spec: don't conflate the two causes)."""
    state = _merge_state(tmp_path)
    (tmp_path / "Show S01E05 (2).eng.srt").write_text("", encoding="utf-8")

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        return _probe_for(path, duration_ms=600_000)  # duration known

    # automux_on=False -> settings is a bare MuxSettings() with merge_subs off.
    ensure_state_plans(state, _svc(tmp_path, automux_on=False), tmp_path, prober=prober)
    plan: dict[str, Any] = state.mux_plans[0]
    assert all(
        m["action"] != "merge" or "(2)" not in m["source_relative"] for m in plan["subtitle_merges"]
    )
    assert any("merging disabled" in w for w in plan["warnings"])
    assert not any("no reliable duration for offset" in w for w in plan["warnings"])


def test_normal_rows_unaffected_when_automux_off(tmp_path: Path) -> None:
    state = ScanState(folder=tmp_path, media_info={})
    video = tmp_path / "Show S01E01.mkv"
    video.write_bytes(b"0")
    state.preview_items = [
        PreviewItem(
            original=video,
            new_name="Show - S01E01.mkv",
            target_dir=tmp_path,
            season=1,
            episodes=[1],
            status="OK",
        )
    ]
    ensure_state_plans(
        state,
        _svc(tmp_path, automux_on=False),
        tmp_path,
        prober=lambda *a, **k: _probe_for(video),
    )
    assert state.mux_plans == {}


def test_mixed_rows_automux_off_plans_only_the_merge_row(tmp_path: Path) -> None:
    """A merge row must not drag normal rows into planning when AutoMux is
    off (regression: has_merge_rows previously gated the whole state, not
    the per-row decision)."""
    merge_state = _merge_state(tmp_path)
    merge_item = merge_state.preview_items[0]

    normal_video = tmp_path / "Show S01E01.mkv"
    normal_video.write_bytes(b"0")
    normal_item = PreviewItem(
        original=normal_video,
        new_name="Show - S01E01.mkv",
        target_dir=tmp_path,
        season=1,
        episodes=[1],
        status="OK",
    )

    state = ScanState(folder=tmp_path, media_info={})
    state.preview_items = [merge_item, normal_item]

    calls: list[Path] = []

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        calls.append(path)
        return _probe_for(path)

    ensure_state_plans(state, _svc(tmp_path, automux_on=False), tmp_path, prober=prober)

    assert 0 in state.mux_plans  # merge row planned
    assert 1 not in state.mux_plans  # normal row left alone
    assert sorted(p.name for p in calls) == [
        "Show S01E05 (1).mkv",
        "Show S01E05 (2).mkv",
        "Show S01E05 (3).mkv",
    ]  # only the merge row's parts were probed -- never the normal row


def test_user_modified_merge_plan_without_append_is_rebuilt(tmp_path: Path) -> None:
    """Final-review I1: a merge row's cached plan can be a single-file plan
    (no append_sources) that the GUI's per-file probe path cached before
    the append was ever planned; if a track edit then set user_modified,
    the append is not user-editable, so the stale user_modified skip must
    not lock it in -- ensure_state_plans has to rebuild the real append
    plan regardless."""
    state = _merge_state(tmp_path)
    # Simulate exactly that: a single-file plan (built from item.original,
    # i.e. part 1) with no append_sources, flagged user_modified by a
    # track edit made before the row was ever grouped/replanned.
    state.mux_plans[0] = {
        "output_name": "Show - S01E05 - Five.mkv",
        "track_decisions": [{"track_id": 0, "keep": False}],
        "subtitle_merges": [],
        "append_sources": [],
        "strip_track_names": False,
        "no_fear": False,
        "mkvmerge_path": "",
        "warnings": [],
        "container_conversion": False,
        "user_modified": True,
    }

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        return _probe_for(path)

    ensure_state_plans(state, _svc(tmp_path, automux_on=False), tmp_path, prober=prober)

    plan: dict[str, Any] = state.mux_plans[0]
    assert plan["append_sources"] == [
        "Show S01E05 (2).mkv",
        "Show S01E05 (3).mkv",
    ]


def test_user_modified_merge_plan_with_append_is_left_alone(tmp_path: Path) -> None:
    """A merge row's user_modified plan that ALREADY carries append_sources
    (a legitimate track edit layered on top of a real append plan) must
    still be honored as user_modified -- the rebuild guard only applies
    when the append itself is missing."""
    state = _merge_state(tmp_path)
    state.mux_plans[0] = {
        "output_name": "Show - S01E05 - Five.mkv",
        "track_decisions": [{"track_id": 0, "keep": False}],
        "subtitle_merges": [],
        "append_sources": ["Show S01E05 (2).mkv", "Show S01E05 (3).mkv"],
        "strip_track_names": False,
        "no_fear": False,
        "mkvmerge_path": "",
        "warnings": [],
        "container_conversion": False,
        "user_modified": True,
    }
    calls: list[Path] = []

    def prober(mkvmerge: Any, path: Path, **kwargs: Any) -> ProbeResult:
        calls.append(path)
        return _probe_for(path)

    ensure_state_plans(state, _svc(tmp_path, automux_on=False), tmp_path, prober=prober)

    assert calls == []  # untouched: no re-probe, the cached plan is kept as-is
    assert state.mux_plans[0]["track_decisions"] == [{"track_id": 0, "keep": False}]
