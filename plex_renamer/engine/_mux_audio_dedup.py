"""Same-language audio dedup by effective quality (spec 2026-07-20).

Pure: operates on TrackDecisions + MediaTracks, no I/O. Never guesses:
any unknown channels, or unknown bitrate on a lossy track, exempts that
track's whole language group (better to keep a duplicate than delete a
unique track on bad data).
"""

from __future__ import annotations

from dataclasses import dataclass

from .._mkv_probe import MediaTrack
from ._audio_codecs import LOSSLESS_CODECS, canonical_codec, codec_weight
from ._mux_models import MuxSettings, TrackDecision

_DESCRIPTIVE_MARKERS = ("descriptive", "description", "audio description", " ad ")


def _is_descriptive(name: str) -> bool:
    padded = f" {name.lower()} "
    return any(marker in padded for marker in _DESCRIPTIVE_MARKERS)


@dataclass
class _Scored:
    decision: TrackDecision
    channels: int
    bitrate_kbps: float
    codec_key: str
    lossless: bool
    effective: float  # bitrate_kbps * weight (0 for lossless)
    transparent: bool

    @property
    def label(self) -> str:
        return f"{self.codec_key} {self.channels}ch"


def _score(decision: TrackDecision, track: MediaTrack, settings: MuxSettings) -> _Scored | None:
    """None = not enough data to judge this track."""
    codec_key = canonical_codec(decision.codec)
    lossless = codec_key in LOSSLESS_CODECS
    channels = track.channels
    kbps = track.bitrate_bps / 1000.0
    if channels <= 0 or (not lossless and kbps <= 0):
        return None
    effective = 0.0 if lossless else kbps * codec_weight(codec_key, settings.codec_weights)
    transparent = lossless or (effective / channels >= settings.transparency_kbps_per_channel)
    return _Scored(
        decision=decision,
        channels=channels,
        bitrate_kbps=kbps,
        codec_key=codec_key,
        lossless=lossless,
        effective=effective,
        transparent=transparent,
    )


def _better(a: _Scored, b: _Scored, settings: MuxSettings) -> _Scored:
    """Winner between two lossy tracks of the same channel count."""
    if a.transparent and b.transparent:
        return _tie_pick(a, b, settings)
    high, low = (a, b) if a.effective >= b.effective else (b, a)
    if high.effective <= 0:
        return a
    if (high.effective - low.effective) / high.effective <= settings.tie_tolerance_pct / 100.0:
        return _tie_pick(a, b, settings)
    return high


def _tie_pick(a: _Scored, b: _Scored, settings: MuxSettings) -> _Scored:
    if settings.tie_prefer_smaller:
        return a if a.bitrate_kbps <= b.bitrate_kbps else b
    return a if a.effective >= b.effective else b


def dedupe_audio_decisions(
    decisions: list[TrackDecision],
    tracks_by_id: dict[int, MediaTrack],
    settings: MuxSettings,
) -> list[str]:
    warnings: list[str] = []
    by_language: dict[str, list[TrackDecision]] = {}
    for decision in decisions:
        if decision.track_type != "audio" or not decision.keep:
            continue
        if decision.is_commentary or decision.language == "und":
            continue
        if _is_descriptive(decision.name):
            continue
        by_language.setdefault(decision.language, []).append(decision)

    for language, group in by_language.items():
        if len(group) < 2:
            continue
        scored: list[_Scored] = []
        incomplete: TrackDecision | None = None
        for decision in group:
            track = tracks_by_id.get(decision.track_id)
            entry = _score(decision, track, settings) if track is not None else None
            if entry is None:
                incomplete = decision
                break
            scored.append(entry)
        if incomplete is not None:
            warnings.append(
                f"Audio dedup skipped for '{language}': track {incomplete.track_id} "
                f"({incomplete.codec}) has unknown bitrate or channels"
            )
            continue

        # Lossless space policy: a transparent lossy track justifies
        # dropping lossless — across channel layouts by design.
        if settings.lossless_policy == "space" and any(
            s.transparent and not s.lossless for s in scored
        ):
            for entry in scored:
                if entry.lossless:
                    entry.decision.keep = False
                    entry.decision.reason = (
                        f"duplicate: lossless {entry.label} dropped for "
                        f"transparent lossy track (space policy)"
                    )
            scored = [s for s in scored if s.decision.keep]

        # Per-layout winners.
        by_channels: dict[int, list[_Scored]] = {}
        for entry in scored:
            by_channels.setdefault(entry.channels, []).append(entry)
        layout_winners: dict[int, _Scored] = {}
        for channels, members in by_channels.items():
            lossless_members = [m for m in members if m.lossless]
            if lossless_members:
                winner = max(lossless_members, key=lambda m: m.bitrate_kbps)
            else:
                winner = members[0]
                for member in members[1:]:
                    winner = _better(winner, member, settings)
            layout_winners[channels] = winner
            for member in members:
                if member is not winner:
                    member.decision.keep = False
                    member.decision.reason = (
                        f"duplicate: {member.label} outranked by {winner.label}"
                    )

        if not settings.dedupe_keep_per_layout and len(layout_winners) > 1:
            top = layout_winners[max(layout_winners)]
            for winner in layout_winners.values():
                if winner is not top:
                    winner.decision.keep = False
                    winner.decision.reason = (
                        f"duplicate: {winner.label} dropped for higher layout {top.label}"
                    )

        # Post-group default-flag rescue: every drop layer above (space
        # policy, per-layout, cross-layout) can strip the flag from a
        # track it dropped. Checked once here -- not per drop-site -- so
        # a later layer dropping the same track can't leave the flag
        # stranded on a member a previous layer already promoted.
        # ``group`` (not ``scored``, which lossless space-policy drops
        # are spliced out of) is the source of truth for "did anything
        # in this language group carry the flag when it got dropped".
        dropped_had_default = any(not d.keep and d.make_default for d in group)
        already_has_default = any(d.keep and d.make_default for d in decisions)
        if dropped_had_default and not already_has_default:
            survivors = [s for s in scored if s.decision.keep]
            if survivors:
                # Best surviving member: highest channel count, then
                # highest effective quality -- lossless tracks have
                # effective pinned to 0 by design, so the `lossless` flag
                # is ranked ahead of `effective` to still count them as
                # best-in-layout, consistent with the layout-winner logic
                # above (lossless wins its own channel layout outright).
                best = max(survivors, key=lambda s: (s.channels, s.lossless, s.effective))
                best.decision.make_default = True
    return warnings
