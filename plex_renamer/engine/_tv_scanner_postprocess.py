"""Postprocessing helpers for TVScanner previews and completeness."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..parsing import (
    clean_folder_name,
    clean_name,
    extract_episode,
    extract_source_title_prefix,
    is_companion_video_file,
    is_sample_file,
    normalize_for_match,
    normalize_for_specials,
)
from ._state import get_episode_auto_accept_threshold
from .models import (
    EPISODE_REVIEW_STATUS_PREFIX,
    CompletenessReport,
    PreviewItem,
    SeasonCompleteness,
)

EXPLICIT_EPISODE_FLOOR = 0.86
COMPATIBLE_PREFIX_FLOOR = 0.88
EPISODE_TITLE_MATCH_FLOOR = 0.92
EXACT_COVERAGE_FLOOR = 0.80
SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR = 0.85
NEAR_COMPLETE_COVERAGE_FLOOR = 0.74
CONTRADICTORY_PREFIX_CAP = 0.45


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


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def _raise_confidence(item: PreviewItem, floor: float) -> None:
    item.episode_confidence = _clamp_confidence(max(item.episode_confidence, floor))


def _cap_confidence(item: PreviewItem, cap: float) -> None:
    item.episode_confidence = _clamp_confidence(min(item.episode_confidence, cap))


def _is_generic_season_name(name: str, season_num: int) -> bool:
    normalized = normalize_for_match(name)
    return normalized in {
        "",
        f"season {season_num}",
        f"season {season_num:02d}",
        f"series {season_num}",
        f"series {season_num:02d}",
    }


def _compact_title(text: str) -> str:
    return normalize_for_specials(text)


def _title_is_compatible(source_title: str, candidate: str) -> bool:
    source_norm = normalize_for_match(source_title)
    candidate_norm = normalize_for_match(candidate)
    if not source_norm or not candidate_norm:
        return False
    if source_norm == candidate_norm:
        return True

    source_compact = _compact_title(source_title)
    candidate_compact = _compact_title(candidate)
    if len(candidate_compact) >= 6 and (
        source_compact.startswith(candidate_compact)
        or candidate_compact.startswith(source_compact)
    ):
        return True
    return False


def _source_title_is_compatible(
    source_title: str,
    *,
    show_name: str,
    season_num: int,
    season_name: str,
) -> bool:
    candidates = [show_name]
    if season_name and not _is_generic_season_name(season_name, season_num):
        candidates.append(season_name)
        if show_name:
            candidates.append(f"{show_name} {season_name}")

    return any(
        _title_is_compatible(source_title, candidate)
        for candidate in candidates
    )


def _episode_title_matches(raw_title: str | None, tmdb_title: str | None) -> bool:
    if not raw_title or not tmdb_title:
        return False
    raw_norm = _compact_title(raw_title)
    tmdb_norm = _compact_title(tmdb_title)
    return bool(raw_norm and tmdb_norm and raw_norm == tmdb_norm)


def _parse_air_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _expected_episode_numbers(season_data: dict, today: date) -> set[int]:
    titles = set(season_data.get("titles", {}).keys())
    if not titles:
        return set()

    episodes = season_data.get("episodes", {}) or {}
    aired: set[int] = set()
    saw_future = False

    for episode_num in titles:
        metadata = episodes.get(episode_num, {}) or {}
        air_date = _parse_air_date(metadata.get("air_date"))
        if air_date is None:
            continue
        if air_date <= today:
            aired.add(episode_num)
        else:
            saw_future = True

    if saw_future and aired:
        return aired
    return titles


def _is_regular_video_candidate(item: PreviewItem) -> bool:
    return (
        item.season is not None
        and item.season > 0
        and bool(item.episodes)
        and not is_companion_video_file(item.original)
        and not is_sample_file(item.original)
    )


def _valid_regular_episode_numbers(item: PreviewItem, season_data: dict) -> list[int]:
    expected = set(season_data.get("titles", {}).keys())
    return [episode for episode in item.episodes if episode in expected]


def _has_single_regular_season(tmdb_seasons: dict) -> bool:
    return sum(1 for season_num in tmdb_seasons if int(season_num) > 0) == 1


def _has_perfect_show_match(show_match_confidence: float | None) -> bool:
    return show_match_confidence is not None and _clamp_confidence(show_match_confidence) == 1.0


def apply_episode_confidence_adjustments(
    items: list[PreviewItem],
    tmdb_seasons: dict,
    show_info: dict,
    *,
    show_match_confidence: float | None = None,
    today: date | None = None,
) -> None:
    """Apply evidence-based episode confidence floors and caps after mapping."""
    current_date = today or date.today()
    show_name = show_info.get("name", "")
    season_issues: set[int] = set()
    ok_items_by_season: dict[int, list[PreviewItem]] = defaultdict(list)
    claims_by_episode: dict[tuple[int, int], list[PreviewItem]] = defaultdict(list)
    contradictory_prefix_items: list[PreviewItem] = []

    for item in items:
        if not _is_regular_video_candidate(item):
            continue
        season_num = item.season
        season_data = tmdb_seasons.get(season_num)
        if not season_data:
            season_issues.add(season_num)
            continue

        valid_episodes = _valid_regular_episode_numbers(item, season_data)
        if len(valid_episodes) != len(item.episodes):
            season_issues.add(season_num)
        for episode_num in valid_episodes:
            claims_by_episode[(season_num, episode_num)].append(item)

        if item.status != "OK":
            season_issues.add(season_num)
            continue
        if valid_episodes:
            ok_items_by_season[season_num].append(item)

    for (season_num, _episode_num), claimants in claims_by_episode.items():
        if len(claimants) > 1:
            season_issues.add(season_num)

    for season_items in ok_items_by_season.values():
        for item in season_items:
            episode_numbers, raw_title, is_season_relative = extract_episode(item.original.name)
            if is_season_relative:
                _raise_confidence(item, EXPLICIT_EPISODE_FLOOR)

            season_num = item.season or 0
            season_data = tmdb_seasons.get(season_num, {})
            season_name = str(season_data.get("name", ""))
            source_title = extract_source_title_prefix(item.original.name)
            source_compatible = True
            if source_title:
                source_compatible = _source_title_is_compatible(
                    source_title,
                    show_name=show_name,
                    season_num=season_num,
                    season_name=season_name,
                )
                if source_compatible and is_season_relative:
                    _raise_confidence(item, COMPATIBLE_PREFIX_FLOOR)

            if item.episodes:
                assigned_title = season_data.get("titles", {}).get(item.episodes[0])
                if _episode_title_matches(raw_title, assigned_title):
                    _raise_confidence(item, EPISODE_TITLE_MATCH_FLOOR)

            if not source_compatible:
                contradictory_prefix_items.append(item)

    single_regular_season = _has_single_regular_season(tmdb_seasons)
    perfect_show_match = _has_perfect_show_match(show_match_confidence)

    for season_num, season_items in ok_items_by_season.items():
        if season_num in season_issues:
            continue
        season_data = tmdb_seasons.get(season_num, {})
        expected = _expected_episode_numbers(season_data, current_date)
        if not expected:
            continue

        matched = {
            episode_num
            for item in season_items
            for episode_num in _valid_regular_episode_numbers(item, season_data)
        }
        missing = expected - matched
        if matched == expected:
            floor = EXACT_COVERAGE_FLOOR
            if single_regular_season and perfect_show_match:
                floor = SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR
        elif matched and matched <= expected and (
            len(missing) <= 1
            or (len(matched) / max(len(expected), 1)) >= 0.90
        ):
            floor = NEAR_COMPLETE_COVERAGE_FLOOR
        else:
            continue

        for item in season_items:
            _raise_confidence(item, floor)

    for item in contradictory_prefix_items:
        _cap_confidence(item, CONTRADICTORY_PREFIX_CAP)


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
