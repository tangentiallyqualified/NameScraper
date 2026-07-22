"""Failure boundary for direct provider-backed show scans."""

# pyright: strict

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import wraps
from typing import TypeVar, cast

from ..providers import SeasonMapUnavailableError
from ._scan_runtime import fail_scan_state
from .models import ScanState

_log = logging.getLogger(__name__)
_Method = TypeVar("_Method", bound=Callable[..., None])


def guard_season_map_scan(method: _Method) -> _Method:
    """Translate a typed provider outage into the public failed-state contract."""

    @wraps(method)
    def guarded(
        receiver: object,
        state: ScanState,
        progress_callback: Callable[..., object] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        try:
            method(receiver, state, progress_callback, cancel_event)
        except SeasonMapUnavailableError as error:
            fail_scan_state(state, error)
            _log.warning("Episode guide unavailable for %s", state.display_name)

    return cast(_Method, guarded)
