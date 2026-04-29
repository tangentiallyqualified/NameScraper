"""Structured application-layer state models used by Phase 1 services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class ScanLifecycle(StrEnum):
    """Normalized scan lifecycle states for UI-neutral progress reporting."""

    IDLE = "idle"
    DISCOVERING = "discovering"
    MATCHING = "matching"
    SCANNING = "scanning"
    REFRESHING_CACHE = "refreshing_cache"
    READY = "ready"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RefreshState(StrEnum):
    """Freshness state for cached metadata and scan snapshots."""

    MISSING = "missing"
    FRESH = "fresh"
    STALE = "stale"
    REFRESHING = "refreshing"
    RECENTLY_REFRESHED = "recently_refreshed"


class QueueCommandState(StrEnum):
    """State model for queue command gating."""

    ENABLED = "enabled"
    DISABLED_NO_SELECTION = "disabled_no_selection"
    DISABLED_SCANNING = "disabled_scanning"
    DISABLED_UNRESOLVED_REVIEW = "disabled_unresolved_review"
    DISABLED_CONFLICT = "disabled_conflict"
    DISABLED_ALREADY_QUEUED = "disabled_already_queued"
    DISABLED_NO_ACTION_NEEDED = "disabled_no_action_needed"


class TVDirectoryRole(StrEnum):
    """Directory classification used during nested batch-TV discovery."""

    SHOW_ROOT = "show_root"
    CONTAINER = "container"
    SEASON_FOLDER = "season_folder"
    IGNORED_SYSTEM = "ignored_system"
    NON_TV_LEAF = "non_tv_leaf"


@dataclass(slots=True)
class ScanProgress:
    """Structured progress payload replacing free-form status strings."""

    lifecycle: ScanLifecycle = ScanLifecycle.IDLE
    phase: str = ""
    done: int = 0
    total: int = 0
    current_item: str | None = None
    message: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.done / self.total) * 100.0)

    @property
    def is_active(self) -> bool:
        return self.lifecycle in {
            ScanLifecycle.DISCOVERING,
            ScanLifecycle.MATCHING,
            ScanLifecycle.SCANNING,
            ScanLifecycle.REFRESHING_CACHE,
        }


@dataclass(slots=True)
class CacheEntry:
    """A persisted cache entry with freshness and eviction metadata."""

    namespace: str
    key: str
    value: Any
    refreshed_at: str
    expires_at: str | None
    last_accessed_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0
    is_refreshing: bool = False


@dataclass(slots=True)
class CacheLookup:
    """Result of a cache lookup with the resolved freshness state."""

    state: RefreshState
    entry: CacheEntry | None = None

    @property
    def value(self) -> Any:
        if self.entry is None:
            return None
        return self.entry.value

    @property
    def is_hit(self) -> bool:
        return self.entry is not None

    @property
    def is_fresh(self) -> bool:
        return self.state in {RefreshState.FRESH, RefreshState.RECENTLY_REFRESHED}


@dataclass(slots=True)
class QueueEligibility:
    """Queue gating result for a single item set or scan state."""

    command_state: QueueCommandState
    reason: str
    actionable_indices: list[int] = field(default_factory=list)
    selected_indices: list[int] = field(default_factory=list)
    blocked_counts: dict[str, int] = field(default_factory=dict)
    eligible_file_count: int = 0
    eligible_job_count: int = 0

    @property
    def enabled(self) -> bool:
        return self.command_state == QueueCommandState.ENABLED


@dataclass(slots=True)
class EpisodeGuideSummary:
    mapped_episodes: int = 0
    mapped_primary_files: int = 0
    companion_files: int = 0
    missing_episodes: int = 0
    unmapped_primary_files: int = 0
    orphan_companion_files: int = 0
    conflicts: int = 0


@dataclass(slots=True)
class EpisodeGuideRow:
    season: int
    episode: int
    title: str = ""
    source_id: str = "tmdb"
    primary_file: Any | None = None
    companions: list[Any] = field(default_factory=list)
    target_rename: str = ""
    status: str = ""
    confidence_label: str = ""
    overview: str = ""
    air_date: str = ""

    @property
    def episode_key(self) -> tuple[int, int]:
        return (self.season, self.episode)


@dataclass(slots=True)
class UnmappedFileRow:
    original: Path
    reason: str
    preview: Any | None = None
    ignored: bool = False


@dataclass(slots=True)
class EpisodeGuide:
    source_id: str = "tmdb"
    source_label: str = "TMDB"
    rows: list[EpisodeGuideRow] = field(default_factory=list)
    unmapped_primary_files: list[UnmappedFileRow] = field(default_factory=list)
    orphan_companion_files: list[Any] = field(default_factory=list)
    summary: EpisodeGuideSummary = field(default_factory=EpisodeGuideSummary)


@dataclass(slots=True)
class QueuePreflightSummary:
    enabled: bool
    mapped_primary_files: int = 0
    companion_files: int = 0
    missing_episodes: int = 0
    unmapped_primary_files: int = 0
    orphan_companion_files: int = 0
    conflicts: int = 0
    summary_text: str = ""


@dataclass(slots=True)
class TVDiscoveryCandidate:
    """A discovered TV show root found during recursive library traversal."""

    folder: Any
    relative_folder: str
    parent_relative_folder: str | None
    depth: int
    discovery_reason: str
    has_direct_season_subdirs: bool = False
    direct_episode_file_count: int = 0
    direct_video_file_count: int = 0
    discovered_via_symlink: bool = False


class MovieDirectoryRole(StrEnum):
    """Directory classification used during nested batch-movie discovery."""

    MOVIE_ROOT = "movie_root"
    CONTAINER = "container"
    MULTI_MOVIE_FOLDER = "multi_movie_folder"
    EXTRAS_FOLDER = "extras_folder"
    IGNORED_SYSTEM = "ignored_system"
    NON_MOVIE_LEAF = "non_movie_leaf"


@dataclass(slots=True)
class MovieDiscoveryCandidate:
    """A discovered movie root or multi-movie folder found during recursive library traversal."""

    folder: Any
    relative_folder: str
    parent_relative_folder: str | None
    depth: int
    discovery_reason: str
    direct_video_file_count: int = 0
    has_title_year_folder_name: bool = False
    discovered_via_symlink: bool = False
