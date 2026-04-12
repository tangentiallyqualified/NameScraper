"""Helpers for controller listeners, progress, and runtime settings."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from ...constants import MediaType
from ...engine import ScanState, set_auto_accept_threshold
from ..models import ScanLifecycle, ScanProgress

ListenerEntry = dict[str, Callable[..., Any] | None]

_log = logging.getLogger(__name__)


def add_controller_listener(
    listeners: list[ListenerEntry],
    on_library_changed: Callable[[list[ScanState]], None] | None = None,
    on_progress: Callable[[ScanProgress], None] | None = None,
    on_scan_complete: Callable[[ScanState | None], None] | None = None,
    on_mode_changed: Callable[[MediaType, MediaType | None], None] | None = None,
) -> int:
    listeners.append({
        "library_changed": on_library_changed,
        "progress": on_progress,
        "scan_complete": on_scan_complete,
        "mode_changed": on_mode_changed,
    })
    return len(listeners) - 1


def notify_controller_listeners(
    listeners: list[ListenerEntry],
    event: str,
    *args: Any,
) -> None:
    for listener in listeners:
        callback = listener.get(event)
        if callback is None:
            continue
        try:
            callback(*args)
        except Exception:
            _log.exception("Listener callback error for %s", event)


def build_scan_progress(
    lifecycle: ScanLifecycle,
    *,
    phase: str = "",
    done: int = 0,
    total: int = 0,
    current_item: str | None = None,
    message: str = "",
) -> ScanProgress:
    return ScanProgress(
        lifecycle=lifecycle,
        phase=phase,
        done=done,
        total=total,
        current_item=current_item,
        message=message,
    )


def apply_runtime_settings_to_states(
    auto_accept_threshold: float,
    states: Iterable[ScanState],
) -> None:
    set_auto_accept_threshold(auto_accept_threshold)
    for state in states:
        if state.match_origin == "manual":
            continue
        if state.needs_review:
            state.checked = False