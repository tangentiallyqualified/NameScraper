"""Tests for multi-episode TV filename formatting in ``build_tv_name``.

Protects range rendering, shared-title collapsing, distinct-title joining,
and the filename-length cap while preserving episode markers.
"""

from __future__ import annotations

import pytest

from plex_renamer.parsing import build_tv_name

AVATAR_TITLES = [
    "Sozin's Comet - The Phoenix King (1)",
    "Sozin's Comet - The Old Masters (2)",
    "Sozin's Comet - Into the Inferno (3)",
    "Sozin's Comet - Avatar Aang (4)",
]


# ── Part 1: episode-range collapse ──────────────────────────────────

@pytest.mark.parametrize(
    "episodes, expected_marker",
    [
        ([1], "E01"),
        ([1, 2], "E01-E02"),
        ([1, 2, 3], "E01-E03"),
        ([18, 19, 20, 21], "E18-E21"),
    ],
)
def test_contiguous_runs_collapse_to_range(episodes, expected_marker):
    name = build_tv_name("Show", "2005", 3, episodes, ["T"] * len(episodes), ".mkv")
    assert f"S03{expected_marker}" in name


def test_noncontiguous_run_renders_each_episode_explicitly():
    # Guarded upstream, but build_tv_name must not invent a misleading range.
    name = build_tv_name("Show", "2005", 1, [3, 5], ["A", "B"], ".mkv")
    assert "S01E03-E05" in name  # join of E03 + E05 (not a 3-4-5 range claim)


# ── Part 2: title common-base collapse ──────────────────────────────

def test_avatar_filename_form_collapses_to_common_base():
    name = build_tv_name(
        "Avatar - The Last Airbender", "2005", 3, [18, 19, 20, 21],
        AVATAR_TITLES, ".mkv",
    )
    assert name == (
        "Avatar - The Last Airbender (2005) - S03E18-E21 - Sozin's Comet.mkv"
    )


def test_tmdb_part_form_collapses_to_common_base():
    titles = [
        "Sozin's Comet, Part 1: The Phoenix King",
        "Sozin's Comet, Part 2: The Old Masters",
        "Sozin's Comet, Part 3: Into the Inferno",
        "Sozin's Comet, Part 4: Avatar Aang",
    ]
    name = build_tv_name("Avatar", "2005", 3, [18, 19, 20, 21], titles, ".mkv")
    assert "S03E18-E21 - Sozin's Comet.mkv" in name


def test_distinct_short_titles_are_left_joined():
    name = build_tv_name(
        "CatDog", "1998", 1, [1, 2], ["Dog Gone", "All You Can't Eat"], ".mp4",
    )
    assert name == "CatDog (1998) - S01E01-E02 - Dog Gone-All You Can't Eat.mp4"


def test_unrelated_titles_do_not_produce_spurious_base():
    name = build_tv_name("Show", "2000", 1, [1, 2], ["Alpha", "Beta"], ".mkv")
    assert "S01E01-E02 - Alpha-Beta.mkv" in name


def test_single_episode_title_unchanged():
    name = build_tv_name("Show", "2000", 1, [5], ["Gun Fever"], ".mkv")
    assert name == "Show (2000) - S01E05 - Gun Fever.mkv"


# ── Part 3: 170-char length cap ─────────────────────────────────────

def test_long_distinct_titles_capped_with_ellipsis():
    titles = [
        "Alpha the First Very Long Episode Title Goes Here And More",
        "Bravo Another Considerably Long Episode Title Indeed For Sure",
        "Charlie Yet One More Lengthy Episode Title To Add On Top",
    ]
    name = build_tv_name("Some Show", "2001", 1, [5, 6, 7], titles, ".mkv")
    assert len(name) <= 170
    assert name.endswith("….mkv")  # truncated with an ellipsis
    assert name.startswith("Some Show (2001) - S01E05-E07 - ")  # marker preserved


def test_short_name_not_capped():
    name = build_tv_name("Show", "2000", 1, [1], ["Pilot"], ".mkv")
    assert len(name) <= 170
    assert "…" not in name
