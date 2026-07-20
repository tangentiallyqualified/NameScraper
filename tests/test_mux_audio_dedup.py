"""Audio dedup: effective-quality selection among same-language tracks."""

from plex_renamer._mkv_probe import MediaTrack
from plex_renamer.engine._mux_audio_dedup import dedupe_audio_decisions
from plex_renamer.engine._mux_models import MuxSettings, TrackDecision


def _track(
    track_id: int,
    codec: str,
    lang: str = "eng",
    channels: int = 6,
    kbps: int = 640,
    name: str = "",
) -> tuple[MediaTrack, TrackDecision]:
    media = MediaTrack(
        track_id=track_id,
        track_type="audio",
        codec=codec,
        language=lang,
        name=name,
        is_default=False,
        is_forced=False,
        channels=channels,
        bitrate_bps=kbps * 1000,
    )
    decision = TrackDecision(
        track_id=track_id,
        track_type="audio",
        codec=codec,
        language=lang,
        name=name,
        keep=True,
        make_default=False,
        reason="stripping disabled",
    )
    return media, decision


def _run(pairs: list[tuple[MediaTrack, TrackDecision]], **overrides: object) -> list[str]:
    settings = MuxSettings(dedupe_audio=True, **overrides)  # type: ignore[arg-type]
    decisions = [d for _, d in pairs]
    tracks = {m.track_id: m for m, _ in pairs}
    return dedupe_audio_decisions(decisions, tracks, settings)


def kept(pairs: list[tuple[MediaTrack, TrackDecision]]) -> set[int]:
    return {d.track_id for _, d in pairs if d.keep}


def test_motivating_pair_eac3_beats_starved_opus() -> None:
    # eac3 6ch 2000kbps: effective 2000*1.3=2600, per-ch 433.3 -> transparent
    # opus 6ch 700kbps: effective 700*2.0=1400, per-ch 233.3 -> transparent
    # Both transparent -> tie preference decides -> smaller bitrate wins.
    eac3 = _track(1, "eac3", channels=6, kbps=2000)
    opus = _track(2, "opus", channels=6, kbps=700)

    pairs_prefer_smaller = [eac3, opus]
    warnings = _run(pairs_prefer_smaller, tie_prefer_smaller=True)
    assert kept(pairs_prefer_smaller) == {2}  # opus (smaller bitrate) kept
    assert warnings == []

    eac3b = _track(1, "eac3", channels=6, kbps=2000)
    opusb = _track(2, "opus", channels=6, kbps=700)
    pairs_prefer_higher = [eac3b, opusb]
    warnings = _run(pairs_prefer_higher, tie_prefer_smaller=False)
    assert kept(pairs_prefer_higher) == {1}  # eac3 (higher effective) kept
    assert warnings == []


def test_motivating_pair_below_ceiling() -> None:
    # eac3 2ch 192kbps: effective 249.6, per-ch 124.8 -> not transparent
    # opus 2ch 64kbps: effective 128.0, per-ch 64.0 -> not transparent
    # gap (249.6-128)/249.6 = 48.7% > 15% tolerance -> eac3 wins outright.
    eac3 = _track(1, "eac3", channels=2, kbps=192)
    opus = _track(2, "opus", channels=2, kbps=64)
    pairs = [eac3, opus]
    warnings = _run(pairs)
    assert kept(pairs) == {1}
    assert warnings == []


def test_opus_wins_when_well_fed_below_ceiling() -> None:
    # opus 6ch 450kbps: effective 900, per-ch 150 -> not transparent
    # ac3 6ch 640kbps: effective 640, per-ch 106.7 -> not transparent
    # gap (900-640)/900 = 28.9% > 15% tolerance -> opus wins outright.
    opus = _track(1, "opus", channels=6, kbps=450)
    ac3 = _track(2, "ac3", channels=6, kbps=640)
    pairs = [opus, ac3]
    warnings = _run(pairs)
    assert kept(pairs) == {1}
    assert warnings == []


