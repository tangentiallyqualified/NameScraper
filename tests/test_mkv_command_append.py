"""Append syntax + per-part flags + subtitle sync offsets in the argv."""

from __future__ import annotations

from pathlib import Path

from plex_renamer._mkv_command import build_mkvmerge_args
from plex_renamer.engine._mux_planner import MuxPlan, SubtitleMergeDecision, TrackDecision


def _audio_decision(track_id: int = 1, keep: bool = True) -> TrackDecision:
    return TrackDecision(
        track_id=track_id,
        track_type="audio",
        codec="AAC",
        language="eng",
        name="",
        keep=keep,
        make_default=True,
        reason="",
    )


def _args(plan: MuxPlan) -> list[str]:
    return build_mkvmerge_args(
        mkvmerge_path="mkvmerge",
        source=Path("src") / "p1.mkv",
        output=Path("out") / "o.mkv",
        plan=plan,
        resolve_sub=lambda rel: Path("src") / rel,
        resolve_part=lambda rel: Path("src") / rel,
    )


def test_plain_plan_has_no_plus_tokens() -> None:
    assert "+" not in _args(MuxPlan(output_name="o.mkv"))


def test_parts_follow_source_with_plus_separators() -> None:
    args = _args(MuxPlan(output_name="o.mkv", append_sources=["p2.mkv", "p3.mkv"]))
    p1 = args.index(str(Path("src") / "p1.mkv"))
    assert args[p1 + 1 : p1 + 5] == [
        "+",
        str(Path("src") / "p2.mkv"),
        "+",
        str(Path("src") / "p3.mkv"),
    ]


def test_selection_flags_repeat_before_each_part() -> None:
    plan = MuxPlan(
        output_name="o.mkv",
        track_decisions=[_audio_decision(1, keep=True), _audio_decision(2, keep=False)],
        append_sources=["p2.mkv"],
    )
    args = _args(plan)
    # --audio-tracks 1 must appear once for the main source and once for p2.
    assert args.count("--audio-tracks") == 2
    p2 = args.index(str(Path("src") / "p2.mkv"))
    before_p2 = args[args.index("+") : p2]
    assert "--audio-tracks" in before_p2


def test_merge_sub_offset_emits_sync() -> None:
    plan = MuxPlan(
        output_name="o.mkv",
        append_sources=["p2.mkv"],
        subtitle_merges=[
            SubtitleMergeDecision(
                source_relative="p2.eng.srt",
                action="merge",
                language="eng",
                set_default=False,
                sync_offset_ms=1500,
            )
        ],
    )
    args = _args(plan)
    sync = args.index("--sync")
    assert args[sync + 1] == "0:1500"
    # The sync flag must precede its subtitle source path.
    assert args.index(str(Path("src") / "p2.eng.srt")) > sync


def test_zero_offset_emits_no_sync() -> None:
    plan = MuxPlan(
        output_name="o.mkv",
        subtitle_merges=[
            SubtitleMergeDecision(
                source_relative="a.srt",
                action="merge",
                language="eng",
                set_default=False,
                sync_offset_ms=0,
            )
        ],
    )
    assert "--sync" not in _args(plan)
