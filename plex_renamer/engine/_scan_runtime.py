"""Shared scan-control primitives for long-running engine operations."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ..providers import SeasonMapUnavailableError

if TYPE_CHECKING:
    from .models import ScanState

# Sentinel value returned by the pick callback to cancel the entire scan.
CANCEL_SCAN = object()


class ScanCancelledError(RuntimeError):
    """Raised when a long-running scan is cancelled by the user."""


EPISODE_GUIDE_UNAVAILABLE_MESSAGE = "Episode guide is unavailable; retry the provider scan."


def scan_failure_message(error: Exception) -> str:
    """Return the stable user-facing message for a failed TV scan."""
    if isinstance(error, SeasonMapUnavailableError):
        return EPISODE_GUIDE_UNAVAILABLE_MESSAGE
    return str(error).strip() or "TV scan failed."


def fail_scan_state(state: ScanState, error: Exception) -> Exception:
    """Clear stale scan output and leave the state visibly failed closed."""
    state.reset_scan()
    state.checked = False
    state.scan_error = scan_failure_message(error)
    return error


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelledError("Scan cancelled")
