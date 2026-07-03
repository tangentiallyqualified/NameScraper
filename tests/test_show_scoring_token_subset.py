"""RC37: a token-subset query must not lose to a prefix-sharing stranger.

'jimmy neutron' is fully contained in 'The Adventures of Jimmy Neutron: Boy
Genius' but the substring branch scored it len(short)/len(long) = 0.33 while
char-LCS gave 'Jimmy Kimmel Live!' ~0.67 for sharing 'jimmy '.
"""
from plex_renamer.engine.matching import score_results, title_similarity


def test_token_subset_similarity_is_strong():
    score = title_similarity(
        "jimmy neutron", "adventures of jimmy neutron boy genius"
    )
    assert score >= 0.7


def test_token_subset_beats_shared_prefix():
    results = [
        {"id": 1489, "name": "Jimmy Kimmel Live!", "year": "2003"},
        {
            "id": 2129,
            "name": "The Adventures of Jimmy Neutron: Boy Genius",
            "year": "2002",
        },
    ]
    scored = score_results(results, "JIMMY NEUTRON (2001)", "2001", title_key="name")
    assert scored[0][0]["id"] == 2129


def test_exact_match_still_scores_one():
    assert title_similarity("limitless", "limitless") == 1.0


def test_unrelated_titles_still_low():
    assert title_similarity("jimmy neutron", "breaking bad") < 0.4


def test_single_token_prefix_keeps_proportional_score():
    # 'daybreak' vs 'daybreakers' is a char substring, not a token subset —
    # it keeps the pre-existing proportional substring score (8/11).
    assert title_similarity("daybreak", "daybreakers") == len("daybreak") / len(
        "daybreakers"
    )
