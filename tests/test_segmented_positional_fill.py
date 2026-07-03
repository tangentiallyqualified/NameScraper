"""RC31: segmented runs survive duplicate-titled or unknown atoms.

Animaniacs' "H.M.S. Yakko, Slappy Goes Walnuts & Yakko's Universe" failed
because "Yakko's Universe" appears twice in TMDB's season — the whole run
was abandoned, the file fell back to its wrong disc number, lost the
conflict, and vanished.
"""
from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS,
    match_segmented_title_run,
    resolve_file,
)

ANIMANIACS_S1 = {
    1: "De-Zanitized",
    2: "The Monkey Song",
    3: "Nighty-Night Toon",
    7: "H.M.S. Yakko",
    8: "Slappy Goes Walnuts",
    9: "Yakko's Universe",
    135: "Yakko's Universe",  # the song recurs as its own segment episode
}


def test_duplicate_titled_atom_fills_positionally():
    seg = match_segmented_title_run(
        "H.M.S. Yakko, Slappy Goes Walnuts & Yakko's Universe",
        ANIMANIACS_S1,
        3,
    )
    assert seg == ((7, 8, 9), True)


def test_disc_grouped_file_resolves_through_duplicate_title():
    resolution = resolve_file(
        parsed_episodes=(3,),
        raw_title="H.M.S. Yakko, Slappy Goes Walnuts & Yakko's Universe",
        is_season_relative=True,
        season_titles=ANIMANIACS_S1,
        season=1,
    )
    assert resolution.episodes == (7, 8, 9)
    assert resolution.confidence == CONF_TITLE_WINS


def test_zero_overlap_atom_does_not_fill():
    # RC42 tightened RC31's fill: 'Flipper Parody' shares no tokens with
    # 'Garage Sale', so it names some OTHER (unlisted) segment — mapping it
    # onto E12 was the wrong-map behind the Animaniacs E06 cascade. Fills
    # that DO share tokens still land at review
    # (tests/test_positional_fill_overlap.py).
    titles = {
        12: "Garage Sale",
        13: "Temporary Insanity",
        14: "Operation Lollipop",
        15: "What Are We",
    }
    seg = match_segmented_title_run(
        "Flipper Parody, Temporary Insanity & Operation Lollipop", titles, 3,
    )
    assert seg is None


def test_two_unknown_atoms_do_not_fill():
    titles = {13: "Temporary Insanity", 14: "Operation Lollipop", 15: "What Are We"}
    seg = match_segmented_title_run(
        "Aaa Bbb, Ccc Ddd & Operation Lollipop", titles, 3,
    )
    assert seg is None


def test_fully_exact_runs_unchanged():
    titles = {4: "Yakko's World", 5: "Cookies for Einstein", 6: "Win Big"}
    seg = match_segmented_title_run(
        "Yakko's World, Cookies for Einstein & Win Big", titles, 3,
    )
    assert seg == ((4, 5, 6), True)
