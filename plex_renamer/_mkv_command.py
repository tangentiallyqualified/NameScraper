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


def _cover_attachment_args(attach_flag: str, cover_path) -> list[str]:
    return ["--attachment-name", "cover.jpg",
            "--attachment-mime-type", "image/jpeg",
            attach_flag, str(cover_path)]


def build_mkvmerge_args(
    *,
    mkvmerge_path: str,
    source: Path,
    output: Path,
    plan: MuxPlan,
    resolve_sub: Callable[[str], Path],
    title: str | None = None,
    global_tags_path: str | Path | None = None,
    cover_path: str | Path | None = None,
) -> list[str]:
    args: list[str] = [mkvmerge_path, "--output", str(output)]
    if title:
        args += ["--title", title]
    if global_tags_path:
        args += ["--global-tags", str(global_tags_path)]
    if cover_path:
        args += _cover_attachment_args("--attach-file", cover_path)

    audio = [d for d in plan.track_decisions if d.track_type == "audio"]
    subs = [d for d in plan.track_decisions if d.track_type == "subtitles"]

    args += _selection_args("--audio-tracks", "--no-audio", audio)
    args += _selection_args("--subtitle-tracks", "--no-subtitles", subs)

    for decision in audio + subs:
        if not decision.keep:
            continue
        flag = "yes" if decision.make_default else "no"
        args += ["--default-track-flag", f"{decision.track_id}:{flag}"]
        forced = "yes" if decision.is_forced else "no"
        args += ["--forced-display-flag", f"{decision.track_id}:{forced}"]

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
        forced = "yes" if merge.forced else "no"
        args += ["--language", f"0:{merge.language}",
                 "--default-track-flag", f"0:{default}",
                 "--forced-display-flag", f"0:{forced}"]
        if plan.strip_track_names:
            args += ["--track-name", "0:"]
        args.append(str(sub_path))

    return args


def build_mkvpropedit_args(
    propedit_path: str,
    target: Path,
    *,
    title: str | None = None,
    tags_path: str | Path | None = None,
    cover_path: str | Path | None = None,
) -> list[str]:
    """argv for in-place container edits (title/tags/cover, no remux)."""
    args = [str(propedit_path), str(target)]
    if title is not None:
        args += ["--edit", "info", "--set", f"title={title}"]
    if tags_path:
        args += ["--tags", f"global:{tags_path}"]
    if cover_path:
        args += _cover_attachment_args("--add-attachment", cover_path)
    return args
