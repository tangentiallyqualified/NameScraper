"""RC20(2): bounded fuzzy matching for titles and segmented-run atoms."""
from plex_renamer.engine._episode_resolution import (
    _TITLE_NEAR_EXACT,
    CONF_AGREE,
    CONF_TITLE_WINS_INEXACT,
    match_segmented_title_run,
    match_title_in_titles,
    resolve_file,
)


def test_single_typo_fuzzy_match():
    titles = {37: "Neferkitty", 38: "Curiosity Almost Killed The Cat"}
    match = match_title_in_titles("Curiousity Almost Killed The Cat", titles)
    assert match is not None
    assert match.episode == 38
    # A unique typo-level hit ranks near-exact since RC46.
    assert match.strength == _TITLE_NEAR_EXACT


def test_token_prefix_fuzzy_match():
    titles = {10: "Friendship Alliance", 11: "Vice Mayor"}
    match = match_title_in_titles("Friend Alliance", titles)
    assert match is not None and match.episode == 10


def test_token_reorder_with_part_words():
    titles = {5: "Tokyo Colony No. 1 (3)", 6: "Tokyo Colony No. 1 (4)"}
    match = match_title_in_titles("Tokyo No 1 Colony Part 3", titles)
    assert match is not None and match.episode == 5


def test_ambiguous_fuzzy_returns_none():
    titles = {1: "The Cat", 2: "The Bat"}
    assert match_title_in_titles("The Hat", titles) is None


def test_segmented_run_with_fuzzy_atom():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse", 3: "Unicorn Club"}
    seg = match_segmented_title_run(
        "To The Moon & Bringin' Down The Mouse", titles, 2,
    )
    assert seg is not None
    run, all_exact = seg
    assert run == (1, 2)
    assert all_exact is False


def test_segmented_run_exact_flag_true():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse"}
    seg = match_segmented_title_run("To the Moon & Bringing Down the Mouse", titles, 2)
    assert seg == ((1, 2), True)


def test_resolve_file_fuzzy_run_is_review():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse", 3: "Unicorn Club", 4: "Go Gomez Go"}
    resolution = resolve_file(
        parsed_episodes=(1,),
        raw_title="To The Moon & Bringin' Down The Mouse",
        is_season_relative=True,
        season_titles=titles,
        season=1,
    )
    assert resolution.episodes == (1, 2)
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT
    assert "title-fuzzy" in resolution.evidence