def test_tie_band_prefers_smaller_or_quality() -> None:
    # Same codec (ac3) so effective is proportional to bitrate.
    # ac3 6ch 640kbps: effective 640, per-ch 106.7 -> not transparent
    # ac3 6ch 600kbps: effective 600, per-ch 100.0 -> not transparent
    # gap (640-600)/640 = 6.25% <= 15% tolerance -> tie band.
    high = _track(1, "ac3", channels=6, kbps=640)
    low = _track(2, "ac3", channels=6, kbps=600)
    pairs_smaller = [high, low]
    warnings = _run(pairs_smaller, tie_prefer_smaller=True)
    assert kept(pairs_smaller) == {2}  # smaller bitrate kept
    assert warnings == []

    high_b = _track(1, "ac3", channels=6, kbps=640)
    low_b = _track(2, "ac3", channels=6, kbps=600)
    pairs_higher = [high_b, low_b]
    warnings = _run(pairs_higher, tie_prefer_smaller=False)
    assert kept(pairs_higher) == {1}  # higher effective kept
    assert warnings == []


def test_channels_dominate_single_best() -> None:
    truehd = _track(1, "truehd", channels=8, kbps=0)
    eac3 = _track(2, "eac3", channels=6, kbps=640)
    aac = _track(3, "aac", channels=2, kbps=192)
    pairs = [truehd, eac3, aac]
    warnings = _run(pairs, dedupe_keep_per_layout=False)
    assert kept(pairs) == {1}
    assert warnings == []


def test_keep_per_layout_keeps_one_per_channel_count() -> None:
    truehd = _track(1, "truehd", channels=8, kbps=0)
    eac3 = _track(2, "eac3", channels=6, kbps=640)
    ac3 = _track(3, "ac3", channels=6, kbps=640)
    aac = _track(4, "aac", channels=2, kbps=192)
    pairs = [truehd, eac3, ac3, aac]
    warnings = _run(pairs, dedupe_keep_per_layout=True)
    assert kept(pairs) == {1, 2, 4}
    assert warnings == []


def test_lossless_quality_policy_wins_its_group() -> None:
    truehd = _track(1, "truehd", channels=6, kbps=0)
    eac3 = _track(2, "eac3", channels=6, kbps=640)
    pairs = [truehd, eac3]
    warnings = _run(pairs, lossless_policy="quality")
    assert kept(pairs) == {1}
    assert warnings == []


def test_lossless_space_policy_drops_lossless_across_layouts() -> None:
    # eac3 6ch 1536kbps: effective 1996.8, per-ch 332.8 -> transparent
    truehd = _track(1, "truehd", channels=8, kbps=0)
    eac3 = _track(2, "eac3", channels=6, kbps=1536)
    pairs = [truehd, eac3]
    warnings = _run(pairs, lossless_policy="space")
    assert kept(pairs) == {2}
    assert warnings == []


def test_lossless_space_policy_keeps_lossless_without_transparent_lossy() -> None:
    # mp3 2ch 128kbps: effective 140.8, per-ch 70.4 -> not transparent
    truehd = _track(1, "truehd", channels=8, kbps=0)
    mp3 = _track(2, "mp3", channels=2, kbps=128)
    pairs = [truehd, mp3]
    warnings = _run(pairs, lossless_policy="space")
    assert 1 in kept(pairs)
    assert warnings == []


def test_und_commentary_descriptive_exempt() -> None:
    und_media, und_decision = _track(1, "ac3", lang="und", channels=6, kbps=640)
    commentary_media, commentary_decision = _track(2, "ac3", lang="eng", channels=6, kbps=640)
    commentary_decision.is_commentary = True
    descriptive_media, descriptive_decision = _track(
        3, "ac3", lang="eng", channels=6, kbps=640, name="English Descriptive Audio"
    )
    pairs = [
        (und_media, und_decision),
        (commentary_media, commentary_decision),
        (descriptive_media, descriptive_decision),
    ]
    warnings = _run(pairs)
    assert kept(pairs) == {1, 2, 3}
    assert warnings == []


