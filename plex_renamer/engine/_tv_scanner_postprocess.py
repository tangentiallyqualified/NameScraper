"""Postprocessing helpers for TVScanner previews and completeness.

Episode confidence calibration (floors, caps, duplicate resolution) moved
to ``_episode_resolution.apply_confidence_adjustments`` operating on the
``EpisodeAssignmentTable``; this module keeps only the item-level review
threshold flip (used when runtime settings change) and completeness
reporting.
"""

from __future__ import annotations

from collections import defaultdict

from ._state import get_episode_auto_accept_threshold
from .models import (
    EPISODE_REVIEW_STATUS_PREFIX,
    CompletenessReport,
    PreviewItem,
    SeasonCompleteness,
)


def apply_episode_review_threshold(items: list[PreviewItem]) -> None:
    """Mark low-confidence episode mappings for manual approval."""
    threshold = get_episode_auto_accept_threshold()
    for item in items:
        if item.status == "OK" and item.episode_confidence < threshold:
            item.status = (
                f"{EPISODE_REVIEW_STATUS_PREFIX} "
                f"({item.episode_confidence:.0%} < {threshold:.0%})"
            )
        elif item.status.startswith(EPISODE_REVIEW_STATUS_PREFIX) and item.episode_confidence >= threshold:
            item.status = "OK"


def build_completeness_report(
    tmdb_seasons: dict,
    items: list[PreviewItem],
    checked_indices: set[int] | None = None,
) -> CompletenessReport:
    """Compute completeness of matched episodes vs TMDB expectations."""
    matched_by_season: dict[int, set[int]] = defaultdict(set)
    for index, item in enumerate(items):
        if checked_indices is not None and index not in checked_indices:
            continue
        if item.season is not None and item.episodes:
            for episode_num in item.episodes:
                matched_by_season[item.season].add(episode_num)

    seasons: dict[int, SeasonCompleteness] = {}

    for season_num, season_data in sorted(tmdb_seasons.items()):
        expected_eps = set(season_data["titles"].keys())
        matched_eps = matched_by_season.get(season_num, set())
        matched_valid = matched_eps & expected_eps
        missing_eps = expected_eps - matched_valid

        missing_details = []
        for episode_num in sorted(missing_eps):
            title = season_data["titles"].get(episode_num, f"Episode {episode_num}")
            missing_details.append((episode_num, title))

        matched_details = []
        for episode_num in sorted(matched_valid):
            title = season_data["titles"].get(episode_num, f"Episode {episode_num}")
            matched_details.append((episode_num, title))

        seasons[season_num] = SeasonCompleteness(
            season=season_num,
            expected=len(expected_eps),
            matched=len(matched_valid),
            missing=missing_details,
            matched_episodes=matched_details,
        )

    total_expected = sum(season.expected for season_num, season in seasons.items() if season_num > 0)
    total_matched = sum(season.matched for season_num, season in seasons.items() if season_num > 0)
    total_missing = []
    for season_num, season in sorted(seasons.items()):
        if season_num > 0:
            for episode_num, title in season.missing:
                total_missing.append((season_num, episode_num, title))

    specials = seasons.get(0)

    return CompletenessReport(
        seasons={season_num: season for season_num, season in seasons.items() if season_num > 0},
        specials=specials,
        total_expected=total_expected,
        total_matched=total_matched,
        total_missing=total_missing,
    )
