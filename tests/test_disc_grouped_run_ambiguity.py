"""RC49: disagreeing disc-grouped run sizes rank by direct title matches.

Animaniacs' "Useless Facts, The Senses, The World Can Wait & Kiki's
Kitten" (file number 44) decomposes at size 4 into E113-E116 with three
groups matching TMDB titles directly, but size 3 ALSO produced E114-E116
by merging the first two atoms and positionally filling the merged group
into E114. Treating those as equal witnesses made the decomposition
"ambiguous", so the file fell back to its disc number and stole slot
S01E44 'The Flame' from the file that actually contains it.
"""
from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    resolve_file,
)

ANIMANIACS_S1 = {
    44: "The Flame",
    45: "Four Score and Seven Migraines Ago",
    112: "Survey Ladies",
    113: "Useless Fact",
    114: "The Senses Song",
    115: "The World Can Wait",
    116: "Kiki's Kitten",
    117: "Mary Tyler Dot Song",
}

RAW = "Useless Facts, The Senses, The World Can Wait & Kiki's Kitten"


def test_more_direct_matches_beats_merged_fill_run():
    resolution = resolve_file(
        parsed_episodes=(44,),
        raw_title=RAW,
        is_season_relative=True,
        season_titles=ANIMANIACS_S1,
        season=1,
        season_hint=1,
    )
    assert resolution.episodes == (113, 114, 115, 116)
    assert "title-segmented" in resolution.evidence
    assert "number" not in resolution.evidence
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT


def test_equally_direct_runs_stay_ambiguous():
    # Size 2 reads the tail as the combined title E06; size 3 reads it as
    # E06 + E07 with 'Beta Two' positionally filled. Both ground two groups
    # in direct title matches -> still ambiguous, keep the number fallback.
    titles = {
        5: "Alpha One",
        6: "Beta Two Gamma Three",
        7: "Gamma Three",
        9: "Something Else",
    }
    resolution = resolve_file(
        parsed_episodes=(9,),
        raw_title="Alpha One, Beta Two & Gamma Three",
        is_season_relative=True,
        season_titles=titles,
        season=1,
        season_hint=1,
    )
    assert resolution.episodes == (9,)
    assert "title-ambiguous" in resolution.evidence
