"""Postprocessing helpers for TVScanner previews and completeness."""

from __future__ import annotations

from collections import defaultdict

from ..parsing import clean_folder_name, clean_name
from ._state import get_episode_auto_accept_threshold
from .models import (
    EPISODE_REVIEW_STATUS_PREFIX,
    CompletenessReport,
    PreviewItem,
    SeasonCompleteness,
)


def resolve_duplicate_episodes(
    items: list[PreviewItem],
    *,
    show_name: str,
) -> None:
    """Skip files that duplicate an episode already claimed by a better match."""
    normalized_show_title = clean_folder_name(
        show_name,
        include_year=False,
    ).casefold()

    episode_map: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        if item.status != "OK" or not item.episodes:
            continue
        for episode_num in item.episodes:
            episode_map[(item.season, episode_num)].append(index)

    for key, indices in episode_map.items():
        if len(indices) < 2:
            continue
        scored: list[tuple[int, float]] = []
        for index in indices:
            item = items[index]
            stem = clean_name(item.original.stem).casefold()
            if stem.startswith(normalized_show_title):
                score = len(normalized_show_title) / max(len(stem), 1)
            elif normalized_show_title in stem:
                score = len(normalized_show_title) / max(len(stem), 1) * 0.5
            else:
                score = 0.0
            scored.append((index, score))

        scored.sort(
            key=lambda item: (-item[1], len(clean_name(items[item[0]].original.stem)), item[0]),
        )
        for loser_index, _score in scored[1:]:
            loser = items[loser_index]
            loser.status = (
                f"SKIP: duplicate episode {key[1]} - filename does not match show title"
            )
            loser.new_name = None
            loser.target_dir = None


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