def test_unknown_bitrate_exempts_group_with_warning() -> None:
    known = _track(1, "ac3", channels=6, kbps=640)
    unknown = _track(2, "ac3", channels=6, kbps=0)
    pairs = [known, unknown]
    warnings = _run(pairs)
    assert kept(pairs) == {1, 2}
    assert len(warnings) == 1
    assert "2" in warnings[0]


def test_unknown_channels_exempts_group() -> None:
    known = _track(1, "ac3", channels=6, kbps=640)
    unknown = _track(2, "ac3", channels=0, kbps=640)
    pairs = [known, unknown]
    warnings = _run(pairs)
    assert kept(pairs) == {1, 2}
    assert len(warnings) == 1


def test_single_track_language_untouched() -> None:
    solo = _track(1, "eac3", channels=6, kbps=640)
    pairs = [solo]
    warnings = _run(pairs)
    assert kept(pairs) == {1}
    assert warnings == []


def test_default_flag_promoted_to_survivor_when_dropped() -> None:
    # ac3 6ch 400kbps carries the source's default flag but loses the
    # dedup vote outright (gap 51.9% > 15% tolerance, see
    # test_drop_reasons_are_explanatory); the flag must land on the
    # surviving eac3 track rather than vanish with the dropped one.
    ac3_media, ac3_decision = _track(1, "ac3", channels=6, kbps=400)
    eac3_media, eac3_decision = _track(2, "eac3", channels=6, kbps=640)
    ac3_decision.make_default = True
    pairs = [(ac3_media, ac3_decision), (eac3_media, eac3_decision)]
    warnings = _run(pairs)
    assert kept(pairs) == {2}
    assert ac3_decision.make_default is True  # untouched on the loser
    assert eac3_decision.make_default is True  # promoted onto the survivor
    assert warnings == []


def test_no_promotion_when_another_kept_track_already_default() -> None:
    # The eng group's default carrier (ac3) is dedup-dropped, but a jpn
    # track elsewhere in the same file already holds the default flag --
    # promoting the eng survivor too would mint a second default track.
    ac3_media, ac3_decision = _track(1, "ac3", lang="eng", channels=6, kbps=400)
    eac3_media, eac3_decision = _track(2, "eac3", lang="eng", channels=6, kbps=640)
    ac3_decision.make_default = True
    jpn_media, jpn_decision = _track(3, "aac", lang="jpn", channels=2, kbps=192)
    jpn_decision.make_default = True
    pairs = [
        (ac3_media, ac3_decision),
        (eac3_media, eac3_decision),
        (jpn_media, jpn_decision),
    ]
    warnings = _run(pairs)
    assert kept(pairs) == {2, 3}
    assert not ac3_decision.keep
    assert eac3_decision.make_default is False  # no promotion
    assert jpn_decision.make_default is True  # left alone
    assert warnings == []


def test_drop_reasons_are_explanatory() -> None:
    # ac3 6ch 400kbps: effective 400, per-ch 66.7 -> not transparent
    # eac3 6ch 640kbps: effective 832, per-ch 138.7 -> not transparent
    # gap (832-400)/832 = 51.9% > 15% tolerance -> eac3 wins outright.
    ac3_media, ac3_decision = _track(1, "ac3", channels=6, kbps=400)
    eac3_media, eac3_decision = _track(2, "eac3", channels=6, kbps=640)
    pairs = [(ac3_media, ac3_decision), (eac3_media, eac3_decision)]
    warnings = _run(pairs)
    assert kept(pairs) == {2}
    assert not ac3_decision.keep
    assert "ac3" in ac3_decision.reason
    assert "eac3" in ac3_decision.reason
    assert "6ch" in ac3_decision.reason
    assert warnings == []
