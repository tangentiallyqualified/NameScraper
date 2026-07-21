"""parse_identify_json extraction of gate/duration fields from mkvmerge -J."""

from __future__ import annotations

from typing import Any

from plex_renamer._mkv_probe import parse_identify_json

_PAYLOAD: dict[str, Any] = {
    "container": {
        "recognized": True,
        "supported": True,
        "type": "Matroska",
        "properties": {"duration": 1_500_000_000_000},  # 1500 s in ns
    },
    "tracks": [
        {
            "id": 0,
            "type": "video",
            "codec": "AVC/H.264/MPEG-4p10",
            "properties": {"language": "und", "pixel_dimensions": "1920x1080"},
        },
        {
            "id": 1,
            "type": "audio",
            "codec": "AAC",
            "properties": {
                "language": "eng",
                "audio_channels": 2,
                "audio_sampling_frequency": 48000,
            },
        },
    ],
}


def test_video_dimensions_parsed() -> None:
    result = parse_identify_json("x.mkv", _PAYLOAD)
    video = result.video_tracks[0]
    assert (video.width, video.height) == (1920, 1080)


def test_audio_sample_rate_parsed() -> None:
    result = parse_identify_json("x.mkv", _PAYLOAD)
    assert result.audio_tracks[0].sample_rate == 48000


def test_container_duration_ns_to_ms() -> None:
    result = parse_identify_json("x.mkv", _PAYLOAD)
    assert result.duration_ms == 1_500_000


def test_missing_fields_default_to_zero() -> None:
    payload: dict[str, Any] = {
        "container": {"recognized": True, "supported": True, "type": "Matroska"},
        "tracks": [
            {"id": 0, "type": "video", "codec": "HEVC", "properties": {}},
            {"id": 1, "type": "audio", "codec": "AC-3", "properties": {}},
        ],
    }
    result = parse_identify_json("x.mkv", payload)
    assert (result.video_tracks[0].width, result.video_tracks[0].height) == (0, 0)
    assert result.audio_tracks[0].sample_rate == 0
    assert result.duration_ms == 0
