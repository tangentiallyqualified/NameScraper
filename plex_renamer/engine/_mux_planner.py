"""Pure mux planning: (probe, companion subs, settings) → MuxPlan.

The planner never touches the filesystem or subprocesses, so every rule
in spec §5 is unit-testable against synthetic ProbeResults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePath
from typing import Any

from .._lang_normalize import normalize_lang, normalize_lang_list
from .._mkv_probe import MediaTrack, ProbeResult
from ._mux_models import MuxSettings as MuxSettings, TrackDecision as TrackDecision

_AUDIO_FLOOR_WARNING = "Audio retain filter would strip every audio track — keeping all audio"
_COMMENTARY_MARKER = "commentary"


def _is_commentary(name: str) -> bool:
    return _COMMENTARY_MARKER in name.lower()


@dataclass
class SubtitleMergeDecision:
    source_relative: str
    action: str  # "merge" | "rename"
    language: str
    set_default: bool
    forced: bool = False
    # Timestamp shift applied when merging (--sync 0:<ms>): the sum of the
    # preceding parts' durations for a later part's external sub. 0 for
    # part-1 / single-file subs.
    sync_offset_ms: int = 0


@dataclass
class MuxPlan:
    output_name: str  # library-format name, always .mkv
    track_decisions: list[TrackDecision] = field(default_factory=list)
    subtitle_merges: list[SubtitleMergeDecision] = field(default_factory=list)
    # Multi-part merge: source-relative paths of parts 2..N in append
    # order. Part 1 is the op's own source and is not repeated here.
    append_sources: list[str] = field(default_factory=list)
    strip_track_names: bool = False
    no_fear: bool = False
    mkvmerge_path: str = ""  # baked at queue time; re-resolved if stale
    warnings: list[str] = field(default_factory=list)
    # True when the source container isn't MKV and settings ask for
    # conversion — counts as a mux action on its own, so a clean MP4
    # still gets remuxed (losslessly) into an MKV container.
    container_conversion: bool = False
    user_modified: bool = False

    @property
    def has_actions(self) -> bool:
        return (
            any(not d.keep for d in self.track_decisions)
            or any(m.action == "merge" for m in self.subtitle_merges)
            or self.container_conversion
            or bool(self.append_sources)
        )

    @property
    def merged_sub_paths(self) -> list[str]:
        return [m.source_relative for m in self.subtitle_merges if m.action == "merge"]

    @property
    def append_source_paths(self) -> list[str]:
        return list(self.append_sources)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MuxPlan:
        d = dict(d)
        d.setdefault("container_conversion", False)
        d.setdefault("append_sources", [])
        for merge in d.get("subtitle_merges", []):
            if isinstance(merge, dict):
                merge.setdefault("sync_offset_ms", 0)
        d["track_decisions"] = [TrackDecision(**t) for t in d.get("track_decisions", [])]
        d["subtitle_merges"] = [SubtitleMergeDecision(**m) for m in d.get("subtitle_merges", [])]
        return cls(**d)


def _companion_language(raw_tag: str) -> str | None:
    """Language of an external sub from its filename tag, or None if untagged.

    Raw tags look like ".eng", ".en.forced", "" — the first dotted
    component is the language, modifiers (forced/sdh/...) are ignored.
    """
    for part in raw_tag.split("."):
        lang = normalize_lang(part)
        if lang and lang != "und":
            return lang
    return None


def _companion_is_forced(raw_tag: str) -> bool:
    """True when any dotted component of the tag is "forced" (spec)."""
    return any(part.lower() == "forced" for part in raw_tag.split("."))


def _decide_embedded(
    tracks: list[MediaTrack],
    *,
    strip: bool,
    retain: list[str],
    exclude_commentary: bool = False,
) -> list[TrackDecision]:
    decisions = []
    for track in tracks:
        commentary = _is_commentary(track.name)
        if not strip:
            keep, reason = True, "stripping disabled"
        elif commentary and exclude_commentary:
            keep, reason = False, "commentary excluded"
        elif track.language == "und":
            keep, reason = True, "und retained"
        elif track.language in retain:
            keep, reason = True, "retained"
        else:
            keep, reason = False, "not in retain list"
        decisions.append(
            TrackDecision(
                track_id=track.track_id,
                track_type=track.track_type,
                codec=track.codec,
                language=track.language,
                name=track.name,
                keep=keep,
                make_default=track.is_default,
                reason=reason,
                is_forced=track.is_forced,
                is_commentary=commentary,
            )
        )
    return decisions


def _apply_default_language(
    decisions: list[TrackDecision],
    default_language: str,
) -> None:
    """Best kept match gets the default flag; other kept tracks lose it.

    Ranking among kept tracks in the target language: full (non-forced,
    non-commentary) first, then forced (non-commentary). Commentary
    tracks are never default-eligible; when only commentary tracks
    match, existing flags are left untouched.
    """
    lang = normalize_lang(default_language)
    if not lang:
        return
    kept = [d for d in decisions if d.keep]
    eligible = [d for d in kept if d.language == lang and not d.is_commentary]
    if not eligible:
        return
    winner = next((d for d in eligible if not d.is_forced), eligible[0])
    for d in kept:
        d.make_default = d is winner


def build_mux_plan(
    *,
    probe: ProbeResult,
    companion_subs: list[tuple[str, str]],
    settings: MuxSettings,
    new_name: str,
    mkvmerge_path: str = "",
    source_name: str = "",
) -> MuxPlan | None:
    """Build the remux plan for one file, or None when no remux is needed."""
    if not probe.ok:
        return None

    retain_subs = normalize_lang_list(settings.retain_sub_languages)
    retain_audio = normalize_lang_list(settings.retain_audio_languages)
    merge_langs = normalize_lang_list(settings.merge_sub_languages)

    decisions: list[TrackDecision] = []
    for track in probe.video_tracks:
        decisions.append(
            TrackDecision(
                track_id=track.track_id,
                track_type="video",
                codec=track.codec,
                language=track.language,
                name=track.name,
                keep=True,
                make_default=track.is_default,
                reason="video",
            )
        )

    audio = _decide_embedded(
        probe.audio_tracks,
        strip=settings.strip_audio,
        retain=retain_audio,
        exclude_commentary=settings.exclude_commentary,
    )
    warnings: list[str] = []
    if settings.strip_audio and audio and not any(d.keep for d in audio):
        for d in audio:
            d.keep = True
            d.reason = "audio safety floor"
        warnings.append(_AUDIO_FLOOR_WARNING)
    if settings.dedupe_audio:
        from ._mux_audio_dedup import dedupe_audio_decisions

        tracks_by_id = {track.track_id: track for track in probe.audio_tracks}
        warnings.extend(dedupe_audio_decisions(audio, tracks_by_id, settings))
    decisions.extend(audio)

    subs = _decide_embedded(
        probe.subtitle_tracks,
        strip=settings.strip_subs,
        retain=retain_subs,
        exclude_commentary=settings.exclude_commentary,
    )
    decisions.extend(subs)

    _apply_default_language(
        [d for d in decisions if d.track_type == "audio"], settings.default_audio_language
    )

    # External subtitle decisions.
    merges: list[SubtitleMergeDecision] = []
    default_sub = normalize_lang(settings.default_sub_language) or ""
    if settings.merge_subs:
        substitute = normalize_lang(settings.untagged_sub_language)
        candidates: list[tuple[int, SubtitleMergeDecision]] = []
        for rel_path, raw_tag in companion_subs:
            lang = _companion_language(raw_tag)
            if lang is None:
                # Untagged external subs always merge (spec §3.1):
                # substitute language when configured, else "und".
                merged_lang = substitute or "und"
                candidates.append(
                    (
                        len(merge_langs),
                        SubtitleMergeDecision(
                            source_relative=rel_path,
                            action="merge",
                            language=merged_lang,
                            set_default=False,
                            forced=_companion_is_forced(raw_tag),
                        ),
                    )
                )
            elif lang in merge_langs:
                candidates.append(
                    (
                        merge_langs.index(lang),
                        SubtitleMergeDecision(
                            source_relative=rel_path,
                            action="merge",
                            language=lang,
                            set_default=False,
                            forced=_companion_is_forced(raw_tag),
                        ),
                    )
                )
            else:
                candidates.append(
                    (
                        len(merge_langs) + 1,
                        SubtitleMergeDecision(
                            source_relative=rel_path,
                            action="rename",
                            language=lang,
                            set_default=False,
                            forced=_companion_is_forced(raw_tag),
                        ),
                    )
                )
        candidates.sort(key=lambda pair: pair[0])
        merges = [decision for _, decision in candidates]
    else:
        merges = [
            SubtitleMergeDecision(
                source_relative=rel_path,
                action="rename",
                language=_companion_language(raw_tag) or "und",
                set_default=False,
                forced=_companion_is_forced(raw_tag),
            )
            for rel_path, raw_tag in companion_subs
        ]

    # Default subtitle flag precedence (spec): full merged match →
    # full embedded → forced embedded → forced merged. Forced merges
    # never steal the default from a full track.
    sub_decisions = [d for d in decisions if d.track_type == "subtitles"]
    if default_sub:
        merged_matches = [m for m in merges if m.action == "merge" and m.language == default_sub]
        full_merge = next((m for m in merged_matches if not m.forced), None)
        embedded_eligible = [
            d for d in sub_decisions if d.keep and d.language == default_sub and not d.is_commentary
        ]
        if full_merge is not None:
            full_merge.set_default = True
            for d in sub_decisions:
                d.make_default = False
        elif embedded_eligible:
            _apply_default_language(sub_decisions, default_sub)
        elif merged_matches:
            merged_matches[0].set_default = True
            for d in sub_decisions:
                d.make_default = False

    convert = bool(
        settings.convert_containers
        and source_name
        and PurePath(source_name).suffix.lower() != ".mkv"
    )
    plan = MuxPlan(
        output_name=str(PurePath(new_name).with_suffix(".mkv")),
        track_decisions=decisions,
        subtitle_merges=merges,
        strip_track_names=settings.strip_track_names,
        no_fear=settings.no_fear,
        mkvmerge_path=mkvmerge_path,
        warnings=warnings,
        container_conversion=convert,
    )
    return plan if plan.has_actions else None
