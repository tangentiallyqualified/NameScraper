"""Append-compatibility gate for multi-part episode merges.

mkvmerge can only concatenate files whose tracks line up one-to-one with
matching codecs and codec parameters. The gate compares each later part
against part 1 and returns the FIRST mismatch as a human-readable reason
(surfaced verbatim on the blocked row), or None when appending is safe.

A parameter value of 0 means "probe could not determine it" and never
fails the gate on its own -- blocking on missing metadata would strand
perfectly mergeable files.
"""

from __future__ import annotations

from .._mkv_probe import MediaTrack, ProbeResult


def _params_differ(a: int, b: int) -> bool:
    return a != 0 and b != 0 and a != b


def _track_mismatch(position: int, first: MediaTrack, other: MediaTrack, part: int) -> str | None:
    prefix = f"part {part} track {position}"
    if first.track_type != other.track_type:
        return f"{prefix}: track order differs ({first.track_type} vs {other.track_type})"
    if first.codec != other.codec:
        return f"{prefix}: {first.track_type} codec mismatch ({first.codec} vs {other.codec})"
    if first.track_type == "video" and (
        _params_differ(first.width, other.width) or _params_differ(first.height, other.height)
    ):
        return (
            f"{prefix}: video resolution mismatch"
            f" ({first.width}x{first.height} vs {other.width}x{other.height})"
        )
    if first.track_type == "audio":
        if _params_differ(first.sample_rate, other.sample_rate):
            return (
                f"{prefix}: audio sample rate mismatch ({first.sample_rate} vs {other.sample_rate})"
            )
        if _params_differ(first.channels, other.channels):
            return f"{prefix}: audio channel count mismatch ({first.channels} vs {other.channels})"
    return None


def check_append_compatibility(probes: list[ProbeResult]) -> str | None:
    """None when all parts can append; else the first mismatch reason."""
    if len(probes) < 2:
        return None
    for index, probe in enumerate(probes, start=1):
        if not probe.ok:
            return f"part {index} unreadable: {probe.error or 'probe failed'}"
    first = probes[0].tracks
    for part_number, probe in enumerate(probes[1:], start=2):
        if len(probe.tracks) != len(first):
            return f"part {part_number}: track count differs ({len(probe.tracks)} vs {len(first)})"
        for position, (a, b) in enumerate(zip(first, probe.tracks, strict=True)):
            reason = _track_mismatch(position, a, b, part_number)
            if reason is not None:
                return reason
    return None
