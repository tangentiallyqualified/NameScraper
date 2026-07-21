"""Append-compatibility gate: identical track layout across parts."""

from __future__ import annotations

from plex_renamer._mkv_probe import MediaTrack, ProbeResult
from plex_renamer.engine._merge_gate import check_append_compatibility


def _video(codec: str = "AVC/H.264", width: int = 1920, height: int = 1080) -> MediaTrack:
    return MediaTrack(
        track_id=0,
        track_type="video",
        codec=codec,
        language="und",
        name="",
        is_default=True,
        is_forced=False,
        width=width,
        height=height,
    )


def _audio(
    codec: str = "AAC", channels: int = 2, sample_rate: int = 48000, track_id: int = 1
) -> MediaTrack:
    return MediaTrack(
        track_id=track_id,
        track_type="audio",
        codec=codec,
        language="eng",
        name="",
        is_default=True,
        is_forced=False,
        channels=channels,
        sample_rate=sample_rate,
    )


def _probe(tracks: list[MediaTrack]) -> ProbeResult:
    return ProbeResult(path="x.mkv", ok=True, tracks=tracks)


def test_identical_layouts_pass() -> None:
    parts = [_probe([_video(), _audio()]) for _ in range(3)]
    assert check_append_compatibility(parts) is None


def test_video_codec_mismatch_named() -> None:
    reason = check_append_compatibility(
        [_probe([_video("AVC/H.264"), _audio()]), _probe([_video("HEVC"), _audio()])]
    )
    assert reason is not None and "video codec" in reason
    assert "AVC/H.264" in reason and "HEVC" in reason


def test_resolution_mismatch_named() -> None:
    reason = check_append_compatibility(
        [_probe([_video(width=1920)]), _probe([_video(width=1280, height=720)])]
    )
    assert reason is not None and "resolution" in reason


def test_audio_param_mismatches_named() -> None:
    assert "sample rate" in check_append_compatibility(
        [_probe([_audio(sample_rate=48000)]), _probe([_audio(sample_rate=44100)])]
    )
    assert "channel" in check_append_compatibility(
        [_probe([_audio(channels=2)]), _probe([_audio(channels=6)])]
    )


def test_track_count_and_order_mismatch() -> None:
    assert "track count" in check_append_compatibility(
        [_probe([_video(), _audio()]), _probe([_video()])]
    )
    assert (
        check_append_compatibility([_probe([_video(), _audio()]), _probe([_audio(), _video()])])
        is not None
    )


def test_failed_probe_is_a_gate_failure() -> None:
    bad = ProbeResult(path="x.mkv", ok=False, error="boom")
    reason = check_append_compatibility([_probe([_video()]), bad])
    assert reason is not None


def test_unknown_params_do_not_block() -> None:
    """0 = unknown never fails the gate on its own (probe couldn't say)."""
    parts = [
        _probe([_video(width=0, height=0), _audio(sample_rate=0)]),
        _probe([_video(), _audio()]),
    ]
    assert check_append_compatibility(parts) is None
