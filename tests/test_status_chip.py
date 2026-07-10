# tests/test_status_chip.py
"""Season chip spec builder rules (GUI V4 spec §4)."""
from __future__ import annotations

from plex_renamer.engine.models import CompletenessReport, SeasonCompleteness
from plex_renamer.gui_qt.widgets.status_chip import (
    ChipSpec,
    _collapse_complete_runs,
    _season_chip,
    _strip_season_chip,
    season_chip_specs,
    season_strip_specs,
)


def _season(n, expected, matched, missing=()):
    return SeasonCompleteness(
        season=n, expected=expected, matched=matched,
        missing=[(num, f"Ep {num}") for num in missing],
    )


def _report(seasons, specials=None):
    return CompletenessReport(
        seasons={s.season: s for s in seasons},
        specials=specials,
        total_expected=sum(s.expected for s in seasons),
        total_matched=sum(s.matched for s in seasons),
        total_missing=[],
    )


def test_none_report_yields_no_chips():
    assert season_chip_specs(None) == []


def test_complete_incomplete_and_missing_tones():
    report = _report([
        _season(1, 10, 10),
        _season(2, 10, 9, missing=(4,)),
        _season(3, 8, 0, missing=tuple(range(1, 9))),
    ])
    chips = season_chip_specs(report)
    assert chips[0] == ChipSpec("S1 ✓", "success", "Season 1: 10/10")
    assert chips[1].text == "S2 9/10"
    assert chips[1].tone == "warning"
    assert chips[1].tooltip == "Season 2 missing E04"
    assert chips[2] == ChipSpec("S3 0/8", "muted", "Season 3 missing E01, E02, E03, E04, E05, E06, E07, E08")


def test_specials_chip_appended_last():
    report = _report([_season(1, 5, 5)], specials=_season(0, 3, 2, missing=(3,)))
    chips = season_chip_specs(report)
    assert chips[-1].text == "SP 2/3"
    assert chips[-1].tone == "warning"


def test_complete_runs_collapse_when_over_max():
    seasons = [_season(n, 10, 10) for n in range(1, 7)] + [_season(7, 10, 3, missing=tuple(range(4, 11)))]
    chips = season_chip_specs(_report(seasons), max_chips=6)
    assert chips[0].text == "S1–S6 ✓"
    assert chips[0].tone == "success"
    assert chips[1].text == "S7 3/10"


def test_no_collapse_at_or_under_max():
    seasons = [_season(n, 10, 10) for n in range(1, 6)]
    chips = season_chip_specs(_report(seasons), max_chips=6)
    assert [chip.text for chip in chips] == ["S1 ✓", "S2 ✓", "S3 ✓", "S4 ✓", "S5 ✓"]


def test_missing_tooltip_truncates_after_twelve():
    season = _season(1, 20, 4, missing=tuple(range(5, 21)))
    chips = season_chip_specs(_report([season]))
    assert chips[0].tooltip.endswith(", …")
    assert chips[0].tooltip.count("E") == 12


def test_season_strip_specs_uncollapsed_with_counts():
    seasons = [_season(n, 10, 10) for n in range(1, 8)]
    specs = season_strip_specs(_report(seasons, specials=_season(0, 3, 1, missing=(2, 3))))
    assert len(specs) == 8                       # 7 seasons + SP, no collapse
    assert specs[0] == (1, ChipSpec("S1 ✓10", "success", "Season 1: 10/10"))
    assert specs[-1][0] == 0
    assert specs[-1][1].text == "SP 1/3"


def test_drop_empty_hides_zero_matched_seasons():
    report = _report([
        _season(1, 10, 10),
        _season(2, 8, 0, missing=tuple(range(1, 9))),
        _season(3, 10, 4, missing=(5, 6)),
    ])
    chips = season_chip_specs(report, drop_empty=True)
    assert [chip.text for chip in chips] == ["S1 ✓", "S3 4/10"]


def test_drop_empty_hides_zero_matched_specials():
    report = _report([_season(1, 5, 5)], specials=_season(0, 3, 0, missing=(1, 2, 3)))
    chips = season_chip_specs(report, drop_empty=True)
    assert [chip.text for chip in chips] == ["S1 ✓"]


def test_drop_empty_default_false_keeps_zero_seasons():
    report = _report([_season(1, 10, 10), _season(2, 8, 0, missing=(1,))])
    assert len(season_chip_specs(report)) == 2


def test_season_chip_counts_review_episodes_but_stays_warning():
    season = SeasonCompleteness(season=1, expected=8, matched=6, missing=[], review=2)
    chip = _season_chip(season)
    assert chip.text == "S1 8/8"
    assert chip.tone == "warning"
    assert "awaiting approval" in chip.tooltip


def test_season_chip_goes_green_only_after_approval():
    season = SeasonCompleteness(season=1, expected=8, matched=8, missing=[], review=0)
    assert _season_chip(season).tone == "success"


def test_strip_chip_counts_review_episodes():
    season = SeasonCompleteness(season=2, expected=10, matched=7, missing=[], review=3)
    chip = _strip_season_chip(season)
    assert chip.text == "S2 10/10"
    assert chip.tone == "warning"


def test_complete_run_collapse_excludes_seasons_with_pending_review():
    complete = SeasonCompleteness(season=1, expected=3, matched=3, missing=[], review=0)
    pending = SeasonCompleteness(season=2, expected=3, matched=3, missing=[], review=1)
    chips = _collapse_complete_runs([complete, pending])
    assert chips[0].tone == "success"
    assert chips[1].tone == "warning"
