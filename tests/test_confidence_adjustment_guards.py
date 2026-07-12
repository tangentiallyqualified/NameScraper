"""Confidence-adjustment guards (R-F1 / R-F2 from the 2026-07-10 review).

R-F1: resolve_file rule 3 deliberately caps a number claim at 0.60 when a
weak title match DISAGREES with the parsed number. The season-relative
confidence floor (0.86) must not lift that back over the 0.85 auto-accept
threshold — the disagreement tags belong in the terminal review-lock set.

R-F2 (perfect-show coverage floor lifting number-only files to exactly
0.85) was investigated and deliberately NOT changed: the lift is a
test-locked product decision (test_scan_improvements single-season
exact-coverage tests). See the NOTE in apply_confidence_adjustments.

All offline and deterministic (no TMDB / network).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    apply_confidence_adjustments,
)
from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _make_table(slots):
    table = EpisodeAssignmentTable()
    for season, episode, title in slots:
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))
    return table


def _assignment_for_name(table, name):
    for file_id, entry in table.files.items():
        if entry.path.name == name:
            return table.assignment_for(file_id)
    raise AssertionError(f"no table entry for {name}")


class WeakTitleDisagreementStaysReviewableTests(unittest.TestCase):
    def test_part_number_title_disagreeing_with_number_stays_below_threshold(self):
        """`Show S01E05 - The Big Game Part 2` where the part-number title
        matches S01E11 must stay at review confidence; the season-relative
        floor must not lift the rule-3 cap past auto-accept (0.85)."""
        season_titles = {5: "Cold Open", 11: "The Big Game (2)"}
        table = _make_table(
            [(1, 5, "Cold Open"), (1, 11, "The Big Game (2)")]
        )
        _resolve_into_table(
            table,
            file_path=Path("Show S01E05 - The Big Game Part 2.mkv"),
            season_num=1,
            season_titles=season_titles,
        )
        assignment = _assignment_for_name(
            table, "Show S01E05 - The Big Game Part 2.mkv"
        )
        self.assertIsNotNone(assignment)
        # Sanity: rule 3 fired (weak title disagreement with the number).
        self.assertIn("title-weak-disagree", assignment.evidence)

        apply_confidence_adjustments(table, show_info={"name": "Show", "year": ""})

        assignment = _assignment_for_name(
            table, "Show S01E05 - The Big Game Part 2.mkv"
        )
        self.assertLessEqual(
            assignment.confidence, CONF_TITLE_WINS_INEXACT,
            "weak-title disagreement must stay review-locked; got "
            f"{assignment.confidence}",
        )


if __name__ == "__main__":
    unittest.main()
