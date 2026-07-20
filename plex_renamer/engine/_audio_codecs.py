"""Audio codec canonicalization + efficiency weights (AC3 = 1.0).

Default weights approximate the bitrate ratio at which typical encoders
reach stereo transparency, relative to AC3:
- opus 2.0   — https://wiki.hydrogenaud.io/index.php?title=Hydrogenaudio_listening_tests (~96-128 kb/s stereo)
- aac 1.5    — https://wiki.hydrogenaud.io/index.php?title=Hydrogenaudio_listening_tests (~128-160 kb/s stereo)
- vorbis 1.4 — https://wiki.hydrogenaud.io/index.php?title=Hydrogenaudio_listening_tests (~160 kb/s stereo)
- eac3 1.3   — https://professionalsupport.dolby.com (~160-192 kb/s stereo)
- mp3 1.1    — https://wiki.hydrogenaud.io/index.php?title=Hydrogenaudio_listening_tests ~192 kb/s stereo
- ac3 1.0    — https://professionalsupport.dolby.com (~224-256 kb/s stereo)
- dts 0.7    — https://dts.com (~320+ kb/s stereo equivalent)
Weights are comparators, not quality meters: they only ever rank two
encodes of the same master, and the transparency ceiling + tie band in
the dedup pass bound the linear model where it is least accurate.
"""

from __future__ import annotations

LOSSLESS_CODECS: frozenset[str] = frozenset({"truehd", "dts_hd_ma", "flac", "pcm", "alac"})

DEFAULT_CODEC_WEIGHTS: dict[str, float] = {
    "opus": 2.0,
    "aac": 1.5,
    "vorbis": 1.4,
    "eac3": 1.3,
    "mp3": 1.1,
    "ac3": 1.0,
    "dts": 0.7,
}

_CANONICAL_PREFIXES: list[tuple[str, str]] = [
    # Order matters: longest/most-specific first.
    ("dts-hd master", "dts_hd_ma"),
    ("dts-hd high", "dts_hd_hra"),
    ("dts", "dts"),
    ("e-ac-3", "eac3"),
    ("eac3", "eac3"),
    ("ac-3", "ac3"),
    ("ac3", "ac3"),
    ("truehd", "truehd"),
    ("mlp fba", "truehd"),
    ("aac", "aac"),
    ("opus", "opus"),
    ("vorbis", "vorbis"),
    ("flac", "flac"),
    ("alac", "alac"),
    ("pcm", "pcm"),
    ("mp3", "mp3"),
    ("mpeg-1/2 audio layer iii", "mp3"),
]


def canonical_codec(codec: str) -> str:
    lowered = codec.strip().lower()
    for prefix, key in _CANONICAL_PREFIXES:
        if lowered.startswith(prefix):
            return key
    return lowered.split()[0] if lowered else ""


def codec_weight(codec_key: str, user_weights: dict[str, float]) -> float:
    user_value = user_weights.get(codec_key, 0.0)
    if isinstance(user_value, (int, float)) and user_value > 0:
        return float(user_value)
    return DEFAULT_CODEC_WEIGHTS.get(codec_key, 1.0)
