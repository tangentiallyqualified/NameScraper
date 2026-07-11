"""Build the mkvmerge argv for one remux op from its MuxPlan."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .engine._mux_planner import MuxPlan


def _selection_args(flag: str, no_flag: str, decisions) -> list[str]:
    """--audio-tracks/--subtitle-tracks selection for one track type."""
    kept = [d for d in decisions if d.keep]
    if len(kept) == len(decisions):
        return []                       # nothing stripped — no selection
    if not kept:
        return [no_flag]
    return [flag, ",".join(str(d.track_id) for d in kept)]


def build_mkvmerge_args(
    *,
    mkvmerge_path: str,
    source: Path,
    output: Path,
    plan: MuxPlan,
    resolve_sub: Callable[[str], Path],
    title: str | None = None,
) -> list[str]:
    args: list[str] = [mkvmerge_path, "--output", str(output)]
    if title:
        args += ["--title", title]

    audio = [d for d in plan.track_decisions if d.track_type == "audio"]
    subs = [d for d in plan.track_decisions if d.track_type == "subtitles"]

    args += _selection_args("--audio-tracks", "--no-audio", audio)
    args += _selection_args("--subtitle-tracks", "--no-subtitles", subs)

    for decision in audio + subs:
        if not decision.keep:
            continue
        flag = "yes" if decision.make_default else "no"
        args += ["--default-track-flag", f"{decision.track_id}:{flag}"]

    if plan.strip_track_names:
        for decision in plan.track_decisions:
            if decision.keep and decision.name:
                args += ["--track-name", f"{decision.track_id}:"]

    args.append(str(source))

    for merge in plan.subtitle_merges:
        if merge.action != "merge":
            continue
        sub_path = resolve_sub(merge.source_relative)
        default = "yes" if merge.set_default else "no"
        args += ["--language", f"0:{merge.language}",
                 "--default-track-flag", f"0:{default}"]
        if plan.strip_track_names:
            args += ["--track-name", "0:"]
        args.append(str(sub_path))

    return args


def build_mkvpropedit_title_args(
    propedit_path: str,
    target: Path,
    title: str,
) -> list[str]:
    """argv to set the container title in place (no remux)."""
    return [str(propedit_path), str(target),
            "--edit", "info", "--set", f"title={title}"]
