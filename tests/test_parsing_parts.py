"""Part-marker extraction: trailing (n) / Part n / pt n / CD n / Disc n and
episode-token letter suffixes (S01E05a). Markers must never leak into
episode parsing."""

from __future__ import annotations

import pytest

from plex_renamer._parsing_episodes import extract_episode
from plex_renamer._parsing_parts import split_part_marker


@pytest.mark.parametrize(
    ("stem", "base", "part"),
    [
        ("Show S01E05 (1)", "Show S01E05", 1),
        ("Show S01E05 (2)", "Show S01E05", 2),
        ("Show S01E05 Part 1", "Show S01E05", 1),
        ("Show S01E05 part2", "Show S01E05", 2),
        ("Show S01E05 pt.3", "Show S01E05", 3),
        ("Show S01E05 - Pt 2", "Show S01E05", 2),
        ("Show S01E05 CD1", "Show S01E05", 1),
        ("Show S01E05.disc.2", "Show S01E05", 2),
        ("Show S01E05a", "Show S01E05", 1),
        ("Show S01E05b", "Show S01E05", 2),
    ],
)
def test_marker_forms(stem: str, base: str, part: int) -> None:
    assert split_part_marker(stem) == (base, part)


@pytest.mark.parametrize(
    "stem",
    [
        "Show S01E05",  # no marker
        "Show S01E05 (1998)",  # year, not a part
        "Show S01E05 (13)",  # beyond the part cap
        "Show S01E05 Part 0",  # parts are 1-based
        "Se7en",  # embedded digit, no marker shape
        "Show S01E05v2",  # version tag, not a letter marker
    ],
)
def test_non_markers_pass_through(stem: str) -> None:
    assert split_part_marker(stem) == (stem, None)


def test_letter_marker_requires_episode_token() -> None:
    # A trailing letter NOT attached to S##E## is a title word, not a marker.
    assert split_part_marker("Anime - 05a") == ("Anime - 05a", None)


@pytest.mark.parametrize(
    ("filename", "episodes"),
    [
        ("Show S01E05 (2).mkv", [5]),
        ("Show S01E05 Part 2.mkv", [5]),
        ("Show - 05 (2).mkv", [5]),
        ("Show S01E05b.mkv", [5]),
    ],
)
def test_extract_episode_is_marker_blind(filename: str, episodes: list[int]) -> None:
    parsed, _title, _rel = extract_episode(filename)
    assert parsed == episodes
