"""Mutable engine state shared across submodules.

Kept in a dedicated module so ``models`` and ``_core`` can both read the
current threshold without a circular import, and runtime updates via
``set_auto_accept_threshold`` are visible everywhere.
"""

from __future__ import annotations


DEFAULT_AUTO_ACCEPT_THRESHOLD = 0.55
AUTO_ACCEPT_THRESHOLD = DEFAULT_AUTO_ACCEPT_THRESHOLD

DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD = 0.85
EPISODE_AUTO_ACCEPT_THRESHOLD = DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD


def get_auto_accept_threshold() -> float:
    return AUTO_ACCEPT_THRESHOLD


def set_auto_accept_threshold(value: float) -> float:
    """Update the runtime auto-accept threshold used by scan/review logic."""
    global AUTO_ACCEPT_THRESHOLD
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = DEFAULT_AUTO_ACCEPT_THRESHOLD
    AUTO_ACCEPT_THRESHOLD = max(0.50, min(1.00, threshold))
    return AUTO_ACCEPT_THRESHOLD


def get_episode_auto_accept_threshold() -> float:
    return EPISODE_AUTO_ACCEPT_THRESHOLD


def set_episode_auto_accept_threshold(value: float) -> float:
    """Update the runtime threshold used for episode auto-mapping review."""
    global EPISODE_AUTO_ACCEPT_THRESHOLD
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
    EPISODE_AUTO_ACCEPT_THRESHOLD = max(0.50, min(1.00, threshold))
    return EPISODE_AUTO_ACCEPT_THRESHOLD
