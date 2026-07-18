"""Pure mux planning: (probe, companion subs, settings) → MuxPlan.

The planner never touches the filesystem or subprocesses, so every rule
in spec §5 is unit-testable against synthetic ProbeResults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePath

from .._lang_normalize import normalize_lang, normalize_lang_list
from .._mkv_probe import MediaTrack, ProbeResult

_AUDIO_FLOOR_WARNING = "Audio retain filter would strip every audio track — keeping all audio"


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


@dataclass
class SubtitleMergeDecision:
    source_relative: str
    action: str  # "merge" | "rename"
    language: str
    set_default: bool


@dataclass
class MuxPlan:
    output_name: str  # library-format name, always .mkv
    track_decisions: list[TrackDecision] = field(default_factory=list)
    subtitle_merges: list[SubtitleMergeDecision] = field(default_factory=list)
    strip_track_names: bool = False
    no_fear: bool = False
    mkvmerge_path: str = ""  # baked at queue time; re-resolved if stale
    warnings: list[str] = field(default_factory=list)
    user_modified: bool = False

    @property
    def has_actions(self) -> bool:
        return any(not d.keep for d in self.track_decisions) or any(
            m.action == "merge" for m in self.subtitle_merges
        )

    @property
    def merged_sub_paths(self) -> list[str]:
        return [m.source_relative for m in self.subtitle_merges if m.action == "merge"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> MuxPlan:
        d = dict(d)
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


def _decide_embedded(
    tracks: list[MediaTrack],
    *,
    strip: bool,
    retain: list[str],
) -> list[TrackDecision]:
    decisions = []
    for track in tracks:
        if not strip:
            keep, reason = True, "stripping disabled"
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
            )
        )
    return decisions


def _apply_default_language(
    decisions: list[TrackDecision],
    default_language: str,
) -> None:
    """First kept match gets the default flag; other tracks lose it."""
    lang = normalize_lang(default_language)
    if not lang:
        return
    kept = [d for d in decisions if d.keep]
    if not any(d.language == lang for d in kept):
        return
    found = False
    for d in kept:
        d.make_default = (not found) and d.language == lang
        found = found or d.language == lang


def build_mux_plan(
    *,
    probe: ProbeResult,
    companion_subs: list[tuple[str, str]],
    settings: MuxSettings,
    new_name: str,
    mkvmerge_path: str = "",
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

    audio = _decide_embedded(probe.audio_tracks, strip=settings.strip_audio, retain=retain_audio)
    warnings: list[str] = []
    if settings.strip_audio and audio and not any(d.keep for d in audio):
        for d in audio:
            d.keep = True
            d.reason = "audio safety floor"
        warnings.append(_AUDIO_FLOOR_WARNING)
    decisions.extend(audio)

    subs = _decide_embedded(probe.subtitle_tracks, strip=settings.strip_subs, retain=retain_subs)
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
            )
            for rel_path, raw_tag in companion_subs
        ]

    # Default subtitle flag: a merged match wins over embedded matches.
    sub_decisions = [d for d in decisions if d.track_type == "subtitles"]
    merged_default = False
    if default_sub:
        for m in merges:
            if m.action == "merge" and m.language == default_sub:
                m.set_default = True
                merged_default = True
                break
        if merged_default:
            for d in sub_decisions:
                d.make_default = False
        else:
            _apply_default_language(sub_decisions, default_sub)

    plan = MuxPlan(
        output_name=str(PurePath(new_name).with_suffix(".mkv")),
        track_decisions=decisions,
        subtitle_merges=merges,
        strip_track_names=settings.strip_track_names,
        no_fear=settings.no_fear,
        mkvmerge_path=mkvmerge_path,
        warnings=warnings,
    )
    return plan if plan.has_actions else None
