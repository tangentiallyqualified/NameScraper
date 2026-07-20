"""Session-scoped AutoMux planning: probe files and attach mux plans.

Qt-free. The GUI coordinator marshals threading/signals around these
functions; queue submission calls ensure_state_plans() from its
thread-pool worker — never on the GUI thread, since cold probes over a
network share take minutes (mkvmerge -J results are cached and
concurrency-coalesced by _mkv_probe).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePath

from ..._mkv_locate import find_mkvmerge
from ..._mkv_probe import ProbeResult, probe_file
from ...engine._mux_planner import MuxSettings, build_mux_plan
from ...engine.models import (
    PreviewItem,
    ScanState,
    file_mux_active,  # noqa: F401  (round6 §1: engine owns these so _queue_bridge can use them)
    plan_has_actions,
)
from .settings_service import SettingsService


def mux_settings_from_service(svc: SettingsService) -> MuxSettings:
    return MuxSettings(
        merge_subs=svc.automux_merge_subs,
        merge_sub_languages=svc.automux_merge_sub_languages,
        default_sub_language=svc.automux_default_sub_language,
        untagged_sub_language=svc.automux_untagged_sub_language,
        strip_subs=svc.automux_strip_subs,
        retain_sub_languages=svc.automux_retain_sub_languages,
        strip_audio=svc.automux_strip_audio,
        retain_audio_languages=svc.automux_retain_audio_languages,
        default_audio_language=svc.automux_default_audio_language,
        strip_track_names=svc.automux_strip_track_names,
        no_fear=svc.automux_no_fear,
        exclude_commentary=svc.automux_exclude_commentary,
        convert_containers=svc.automux_convert_containers,
    )


def resolve_mkvmerge(svc: SettingsService | None) -> Path | None:
    if svc is None:
        return None
    return find_mkvmerge(svc.mkvmerge_path)


def automux_active(svc: SettingsService | None) -> bool:
    """AutoMux UI exists only when a toggle is on AND mkvmerge resolves
    (spec §3.1)."""
    return svc is not None and svc.automux_any_enabled and resolve_mkvmerge(svc) is not None


def companion_subs_for_item(
    item: PreviewItem,
    source_root: Path,
) -> list[tuple[str, str]]:
    """(source_relative, raw_lang_tag) pairs for the item's subtitle
    companions.

    The raw tag is recovered from the companion's computed new name:
    find_companion_subtitles builds companion names as
    ``<video new stem><tag><ext>``, so the tag is the text between the
    video's new stem and the subtitle extension (".eng", ".en.forced",
    "" for untagged).
    """
    video_stem = PurePath(item.new_name or "").stem
    pairs: list[tuple[str, str]] = []
    for companion in item.companions:
        if companion.file_type != "subtitle":
            continue
        try:
            rel = str(companion.original.relative_to(source_root))
        except ValueError:
            rel = str(companion.original)
        comp_stem = PurePath(companion.new_name or "").stem
        raw_tag = ""
        if video_stem and comp_stem.startswith(video_stem):
            raw_tag = comp_stem[len(video_stem) :]
        pairs.append((rel, raw_tag))
    return pairs


def plan_for_item(
    state: ScanState,
    index: int,
    *,
    probe: ProbeResult,
    settings: MuxSettings,
    mkvmerge_path: str,
    source_root: Path,
) -> dict | None:
    """Serialized MuxPlan for one preview item, or None when no remux."""
    item = state.preview_items[index]
    plan = build_mux_plan(
        probe=probe,
        companion_subs=companion_subs_for_item(item, source_root),
        settings=settings,
        new_name=item.new_name or "",
        mkvmerge_path=mkvmerge_path,
        source_name=item.original.name,
    )
    return plan.to_dict() if plan is not None else None


def ensure_state_plans(
    state: ScanState,
    svc: SettingsService,
    source_root: Path,
    *,
    prober: Callable | None = None,
    only_index: int | None = None,
) -> None:
    """Probe + plan actionable preview items, storing results on *state*.

    Skips user-modified plans (spec §5.1). No-op when the entry has
    AutoMux disabled or AutoMux is unavailable. Probe failures land in
    state.mux_probe_errors and leave the file on the plain rename path.
    """
    if state.automux_disabled or not automux_active(svc):
        return
    # Late-bound so tests can monkeypatch probe_file at module level.
    prober = prober or probe_file
    mkvmerge = resolve_mkvmerge(svc)
    settings = mux_settings_from_service(svc)
    if only_index is not None:
        indices: list[int] = [only_index]
    else:
        indices = sorted(
            index for index, item in enumerate(state.preview_items) if item_mux_probe_eligible(item)
        )
    for index in indices:
        if not (0 <= index < len(state.preview_items)):
            continue
        existing = state.mux_plans.get(index)
        if existing and existing.get("user_modified"):
            continue
        item = state.preview_items[index]
        if not item.new_name:
            continue
        probe = prober(mkvmerge, item.original)
        if not probe.ok:
            state.mux_probe_errors[index] = probe.error or "Unreadable file"
            state.mux_plans.pop(index, None)
            continue
        state.mux_probe_errors.pop(index, None)
        plan = plan_for_item(
            state,
            index,
            probe=probe,
            settings=settings,
            mkvmerge_path=str(mkvmerge),
            source_root=source_root,
        )
        if plan is None:
            state.mux_plans.pop(index, None)
        else:
            state.mux_plans[index] = plan


def item_mux_probe_eligible(item) -> bool:
    """Probe-eligible even when the name is already correct (round6 §1):
    mapped primary video item — has a target name, not unmatched, status
    OK or a REVIEW variant. Mirrors PreviewItem.is_actionable WITHOUT the
    name-already-correct exclusion; excludes unmatched because the queue
    can never process them (labels would lie)."""
    if item.new_name is None or item.is_unmatched:
        return False
    return item.status == "OK" or "REVIEW" in item.status


def state_has_mux_actions(state: ScanState) -> bool:
    if state.automux_disabled:
        return False
    return any(
        plan_has_actions(plan)
        for index, plan in state.mux_plans.items()
        if index not in state.mux_opt_outs
    )


def state_mux_eligible(state: ScanState) -> bool:
    """True when any cached plan carries actions, regardless of the
    per-show disable flag (the toggle button must stay reachable)."""
    return any(plan_has_actions(plan) for plan in state.mux_plans.values())


def effective_mux_plans(state: ScanState) -> dict[int, dict] | None:
    """Plans to bake into a queue job — None when AutoMux contributes
    nothing (disabled entry, or every plan edited down to a no-op)."""
    if state.automux_disabled:
        return None
    plans = {
        index: plan
        for index, plan in state.mux_plans.items()
        if index not in state.mux_opt_outs and plan_has_actions(plan)
    }
    return plans or None
