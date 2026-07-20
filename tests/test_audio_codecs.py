"""Canonical audio codec keys and efficiency weights."""

import pytest

from plex_renamer.engine._audio_codecs import (
    DEFAULT_CODEC_WEIGHTS,
    LOSSLESS_CODECS,
    canonical_codec,
    codec_weight,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("E-AC-3", "eac3"),
        ("AC-3", "ac3"),
        ("AC-3 Dolby Surround EX", "ac3"),
        ("AAC", "aac"),
        ("Opus", "opus"),
        ("DTS", "dts"),
        ("DTS-HD Master Audio", "dts_hd_ma"),
        ("DTS-HD High Resolution Audio", "dts_hd_hra"),
        ("TrueHD Atmos", "truehd"),
        ("FLAC", "flac"),
        ("A_MS/ACM", "a_ms/acm"),
        ("PCM", "pcm"),
        ("MP3", "mp3"),
        ("Vorbis", "vorbis"),
    ],
)
def test_canonical_codec(raw: str, expected: str) -> None:
    assert canonical_codec(raw) == expected


def test_lossless_membership() -> None:
    assert "truehd" in LOSSLESS_CODECS
    assert "eac3" not in LOSSLESS_CODECS


def test_codec_weight_user_override_and_fallbacks() -> None:
    assert codec_weight("opus", {}) == DEFAULT_CODEC_WEIGHTS["opus"]
    assert codec_weight("opus", {"opus": 1.7}) == 1.7
    assert codec_weight("opus", {"opus": -3.0}) == DEFAULT_CODEC_WEIGHTS["opus"]
    assert codec_weight("mystery", {}) == 1.0
