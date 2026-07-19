"""SeasonCompleteness.review counts review-status episode mappings (GUI4 R2 M7)."""

from pathlib import Path

from plex_renamer.engine._tv_scanner_postprocess import build_completeness_report
from plex_renamer.engine.models import EPISODE_REVIEW_STATUS_PREFIX, PreviewItem


def _item(name: str, season: int, episodes: list[int], status: str) -> PreviewItem:
    return PreviewItem(
        original=Path(f"C:/fake/{name}"),
        new_name=name,
        target_dir=None,
        season=season,
        episodes=episodes,
        status=status,
    )


def _tmdb_seasons() -> dict:
    return {1: {"titles": {1: "One", 2: "Two", 3: "Three"}}}


def test_review_items_counted_separately_from_matched():
    items = [
        _item("e1.mkv", 1, [1], "OK"),
        _item("e2.mkv", 1, [2], f"{EPISODE_REVIEW_STATUS_PREFIX} (60% < 85%)"),
    ]
    checked = {0}  # callers pass only status == "OK" indices
    report = build_completeness_report(_tmdb_seasons(), items, checked_indices=checked)
    season = report.seasons[1]
    assert season.matched == 1
    assert season.review == 1
    assert season.missing == [(3, "Three")]
    assert not season.is_complete


def test_review_never_double_counts_matched_episodes():
    # Same episode has an approved file AND a review-status file: review must not
    # re-count E1.
    items = [
        _item("e1a.mkv", 1, [1], "OK"),
        _item("e1b.mkv", 1, [1], f"{EPISODE_REVIEW_STATUS_PREFIX} (60% < 85%)"),
    ]
    report = build_completeness_report(_tmdb_seasons(), items, checked_indices={0})
    season = report.seasons[1]
    assert season.matched == 1
    assert season.review == 0


def test_review_defaults_to_zero_without_review_items():
    items = [_item("e1.mkv", 1, [1], "OK")]
    report = build_completeness_report(_tmdb_seasons(), items, checked_indices={0})
    assert report.seasons[1].review == 0


def test_review_episodes_carry_titles():
    items = [
        _item("e1.mkv", 1, [1], "OK"),
        _item("e2.mkv", 1, [2], f"{EPISODE_REVIEW_STATUS_PREFIX} (60% < 85%)"),
    ]
    report = build_completeness_report(_tmdb_seasons(), items, checked_indices={0})
    assert report.seasons[1].review_episodes == [(2, "Two")]
