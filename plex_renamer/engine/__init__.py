"""Rename engine package — re-exports the public API of the old ``engine`` module.

Previously this was a single 3700-line ``engine.py``.  The package split
preserves every existing ``from plex_renamer.engine import X`` call site
while letting internals live in focused submodules.
"""

from __future__ import annotations

from ._state import (
    AUTO_ACCEPT_THRESHOLD,
    DEFAULT_AUTO_ACCEPT_THRESHOLD,
    DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD,
    EPISODE_AUTO_ACCEPT_THRESHOLD,
    get_auto_accept_threshold,
    get_episode_auto_accept_threshold,
    set_auto_accept_threshold,
    set_episode_auto_accept_threshold,
)
from .models import (
    CompanionFile,
    CompletenessReport,
    DirectEpisodeEvidence,
    PreviewItem,
    RenameResult,
    ScanState,
    SeasonCompleteness,
    collect_direct_episode_evidence,
    infer_explicit_season_assignment,
)
from ._batch_orchestrators import (
    BatchMovieOrchestrator,
    BatchTVOrchestrator,
)
from .matching import (
    boost_scores_with_alt_titles,
    boost_tv_scores_with_episode_evidence,
    pick_alternate_matches,
    score_results,
    score_tv_results,
    title_similarity,
)
from ._movie_scanner import MovieScanner
from ._queue_bridge import (
    build_rename_job_from_items,
    build_rename_job_from_state,
    get_checked_indices_from_state,
)
from ._rename_execution import (
    check_duplicates,
    execute_rename,
)
from ._scan_runtime import (
    CANCEL_SCAN,
    ScanCancelledError,
)
from ._tv_scanner import TVScanner

__all__ = [
    "AUTO_ACCEPT_THRESHOLD",
    "BatchMovieOrchestrator",
    "BatchTVOrchestrator",
    "CANCEL_SCAN",
    "CompanionFile",
    "CompletenessReport",
    "DEFAULT_AUTO_ACCEPT_THRESHOLD",
    "DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD",
    "DirectEpisodeEvidence",
    "EPISODE_AUTO_ACCEPT_THRESHOLD",
    "MovieScanner",
    "PreviewItem",
    "RenameResult",
    "ScanCancelledError",
    "ScanState",
    "SeasonCompleteness",
    "TVScanner",
    "boost_scores_with_alt_titles",
    "boost_tv_scores_with_episode_evidence",
    "build_rename_job_from_items",
    "build_rename_job_from_state",
    "check_duplicates",
    "collect_direct_episode_evidence",
    "execute_rename",
    "get_auto_accept_threshold",
    "get_episode_auto_accept_threshold",
    "get_checked_indices_from_state",
    "infer_explicit_season_assignment",
    "pick_alternate_matches",
    "score_results",
    "score_tv_results",
    "set_auto_accept_threshold",
    "set_episode_auto_accept_threshold",
    "title_similarity",
]
