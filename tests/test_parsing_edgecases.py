"""Edge-case parsing tests grounded in real download-directory filenames.

Covers three hardening areas (see
docs/superpowers/specs/2026-06-29-episode-parsing-edgecase-hardening-design.md):

  Item 1 - bracketed [NN] fansub episode numbers
  Item 2 - numeric-in-title false-positive guards
  Item 3 - file-vs-TMDB season mismatch (scanner-level regression tests)

All offline and deterministic (no TMDB / network).
"""

from __future__ import annotations

import pytest

from plex_renamer.parsing import (
    extract_episode,
    extract_source_title_prefix,
    extract_year,
    looks_like_tv_episode,
)
from pathlib import Path


# ── Year hints from run-range folder names ──────────────────────────

@pytest.mark.parametrize(
    "name, expected",
    [
        # A YYYY-YYYY run range names the show's whole run; TMDB indexes by
        # FIRST-AIR year, so the hint must be the range START. (Jimmy Neutron
        # matched "Rich, Jimmy & Kait's Castle" (2013) via the range end.)
        (
            "JIMMY NEUTRON (2001-2013) - Complete Movie, ANIMATED TV Series,"
            " and Planet Sheen - 576p-1080p x264",
            "2001",
        ),
        ("Specials (1998-2003)", "1998"),
        ("The Wild Thornberries (1998 - 2004)", "1998"),
        # Non-range names keep existing behavior.
        ("The.Matrix.1999.1080p", "1999"),
        ("2001.A.Space.Odyssey.1968.2160p", "1968"),
        ("2001 A Space Odyssey (1968)", "1968"),
        ("Watchmen.S01.2160p.MAX.WEB-DL", None),
    ],
)
def test_extract_year_uses_range_start(name, expected):
    assert extract_year(name) == expected


# ── Item 1: bracketed [NN] episode numbers ──────────────────────────

@pytest.mark.parametrize(
    "name, expected_episode",
    [
        ("[DBD-Raws][Wolf's Rain][01][1080P][BDRip][HEVC-10bit][FLACx2].mkv", 1),
        ("[DBD-Raws][Wolf's Rain][09][1080P][BDRip][HEVC-10bit][FLACx2].mkv", 9),
        ("[DBD-Raws][Wolf's Rain][30][1080P][BDRip][HEVC-10bit][FLACx2].mkv", 30),
    ],
)
def test_extract_episode_recognizes_bracketed_episode_number(name, expected_episode):
    episodes, title, is_season_relative = extract_episode(name)
    assert episodes == [expected_episode]
    # absolute numbering (anime convention) -> not season-relative
    assert is_season_relative is False


@pytest.mark.parametrize(
    "name",
    [
        # resolution / quality / version / hash / year brackets must NOT be
        # mistaken for an episode number.
        "[Group][Show][1080P][BDRip][HEVC-10bit].mkv",
        "[Group][Show][480p][x265].mkv",
        "[Group][Show][v2][HEVC-10bit].mkv",
        "[Group][Show][B36160B7].mkv",
        "[Group][Show][2006][BDRip].mkv",
    ],
)
def test_extract_episode_ignores_non_episode_brackets(name):
    episodes, _title, _rel = extract_episode(name)
    assert episodes == []


def test_extract_episode_bracket_does_not_override_explicit_sxxeyy():
    # An explicit S##E## still wins; the bracket fallback must not fire.
    episodes, _title, is_season_relative = extract_episode(
        "Show S02E05 [720p].mkv"
    )
    assert episodes == [5]
    assert is_season_relative is True


def test_looks_like_tv_episode_recognizes_fansub_bracket_files():
    path = Path(
        "[DBD-Raws][Wolf's Rain][01][1080P][BDRip][HEVC-10bit][FLACx2].mkv"
    )
    assert looks_like_tv_episode(path) is True


def test_extract_source_title_prefix_reads_bracket_show_title():
    name = "[DBD-Raws][Wolf's Rain][01][1080P][BDRip][HEVC-10bit][FLACx2].mkv"
    assert extract_source_title_prefix(name) == "Wolf's Rain"


# ── Item 2: numeric-in-title false-positive guards ──────────────────

