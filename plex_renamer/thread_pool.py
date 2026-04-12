"""Shared thread pool for background work.

All fire-and-forget background tasks should use :func:`submit` instead of
spawning raw ``threading.Thread`` instances.  The pool caps concurrency
and reuses threads.

The ``QueueExecutor`` long-running worker loop is excluded — it manages
its own thread lifecycle.
"""

from __future__ import annotations

import atexit
import logging
from concurrent.futures import Future, ThreadPoolExecutor

_log = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="PlexWorker")
atexit.register(_pool.shutdown, wait=False)


def submit(fn, /, *args, **kwargs) -> Future:
    """Submit *fn* to the shared pool.  Returns a :class:`~concurrent.futures.Future`."""
    return _pool.submit(fn, *args, **kwargs)


def shutdown(wait: bool = False) -> None:
    """Shut down the shared pool (also registered as an *atexit* hook)."""
    _pool.shutdown(wait=wait)
