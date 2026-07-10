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
import threading
import weakref
from concurrent.futures import Future, ThreadPoolExecutor, wait

_log = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ScraperWorker")
_inflight: "weakref.WeakSet[Future]" = weakref.WeakSet()
_inflight_lock = threading.Lock()


def submit(fn, /, *args, **kwargs) -> Future:
    """Submit *fn* to the shared pool.  Returns a :class:`~concurrent.futures.Future`."""
    future = _pool.submit(fn, *args, **kwargs)
    with _inflight_lock:
        _inflight.add(future)
    return future


def drain(timeout: float = 3.0) -> bool:
    """Cancel queued work and wait (bounded) for running work to finish.

    Called on app quit so no worker is mid-flight when Qt/CPython tear
    down.  Does NOT shut the pool down — callers may still submit after a
    drain (e.g. consecutive test classes).  Returns True when quiescent.
    """
    with _inflight_lock:
        pending = [f for f in _inflight if not f.done()]
    for future in pending:
        future.cancel()                      # no-op for already-running work
    not_done = wait(pending, timeout=timeout).not_done
    if not_done:
        _log.warning("thread_pool.drain: %d worker(s) still running after %.1fs",
                     len(not_done), timeout)
    return not not_done


def _atexit_shutdown() -> None:
    # Best effort: cancel anything queued, then release threads without
    # joining (a worker stuck on a network call must not hang exit).
    _pool.shutdown(wait=False, cancel_futures=True)


atexit.register(_atexit_shutdown)


def shutdown(wait: bool = False) -> None:
    """Shut down the shared pool (also registered as an *atexit* hook)."""
    _pool.shutdown(wait=wait)