@pytest.mark.parametrize(
    "name",
    [
        # digit embedded in letters
        "Se7en.mkv",
        # "No.6" is the volume/number "Number 6", not episode 6
        "[CBM]_Blue_Submarine_No.6_(Toonami_Version)_[v2]_[H.265_10bit]_[B36160B7].mkv",
        "[CBM]_Blue_Submarine_No.6_Toonami_Promo_(30_seconds)_[v2]_[H.265_10bit]_[638719A5].mkv",
        # "3D" must not yield phantom episode 3 (real Futurama featurette names)
        "Futurama University - 3D Modeling.mkv",
        "3D Models With Animator Discussion.mkv",
        # "Part 1" is a part label, not an episode number
        "Storyboard Animatic Into the Wild Green Yonder, Part 1.mkv",
    ],
)
def test_extract_episode_rejects_numeric_in_title(name):
    episodes, _title, _rel = extract_episode(name)
    assert episodes == []


@pytest.mark.parametrize(
    "name, expected",
    [
        # legit anime absolute numbering must still parse
        ("[Kawaiika-Raws] Bartender 02 [BDRip 1920x1080 HEVC FLAC].mkv", [2]),
        ("[Kawaiika-Raws] Bartender 11 [BDRip 1920x1080 HEVC FLAC].mkv", [11]),
        # dash-delimited episode + title still parses
        ("Mobile Suit Gundam - 0083 Stardust Memory - 05 - Title.mkv", [5]),
    ],
)
def test_extract_episode_keeps_legit_bare_numbers(name, expected):
    episodes, _title, _rel = extract_episode(name)
    assert episodes == expected


# ── Item 3: file-vs-TMDB season mismatch (regression locks) ─────────
#
# Investigation (live-TMDB harness over the real corpus) confirmed the engine
# already handles these correctly: a bogus file-level S## is ignored in favor
# of the folder season + episode/title, and genuinely unreliable numbering is
# routed to REVIEW/rescue rather than silently mis-assigned. These tests lock
# that behavior in offline (synthetic titles), so a future change can't
# regress it. No production code changes for Item 3.

def _make_table_with_slots(slots):
    from plex_renamer.engine.episode_assignments import (
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for season, episode, title in slots:
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))
    return table


def test_wrong_file_season_marker_resolves_against_folder_season():
    """`Animaniacs (2020)/Season 1/...S06E01 - Jurassic Lark` -> S1E1 at high
    confidence; the bogus S06 marker is ignored (folder season + title win)."""
    from plex_renamer.engine._tv_scanner_normal import _resolve_into_table

    season_titles = {1: "Jurassic Lark", 2: "Suspended Animation"}
    table = _make_table_with_slots(
        [(1, 1, "Jurassic Lark"), (1, 2, "Suspended Animation")]
    )
    _resolve_into_table(
        table,
        file_path=Path("Animaniacs (1993) - S06E01 - Jurassic Lark.mkv"),
        season_num=1,
        season_titles=season_titles,
    )
    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 1
    assert assignment.episodes == (1,)
    assert assignment.confidence >= 0.9  # rule-1 number+title agreement


def test_cross_season_title_rescue_holds_review_confidence():
    """A `Season 1` folder file whose real episode is in Season 2 (As Told By
    Ginger style) is rescued by exact title to S2 but held at REVIEW
    confidence because the source numbering is known-bad."""
    from plex_renamer.engine._episode_resolution import (
        CONF_TITLE_WINS_INEXACT,
        rescue_cross_season_titles,
    )
    from plex_renamer.engine._tv_scanner_normal import _resolve_into_table

    season_titles = {ep: f"S1 Ep {ep}" for ep in range(1, 17)}
    slots = [(1, ep, f"S1 Ep {ep}") for ep in range(1, 17)]
    slots.append((2, 1, "I Spy a Witch"))
    table = _make_table_with_slots(slots)

    _resolve_into_table(
        table,
        file_path=Path("As Told By Ginger - S01E17 - I Spy a Witch.mkv"),
        season_num=1,
        season_titles=season_titles,
    )
    rescue_cross_season_titles(table)

    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 2
    assert assignment.episodes == (1,)
    # Held at review confidence (known-bad source numbering).
    assert assignment.confidence <= CONF_TITLE_WINS_INEXACT
