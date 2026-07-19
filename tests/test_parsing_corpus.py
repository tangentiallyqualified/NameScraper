"""Corpus-driven parsing tests over realistic release names.

Each record in tests/parsing_corpus.py asserts only the keys it carries
(partial expectations). Records with xfail=True document known parser
gaps; strict xfail means a parser fix turns the record into an XPASS
failure, forcing it to be flipped to a real assertion. All offline and
deterministic (no TMDB / network).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parsing_corpus import CORPUS

from plex_renamer.parsing import (
    extract_episode,
    extract_season_number,
    extract_year,
    looks_like_tv_episode,
)


def _params():
    for rec in CORPUS:
        marks = (
            [pytest.mark.xfail(strict=True, reason=rec.get("note", "known parser gap"))]
            if rec.get("xfail")
            else []
        )
        yield pytest.param(rec, marks=marks, id=rec["name"][:70])


@pytest.mark.parametrize("rec", list(_params()))
def test_parsing_corpus(rec):
    name = rec["name"]
    if "episodes" in rec or "ep_title" in rec or "season_relative" in rec:
        episodes, title, relative = extract_episode(name)
        if "episodes" in rec:
            assert episodes == rec["episodes"]
        if "ep_title" in rec:
            assert title == rec["ep_title"]
        if "season_relative" in rec:
            assert relative is rec["season_relative"]
    if "season" in rec:
        assert extract_season_number(name) == rec["season"]
    if "year" in rec:
        assert extract_year(name) == rec["year"]
    if "is_tv" in rec:
        assert looks_like_tv_episode(Path(name)) is rec["is_tv"]
