"""Shared mux dataclasses.

`_mux_planner` and `_mux_audio_dedup` both need `MuxSettings` and
`TrackDecision`; living here lets the dedup pass import them without
creating a dependency cycle back to the planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MuxSettings:
    """Snapshot of the automux_* settings relevant to planning."""

    merge_subs: bool = False
    merge_sub_languages: list[str] = field(default_factory=list)
    default_sub_language: str = ""
    untagged_sub_language: str = ""
    strip_subs: bool = False
    retain_sub_languages: list[str] = field(default_factory=list)
    strip_audio: bool = False
    retain_audio_languages: list[str] = field(default_factory=list)
    default_audio_language: str = ""
    strip_track_names: bool = False
    no_fear: bool = False
    exclude_commentary: bool = False
    convert_containers: bool = False
    dedupe_audio: bool = False
    dedupe_keep_per_layout: bool = True
    lossless_policy: str = "quality"
    tie_prefer_smaller: bool = True
    tie_tolerance_pct: int = 15
    transparency_kbps_per_channel: int = 160
    codec_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class TrackDecision:
    track_id: int
    track_type: str
    codec: str
    language: str
    name: str
    keep: bool
    make_default: bool
    reason: str
    is_forced: bool = False
    is_commentary: bool = False
