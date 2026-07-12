"""Drain semantics for the shared background pool."""
import threading
import time

from plex_renamer import thread_pool


def test_drain_waits_for_running_work():
    started = threading.Event()
    done = threading.Event()

    def work():
        started.set()
        time.sleep(0.2)
        done.set()

    thread_pool.submit(work)
    # Wait for the worker to actually start (transition PENDING -> RUNNING)
    # before draining, otherwise drain's cancel-queued-work step can race
    # the worker pickup and cancel it before it ever runs -- that is
    # correct drain behavior for queued work, but this test is exercising
    # the "wait for running work" half of drain, not the cancellation half.
    assert started.wait(timeout=5.0)
    assert thread_pool.drain(timeout=5.0) is True
    assert done.is_set()


def test_drain_times_out_on_stuck_worker():
    started = threading.Event()
    release = threading.Event()

    def stuck():
        started.set()
        release.wait()

    thread_pool.submit(stuck)
    # Wait for the worker to actually start (transition PENDING -> RUNNING)
    # before draining, otherwise drain's own cancel-queued-work step can
    # race the worker pickup and cancel it before it ever runs.
    assert started.wait(timeout=5.0)
    try:
        assert thread_pool.drain(timeout=0.3) is False
    finally:
        release.set()
        thread_pool.drain(timeout=5.0)
