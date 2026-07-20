"""ffprobe bitrate fallback: subprocess parsing, merge-by-order, and the
probe_file/cache integration that keeps cached and fresh results in sync.

Controller resolution (binding, amends the task-3 brief's sample code):
MediaTrack is @dataclass(frozen=True), so merge_ffprobe_bitrates cannot
mutate track.bitrate_bps in place. It instead rebuilds filled tracks via
dataclasses.replace() and writes the new list back to the (mutable)
ProbeResult.tracks -- see the frozen-dataclass test below.

merge_ffprobe_bitrates lives in _mkv_probe.py (not _ffprobe.py as the
brief's sample sketched): typing it against ProbeResult/MediaTrack would
require _ffprobe.py to import _mkv_probe, which -- combined with
_mkv_probe.probe_file's existing local import of _ffprobe -- closes a
module dependency cycle the repository's audit contract forbids
(tests/audit/test_repository_contracts.py). Colocating it with the
dataclasses it operates on avoids the import entirely.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from plex_renamer import _ffprobe, _mkv_probe
from plex_renamer._ffprobe import find_ffprobe, probe_audio_bitrates
from plex_renamer._mkv_probe import (
    MediaTrack,
    ProbeResult,
    clear_probe_cache,
    merge_ffprobe_bitrates,
    probe_file,
)
from plex_renamer.app.services.automux_service import resolve_ffprobe
from plex_renamer.app.services.settings_service import SettingsService


class _FakeCompleted:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.returncode = 0


class _MkvProc:
    returncode = 0
    stderr = ""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.stdout = json.dumps(payload)


def _runner_for(payload: str) -> Callable[..., _FakeCompleted]:
    def runner(*args: Any, **kwargs: Any) -> _FakeCompleted:
        return _FakeCompleted(payload)

    return runner


def _fake_which(result: str | None) -> Callable[[str], str | None]:
    """monkeypatch-able stand-in for shutil.which, fully typed so strict
    pyright doesn't flag an unannotated lambda parameter."""

    def _which(name: str) -> str | None:
        return result

    return _which


def _fake_mkvmerge_run(payload: dict[str, Any]) -> Callable[..., _MkvProc]:
    def _run(*args: Any, **kwargs: Any) -> _MkvProc:
        return _MkvProc(payload)

    return _run


def _fake_probe_audio_bitrates(
    bitrates: list[int], calls: list[Path] | None = None
) -> Callable[..., list[int]]:
    def _probe(ffprobe: Path, path: Path, **kwargs: Any) -> list[int]:
        if calls is not None:
            calls.append(path)
        return bitrates

    return _probe


# ── probe_audio_bitrates ───────────────────────────────────────────────


def test_bit_rate_field_wins() -> None:
    payload = '{"streams": [{"index": 1, "bit_rate": "640000"}]}'
    assert probe_audio_bitrates(Path("ffprobe"), Path("x.mp4"), runner=_runner_for(payload)) == [
        640000
    ]


def test_bps_tag_fallback() -> None:
    payload = '{"streams": [{"index": 1, "tags": {"BPS-eng": "1509000"}}]}'
    assert probe_audio_bitrates(Path("ffprobe"), Path("x.mkv"), runner=_runner_for(payload)) == [
        1509000
    ]


def test_bps_tag_without_eng_suffix() -> None:
    payload = '{"streams": [{"index": 1, "tags": {"BPS": "256000"}}]}'
    assert probe_audio_bitrates(Path("ffprobe"), Path("x.mkv"), runner=_runner_for(payload)) == [
        256000
    ]


def test_unknown_stream_is_zero_and_failure_is_empty() -> None:
    assert probe_audio_bitrates(
        Path("ffprobe"), Path("x.mp4"), runner=_runner_for('{"streams": [{}]}')
    ) == [0]
    assert (
        probe_audio_bitrates(Path("ffprobe"), Path("x.mp4"), runner=_runner_for("not json")) == []
    )


def test_multiple_streams_preserve_order() -> None:
    payload = json.dumps(
        {
            "streams": [
                {"index": 1, "bit_rate": "128000"},
                {"index": 2},
                {"index": 3, "tags": {"BPS-eng": "384000"}},
            ]
        }
    )
    assert probe_audio_bitrates(Path("ffprobe"), Path("x.mkv"), runner=_runner_for(payload)) == [
        128000,
        0,
        384000,
    ]


