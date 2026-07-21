"""MuxPlan append-source model + serialization back-compat."""

from __future__ import annotations

from plex_renamer.engine._mux_planner import MuxPlan, SubtitleMergeDecision


def test_append_sources_count_as_actions() -> None:
    plan = MuxPlan(output_name="out.mkv", append_sources=["a (2).mkv"])
    assert plan.has_actions
    assert plan.append_source_paths == ["a (2).mkv"]


def test_plan_without_append_or_other_actions_is_inert() -> None:
    assert not MuxPlan(output_name="out.mkv").has_actions


def test_round_trip_preserves_append_and_offsets() -> None:
    plan = MuxPlan(
        output_name="out.mkv",
        append_sources=["p2.mkv", "p3.mkv"],
        subtitle_merges=[
            SubtitleMergeDecision(
                source_relative="p2.eng.srt",
                action="merge",
                language="eng",
                set_default=False,
                sync_offset_ms=1_500_000,
            )
        ],
    )
    restored = MuxPlan.from_dict(plan.to_dict())
    assert restored.append_sources == ["p2.mkv", "p3.mkv"]
    assert restored.subtitle_merges[0].sync_offset_ms == 1_500_000


def test_from_dict_backcompat_defaults() -> None:
    legacy = {
        "output_name": "out.mkv",
        "track_decisions": [],
        "subtitle_merges": [
            {
                "source_relative": "a.srt",
                "action": "merge",
                "language": "eng",
                "set_default": False,
                "forced": False,
            }
        ],
        "strip_track_names": False,
        "no_fear": False,
        "mkvmerge_path": "",
        "warnings": [],
        "user_modified": False,
    }
    plan = MuxPlan.from_dict(legacy)
    assert plan.append_sources == []
    assert plan.subtitle_merges[0].sync_offset_ms == 0
