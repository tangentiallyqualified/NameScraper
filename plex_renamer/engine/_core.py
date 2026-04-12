"""Compatibility re-export layer for the old engine monolith.

The active engine implementation now lives in focused internal modules,
but keeping this module as a thin shim preserves any direct imports of
``plex_renamer.engine._core`` while the refactor lands.
"""

from __future__ import annotations

from ._batch_orchestrators import BatchMovieOrchestrator, BatchTVOrchestrator
from ._movie_scanner import (
    MovieScanner,
    _build_movie_preview_item,
    _build_subtitle_companions,
    _prepare_movie_query,
)
from ._queue_bridge import (
    build_rename_job_from_items,
    build_rename_job_from_state,
    get_checked_indices_from_state,
)
from ._rename_execution import check_duplicates, execute_rename
from ._scan_runtime import CANCEL_SCAN, ScanCancelledError, _raise_if_cancelled
from ._tv_scanner import TVScanner
from .matching import (
    boost_scores_with_alt_titles,
    boost_tv_scores_with_episode_evidence,
    pick_alternate_matches,
    score_results,
    score_tv_results,
    title_similarity,
)

__all__ = [
    "BatchMovieOrchestrator",
    "BatchTVOrchestrator",
    "CANCEL_SCAN",
    "MovieScanner",
    "ScanCancelledError",
    "TVScanner",
    "_build_movie_preview_item",
    "_build_subtitle_companions",
    "_prepare_movie_query",
    "_raise_if_cancelled",
    "boost_scores_with_alt_titles",
    "boost_tv_scores_with_episode_evidence",
    "build_rename_job_from_items",
    "build_rename_job_from_state",
    "check_duplicates",
    "execute_rename",
    "get_checked_indices_from_state",
    "pick_alternate_matches",
    "score_results",
    "score_tv_results",
    "title_similarity",
]
