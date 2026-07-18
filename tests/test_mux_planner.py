"""Pure mux-planning rules (spec §5)."""
from plex_renamer._mkv_probe import MediaTrack, ProbeResult
from plex_renamer.engine._mux_planner import (
    MuxPlan,
    MuxSettings,
    build_mux_plan,
)


def _track(tid, ttype, lang, *, default=False, forced=False, name="", codec="c"):
    return MediaTrack(
        track_id=tid, track_type=ttype, codec=codec, language=lang,
        name=name, is_default=default, is_forced=forced)


def _probe(*tracks):
    return ProbeResult(path="X.mkv", ok=True, tracks=list(tracks))


BASIC = _probe(
    _track(0, "video", "und"),
    _track(1, "audio", "eng", default=True),
    _track(2, "audio", "jpn"),
    _track(3, "subtitles", "eng"),
    _track(4, "subtitles", "fre"),
)


def test_no_toggles_no_plan():
    plan = build_mux_plan(
        probe=BASIC, companion_subs=[], settings=MuxSettings(),
        new_name="Show - S01E01 - Pilot.mkv")
    assert plan is None


def test_strip_subs_keeps_retained_and_und():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "eng"),
        _track(3, "subtitles", "fre"),
        _track(4, "subtitles", "und"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["en"]),
        new_name="X.mkv")
    keep = {d.track_id: d.keep for d in plan.track_decisions}
    assert keep == {0: True, 1: True, 2: True, 3: False, 4: True}


def test_audio_safety_floor():
    plan = build_mux_plan(
        probe=BASIC, companion_subs=[],
        settings=MuxSettings(
            strip_audio=True, retain_audio_languages=["kor"],
            strip_subs=True, retain_sub_languages=["eng"]),
        new_name="X.mkv")
    audio = [d for d in plan.track_decisions if d.track_type == "audio"]
    assert all(d.keep for d in audio)
    assert any("every audio track" in w for w in plan.warnings)


def test_all_audio_stripped_no_subs_stripped_still_none_when_no_actions():
    # strip toggles on but everything retained + no merges → no remux.
    plan = build_mux_plan(
        probe=BASIC, companion_subs=[],
        settings=MuxSettings(
            strip_subs=True, retain_sub_languages=["eng", "fre"],
            strip_audio=True, retain_audio_languages=["eng", "jpn"]),
        new_name="X.mkv")
    assert plan is None


def test_merge_listed_language_and_rename_unlisted():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[
            ("Show/S01E01.eng.srt", ".eng"),
            ("Show/S01E01.spa.srt", ".spa"),
        ],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"]),
        new_name="X.mkv")
    actions = {m.source_relative: m.action for m in plan.subtitle_merges}
    assert actions["Show/S01E01.eng.srt"] == "merge"
    assert actions["Show/S01E01.spa.srt"] == "rename"


def test_untagged_sub_merges_with_substitute_language():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[("Show/S01E01.srt", "")],
        settings=MuxSettings(
            merge_subs=True, merge_sub_languages=["eng"],
            untagged_sub_language="en"),
        new_name="X.mkv")
    merged = plan.subtitle_merges[0]
    assert merged.action == "merge"
    assert merged.language == "eng"


def test_untagged_sub_merges_as_und_without_substitute():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[("Show/S01E01.srt", "")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"]),
        new_name="X.mkv")
    assert plan.subtitle_merges[0].action == "merge"
    assert plan.subtitle_merges[0].language == "und"


def test_merge_priority_order():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[
            ("a.jpn.srt", ".jpn"),
            ("a.eng.srt", ".eng"),
        ],
        settings=MuxSettings(
            merge_subs=True, merge_sub_languages=["eng", "jpn"]),
        new_name="X.mkv")
    merged = [m for m in plan.subtitle_merges if m.action == "merge"]
    assert [m.language for m in merged] == ["eng", "jpn"]