# ── find_ffprobe ─────────────────────────────────────────────────────────


def test_find_ffprobe_explicit_file(tmp_path: Path) -> None:
    exe = tmp_path / "ffprobe.exe"
    exe.write_bytes(b"")
    assert find_ffprobe(str(exe)) == exe


def test_find_ffprobe_explicit_missing_returns_none(tmp_path: Path) -> None:
    assert find_ffprobe(str(tmp_path / "missing.exe")) is None


def test_find_ffprobe_falls_back_to_which(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    found = tmp_path / "ffprobe"
    monkeypatch.setattr(_ffprobe.shutil, "which", _fake_which(str(found)))
    assert find_ffprobe() == found


def test_find_ffprobe_none_when_which_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ffprobe.shutil, "which", _fake_which(None))
    assert find_ffprobe() is None


# ── merge_ffprobe_bitrates (controller-resolution seam over ProbeResult) ──


def _track(track_type: str, *, bitrate_bps: int = 0, track_id: int = 0) -> MediaTrack:
    return MediaTrack(
        track_id=track_id,
        track_type=track_type,
        codec="aac" if track_type == "audio" else "h264",
        language="und",
        name="",
        is_default=False,
        is_forced=False,
        bitrate_bps=bitrate_bps,
    )


def test_merge_fills_zero_bitrate_audio_tracks_in_order() -> None:
    result = ProbeResult(
        path="x.mkv",
        ok=True,
        tracks=[
            _track("video", track_id=0),
            _track("audio", track_id=1, bitrate_bps=0),
            _track("subtitles", track_id=2),
            _track("audio", track_id=3, bitrate_bps=0),
        ],
    )
    merge_ffprobe_bitrates(result, [128000, 256000])
    assert [t.bitrate_bps for t in result.tracks] == [0, 128000, 0, 256000]


def test_merge_never_overwrites_a_known_bitrate() -> None:
    result = ProbeResult(
        path="x.mkv", ok=True, tracks=[_track("audio", track_id=1, bitrate_bps=768000)]
    )
    merge_ffprobe_bitrates(result, [999999])
    assert result.tracks[0].bitrate_bps == 768000


def test_merge_leaves_zero_when_ffprobe_also_unknown() -> None:
    result = ProbeResult(path="x.mkv", ok=True, tracks=[_track("audio", track_id=1)])
    merge_ffprobe_bitrates(result, [0])
    assert result.tracks[0].bitrate_bps == 0


def test_merge_stops_at_shorter_bitrates_list() -> None:
    result = ProbeResult(
        path="x.mkv",
        ok=True,
        tracks=[_track("audio", track_id=1), _track("audio", track_id=2)],
    )
    merge_ffprobe_bitrates(result, [128000])
    assert [t.bitrate_bps for t in result.tracks] == [128000, 0]


def test_merge_rebuilds_via_dataclasses_replace_frozen_track_untouched() -> None:
    """MediaTrack is frozen -- the merge must rebuild filled tracks with
    dataclasses.replace(), not mutate them in place (controller
    resolution)."""
    track = _track("audio", track_id=1)
    result = ProbeResult(path="x.mkv", ok=True, tracks=[track])
    merge_ffprobe_bitrates(result, [128000])
    assert track.bitrate_bps == 0  # original object is untouched (frozen)
    assert result.tracks[0].bitrate_bps == 128000
    assert result.tracks[0] is not track


# ── probe_file enrichment + cache-before-store ordering ──────────────────

IDENTIFY_PAYLOAD_ONE_AUDIO_UNKNOWN: dict[str, Any] = {
    "container": {"recognized": True, "supported": True, "type": "Matroska"},
    "tracks": [
        {"id": 0, "type": "video", "codec": "HEVC", "properties": {"language": "und"}},
        {
            "id": 1,
            "type": "audio",
            "codec": "AAC",
            "properties": {"language": "eng"},  # no tag_bps -> bitrate_bps 0
        },
    ],
}


