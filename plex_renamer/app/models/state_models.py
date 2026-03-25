"""Structured application-layer state models used by Phase 1 services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
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