"""mkvmerge argv construction from a MuxPlan."""
from pathlib import Path

from plex_renamer._mkv_command import build_mkvmerge_args
from plex_renamer.engine._mux_planner import (
    MuxPlan,
    SubtitleMergeDecision,
    TrackDecision,
)


def _td(tid, ttype, lang, keep=True, default=False, name="", forced=False):
    return TrackDecision(
        track_id=tid, track_type=ttype, codec="c", language=lang,
        name=name, keep=keep, make_default=default, reason="",
        is_forced=forced)


def _args(plan):
    return build_mkvmerge_args(
        mkvmerge_path="mkvmerge",
        source=Path("C:/lib/Show/a.mkv"),
        output=Path("C:/out/Show (2020)/X.mkv.tmp-abcd1234.mkv"),
        plan=plan,
        resolve_sub=lambda rel: Path("C:/lib") / rel,
    )


def test_track_selection_and_merge_inputs():
    plan = MuxPlan(
        output_name="X.mkv",
        track_decisions=[
            _td(0, "video", "und"),
            _td(1, "audio", "eng", keep=True, default=True),
            _td(2, "audio", "jpn", keep=False),
            _td(3, "subtitles", "eng", keep=True, default=True),
            _td(4, "subtitles", "fre", keep=False),
        ],
        subtitle_merges=[SubtitleMergeDecision(
            source_relative="Show/a.eng.srt", action="merge",
            language="eng", set_default=False)],
    )
    args = _args(plan)
    assert args[0] == "mkvmerge"
    assert args[1:3] == ["--output",
                         "C:\\out\\Show (2020)\\X.mkv.tmp-abcd1234.mkv"] or \
           args[1:3] == ["--output",
                         "C:/out/Show (2020)/X.mkv.tmp-abcd1234.mkv"]
    joined = " ".join(args)
    assert "--audio-tracks 1" in joined
    assert "--subtitle-tracks 3" in joined
    assert "--default-track-flag 1:yes" in joined
    assert "--default-track-flag 3:yes" in joined
    # Merge input: options precede the sub file, TIDs are file-relative 0.
    sub_index = args.index(str(Path("C:/lib") / "Show/a.eng.srt"))
    sub_opts = " ".join(args[:sub_index])
    assert "--language 0:eng" in sub_opts
    assert "--default-track-flag 0:no" in sub_opts
    # Source file comes before the merged sub input.
    assert args.index(str(Path("C:/lib/Show/a.mkv"))) < sub_index


def test_all_subs_stripped_uses_no_subtitles():
    plan = MuxPlan(
        output_name="X.mkv",
        track_decisions=[
            _td(0, "video", "und"),
            _td(1, "audio", "eng"),
            _td(2, "subtitles", "eng", keep=False),
        ],
    )
    args = _args(plan)
    assert "--no-subtitles" in args
    assert "--subtitle-tracks" not in args


def test_no_stripping_emits_no_track_selection():
    plan = MuxPlan(
        output_name="X.mkv",
        track_decisions=[
            _td(0, "video", "und"),
            _td(1, "audio", "eng"),
            _td(3, "subtitles", "eng"),
        ],
        subtitle_merges=[SubtitleMergeDecision(
            source_relative="Show/a.srt", action="merge",
            language="und", set_default=True)],
    )
    args = _args(plan)
    joined = " ".join(args)
    assert "--audio-tracks" not in joined
    assert "--subtitle-tracks" not in joined
    assert "--no-subtitles" not in joined
    assert "--default-track-flag 0:yes" in joined  # merged sub is default


def test_strip_track_names():
    plan = MuxPlan(
        output_name="X.mkv",
        track_decisions=[
            _td(0, "video", "und", name="x265 rip"),
            _td(1, "audio", "eng", name="Commentary"),
            _td(2, "subtitles", "eng", keep=False, name="drop me"),
        ],
        strip_track_names=True,
    )
    joined = " ".join(_args(plan))
    assert "--track-name 0:" in joined
    assert "--track-name 1:" in joined
    assert "--track-name 2:" not in joined  # stripped track needs no rename


def test_rename_action_subs_are_not_inputs():
    plan = MuxPlan(
        output_name="X.mkv",
        track_decisions=[_td(0, "video", "und"), _td(1, "audio", "eng"),
                         _td(2, "subtitles", "fre", keep=False)],
        subtitle_merges=[SubtitleMergeDecision(
            source_relative="Show/a.spa.srt", action="rename",
            language="spa", set_default=False)],
    )
    args = _args(plan)
    assert not any("a.spa.srt" in a for a in args)


def test_forced_display_flags_emitted():
    plan = MuxPlan(
        output_name="X.mkv",
        track_decisions=[
            _td(0, "video", "und"),
            _td(1, "audio", "eng", default=True),
            _td(2, "subtitles", "eng", forced=True),
            _td(3, "subtitles", "eng", keep=False, forced=True),
        ],
        subtitle_merges=[
            SubtitleMergeDecision(
                source_relative="Show/a.en.forced.srt", action="merge",
                language="eng", set_default=False, forced=True),
            SubtitleMergeDecision(
                source_relative="Show/a.eng.srt", action="merge",
                language="eng", set_default=True, forced=False),
        ],
    )
    args = _args(plan)
    joined = " ".join(args)
    assert "--forced-display-flag 1:no" in joined
    assert "--forced-display-flag 2:yes" in joined
    assert "--forced-display-flag 3:" not in joined  # stripped track
    forced_idx = args.index(str(Path("C:/lib") / "Show/a.en.forced.srt"))
    assert "--forced-display-flag 0:yes" in " ".join(args[:forced_idx])