def test_probe_file_enriches_unknown_audio_bitrate_via_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_probe_cache()
    video = tmp_path / "a.mp4"
    video.write_bytes(b"0" * 32)
    monkeypatch.setattr(
        _mkv_probe.subprocess, "run", _fake_mkvmerge_run(IDENTIFY_PAYLOAD_ONE_AUDIO_UNKNOWN)
    )
    monkeypatch.setattr(_ffprobe, "probe_audio_bitrates", _fake_probe_audio_bitrates([640000]))

    result = probe_file(Path("mkvmerge"), video, ffprobe_path=Path("ffprobe"))

    assert result.ok
    assert result.audio_tracks[0].bitrate_bps == 640000


def test_probe_file_skips_ffprobe_when_no_path_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_probe_cache()
    video = tmp_path / "b.mp4"
    video.write_bytes(b"0" * 32)
    monkeypatch.setattr(
        _mkv_probe.subprocess, "run", _fake_mkvmerge_run(IDENTIFY_PAYLOAD_ONE_AUDIO_UNKNOWN)
    )
    calls: list[Path] = []
    monkeypatch.setattr(
        _ffprobe, "probe_audio_bitrates", _fake_probe_audio_bitrates([640000], calls)
    )

    result = probe_file(Path("mkvmerge"), video)

    assert result.audio_tracks[0].bitrate_bps == 0
    assert calls == []  # ffprobe never invoked


def test_probe_file_skips_ffprobe_when_all_audio_bitrates_already_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_probe_cache()
    video = tmp_path / "c.mkv"
    video.write_bytes(b"0" * 32)
    payload: dict[str, Any] = {
        "container": {"recognized": True, "supported": True, "type": "Matroska"},
        "tracks": [
            {
                "id": 0,
                "type": "audio",
                "codec": "AC-3",
                "properties": {"language": "eng", "tag_bps": "768000"},
            },
        ],
    }
    monkeypatch.setattr(_mkv_probe.subprocess, "run", _fake_mkvmerge_run(payload))
    calls: list[Path] = []
    monkeypatch.setattr(_ffprobe, "probe_audio_bitrates", _fake_probe_audio_bitrates([1], calls))

    result = probe_file(Path("mkvmerge"), video, ffprobe_path=Path("ffprobe"))

    assert result.audio_tracks[0].bitrate_bps == 768000  # untouched
    assert calls == []  # already known -> ffprobe skipped


def test_probe_file_cache_stores_the_enriched_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAUTION in the brief: the cache key (path, size, mtime) doesn't
    include ffprobe_path, so enrichment must happen before the result is
    cached -- a later cache hit (even a differently-parameterized call)
    must see the already-enriched value, not a fresh un-enriched parse."""
    clear_probe_cache()
    video = tmp_path / "d.mp4"
    video.write_bytes(b"0" * 32)
    monkeypatch.setattr(
        _mkv_probe.subprocess, "run", _fake_mkvmerge_run(IDENTIFY_PAYLOAD_ONE_AUDIO_UNKNOWN)
    )
    monkeypatch.setattr(_ffprobe, "probe_audio_bitrates", _fake_probe_audio_bitrates([640000]))

    first = probe_file(Path("mkvmerge"), video, ffprobe_path=Path("ffprobe"))
    assert first.audio_tracks[0].bitrate_bps == 640000

    second = probe_file(Path("mkvmerge"), video)  # no ffprobe_path this time
    assert second.audio_tracks[0].bitrate_bps == 640000
    assert second is first  # served straight from cache


# ── resolve_ffprobe (automux_service) ─────────────────────────────────────


def test_resolve_ffprobe_none_svc() -> None:
    assert resolve_ffprobe(None) is None


def test_resolve_ffprobe_uses_configured_path(tmp_path: Path) -> None:
    svc = SettingsService(tmp_path / "settings.json")
    exe = tmp_path / "ffprobe.exe"
    exe.write_bytes(b"")
    svc.ffprobe_path = str(exe)
    assert resolve_ffprobe(svc) == exe


def test_resolve_ffprobe_none_when_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = SettingsService(tmp_path / "settings.json")
    monkeypatch.setattr(_ffprobe.shutil, "which", _fake_which(None))
    assert resolve_ffprobe(svc) is None