def test_default_flags():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[("a.eng.srt", ".eng")],
        settings=MuxSettings(
            merge_subs=True, merge_sub_languages=["eng"],
            default_sub_language="eng", default_audio_language="jpn",
            strip_audio=True, retain_audio_languages=["eng", "jpn"],
            strip_subs=True, retain_sub_languages=["eng", "fre"]),
        new_name="X.mkv")
    audio_defaults = {
        d.track_id: d.make_default
        for d in plan.track_decisions if d.track_type == "audio"}
    assert audio_defaults == {1: False, 2: True}
    # Merged eng sub takes the default flag; embedded subs are demoted.
    assert plan.subtitle_merges[0].set_default is True
    sub_defaults = [
        d.make_default for d in plan.track_decisions
        if d.track_type == "subtitles" and d.keep]
    assert sub_defaults == [False, False]


def test_output_name_forced_to_mkv():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[("a.eng.srt", ".eng")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"]),
        new_name="Show - S01E01 - Pilot.mp4")
    assert plan.output_name == "Show - S01E01 - Pilot.mkv"


def test_failed_probe_returns_none():
    bad = ProbeResult(path="X.avi", ok=False, error="boom")
    plan = build_mux_plan(
        probe=bad, companion_subs=[("a.eng.srt", ".eng")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"]),
        new_name="X.mkv")
    assert plan is None


def test_plan_round_trips_through_dict():
    plan = build_mux_plan(
        probe=BASIC,
        companion_subs=[("a.eng.srt", ".eng")],
        settings=MuxSettings(
            merge_subs=True, merge_sub_languages=["eng"], no_fear=True),
        new_name="X.mkv", mkvmerge_path="C:/t/mkvmerge.exe")
    restored = MuxPlan.from_dict(plan.to_dict())
    assert restored == plan
    assert restored.no_fear is True
    assert restored.mkvmerge_path == "C:/t/mkvmerge.exe"


def test_decisions_carry_forced_and_commentary_metadata():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng", name="Director Commentary"),
        _track(2, "subtitles", "eng", forced=True),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[("a.eng.srt", ".eng")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"]),
        new_name="X.mkv")
    assert plan is not None
    by_id = {d.track_id: d for d in plan.track_decisions}
    assert by_id[1].is_commentary is True
    assert by_id[1].is_forced is False
    assert by_id[2].is_forced is True
    assert by_id[2].is_commentary is False


def test_from_dict_accepts_legacy_plan_without_new_keys():
    # Plans serialized before the forced/commentary fields existed
    # (baked queue jobs) must still deserialize with default values.
    legacy = {
        "output_name": "X.mkv",
        "track_decisions": [{
            "track_id": 1, "track_type": "audio", "codec": "c",
            "language": "eng", "name": "", "keep": True,
            "make_default": True, "reason": "retained"}],
        "subtitle_merges": [{
            "source_relative": "a.eng.srt", "action": "merge",
            "language": "eng", "set_default": False}],
    }
    plan = MuxPlan.from_dict(legacy)
    assert plan.track_decisions[0].is_forced is False
    assert plan.track_decisions[0].is_commentary is False
    assert plan.subtitle_merges[0].forced is False


def test_default_sub_prefers_full_over_forced():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "eng", forced=True, default=True),
        _track(3, "subtitles", "eng"),
        _track(4, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"],
                             default_sub_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    defaults = {d.track_id: d.make_default for d in plan.track_decisions
                if d.track_type == "subtitles"}
    assert defaults[2] is False
    assert defaults[3] is True


def test_default_audio_prefers_full_over_forced():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng", forced=True, default=True),
        _track(2, "audio", "eng"),
        _track(3, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"],
                             default_audio_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    defaults = {d.track_id: d.make_default for d in plan.track_decisions
                if d.track_type == "audio"}
    assert defaults == {1: False, 2: True}


def test_forced_only_match_still_gets_default():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "eng", forced=True),
        _track(3, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"],
                             default_sub_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    defaults = {d.track_id: d.make_default for d in plan.track_decisions
                if d.track_type == "subtitles"}
    assert defaults[2] is True


def test_default_audio_skips_commentary():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng", name="Commentary with director", default=True),
        _track(2, "audio", "eng"),
        _track(3, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"],
                             default_audio_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    defaults = {d.track_id: d.make_default for d in plan.track_decisions
                if d.track_type == "audio"}
    assert defaults == {1: False, 2: True}


def test_only_commentary_match_leaves_flags_untouched():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng", name="Commentary", default=True),
        _track(2, "audio", "jpn"),
        _track(3, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"],
                             default_audio_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    defaults = {d.track_id: d.make_default for d in plan.track_decisions
                if d.track_type == "audio"}
    assert defaults == {1: True, 2: False}


def test_forced_companion_gets_flag_but_not_default():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "eng"),
    )
    plan = build_mux_plan(
        probe=probe,
        companion_subs=[("a.en.forced.srt", ".en.forced")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"],
                             default_sub_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    merge = plan.subtitle_merges[0]
    assert merge.action == "merge"
    assert merge.forced is True
    assert merge.set_default is False
    defaults = {d.track_id: d.make_default for d in plan.track_decisions
                if d.track_type == "subtitles"}
    assert defaults == {2: True}


def test_forced_companion_default_when_only_match():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe,
        companion_subs=[("a.en.forced.srt", ".en.forced")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"],
                             default_sub_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    assert plan.subtitle_merges[0].forced is True
    assert plan.subtitle_merges[0].set_default is True


def test_full_merge_beats_forced_merge_for_default():
    probe = _probe(_track(0, "video", "und"), _track(1, "audio", "eng"))
    plan = build_mux_plan(
        probe=probe,
        companion_subs=[
            ("a.en.forced.srt", ".en.forced"),
            ("a.eng.srt", ".eng"),
        ],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"],
                             default_sub_language="eng"),
        new_name="X.mkv")
    assert plan is not None
    by_src = {m.source_relative: m for m in plan.subtitle_merges}
    assert by_src["a.eng.srt"].set_default is True
    assert by_src["a.en.forced.srt"].set_default is False


def test_commentary_excluded_when_stripping():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "eng"),
        _track(3, "subtitles", "eng", name="Commentary"),
        _track(4, "subtitles", "und", name="commentary track"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"],
                             exclude_commentary=True),
        new_name="X.mkv")
    assert plan is not None
    keep = {d.track_id: d.keep for d in plan.track_decisions}
    assert keep == {0: True, 1: True, 2: True, 3: False, 4: False}
    reasons = {d.track_id: d.reason for d in plan.track_decisions}
    assert reasons[3] == "commentary excluded"


def test_commentary_kept_when_toggle_or_strip_off():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng"),
        _track(2, "subtitles", "eng", name="Commentary"),
        _track(3, "subtitles", "fre"),
    )
    # Toggle off: commentary in a retained language stays.
    toggle_off = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_subs=True, retain_sub_languages=["eng"]),
        new_name="X.mkv")
    assert toggle_off is not None
    assert {d.track_id: d.keep for d in toggle_off.track_decisions}[2] is True
    # Strip off: the toggle alone does nothing (refinement only).
    strip_off = build_mux_plan(
        probe=probe,
        companion_subs=[("a.eng.srt", ".eng")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["eng"],
                             exclude_commentary=True),
        new_name="X.mkv")
    assert strip_off is not None
    assert {d.track_id: d.keep for d in strip_off.track_decisions}[2] is True


def test_commentary_exclusion_respects_audio_floor():
    probe = _probe(
        _track(0, "video", "und"),
        _track(1, "audio", "eng", name="Commentary"),
        _track(2, "subtitles", "fre"),
    )
    plan = build_mux_plan(
        probe=probe, companion_subs=[],
        settings=MuxSettings(strip_audio=True, retain_audio_languages=["eng"],
                             exclude_commentary=True,
                             strip_subs=True, retain_sub_languages=["eng"]),
        new_name="X.mkv")
    assert plan is not None
    audio = [d for d in plan.track_decisions if d.track_type == "audio"]
    assert all(d.keep for d in audio)
    assert any("every audio track" in w for w in plan.warnings)
