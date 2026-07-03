"""RC42: a positional fill piece must share tokens with the slot it fills.

'Flipper Parody, Temporary Insanity, Operation Lollipop & What Are We'
holds one segment TMDB does not list (Flipper Parody). At expected=4 the
fill mapped 'Flipper Parody' onto E12 'Taming of the Screwy' (zero token
overlap), producing a second candidate run — the ambiguity killed the
whole decomposition and the file fell back to its bogus number claim.
"""
from plex_renamer.engine._episode_resolution import (
    match_segmented_title_run,
    resolve_file,
)

ANIMANIACS_S1 = {
    6: "Win Big",
    12: "Taming of the Screwy",
    13: "Temporary Insanity",
    14: "Operation: Lollipop",
    15: "What Are We?",
}

RAW = "Flipper Parody, Temporary Insanity, Operation Lollipop & What Are We"


def test_zero_overlap_fill_rejected():
    assert match_segmented_title_run(RAW, ANIMANIACS_S1, 4) is None


def test_containment_fill_survives():
    seg = match_segmented_title_run(RAW, ANIMANIACS_S1, 3)
    assert seg is not None
    assert seg[0] == (13, 14, 15)


def test_unlisted_leading_segment_resolves_to_titled_run():
    resolution = resolve_file(
        parsed_episodes=(6,),
        raw_title=RAW,
        is_season_relative=True,
        season_titles=ANIMANIACS_S1,
        season=1,
        season_hint=1,
    )
    assert resolution.episodes == (13, 14, 15)
    assert "title-segmented" in resolution.evidence
