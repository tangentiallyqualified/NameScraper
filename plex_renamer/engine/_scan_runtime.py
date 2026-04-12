"""Shared scan-control primitives for long-running engine operations."""

from __future__ import annotations

import threading


# Sentinel value returned by the pick callback to cancel the entire scan.
CANCEL_SCAN = object()


class ScanCancelledError(RuntimeError):
    """Raised when a long-running scan is cancelled by the user."""


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelledError("Scan cancelled")