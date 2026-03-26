"""Typed application-layer models shared across controllers and services."""

from .state_models import (
    CacheEntry,
    CacheLookup,
    MovieDirectoryRole,
    MovieDiscoveryCandidate,
    QueueCommandState,
    QueueEligibility,
    RefreshState,
    ScanLifecycle,
    ScanProgress,
    TVDirectoryRole,
    TVDiscoveryCandidate,
)

__all__ = [
    "CacheEntry",
    "CacheLookup",
    "MovieDirectoryRole",
    "MovieDiscoveryCandidate",
    "QueueCommandState",
    "QueueEligibility",
    "RefreshState",
    "ScanLifecycle",
    "ScanProgress",
    "TVDirectoryRole",
    "TVDiscoveryCandidate",
]