"""Helpers for queue history, undo, and poster backfill behavior."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...constants import JobStatus
from ...engine import RenameResult
from ...job_executor import QueueExecutor
from ...job_store import JobStore, RenameJob


def record_completed_queue_job(
    job_store: JobStore,
    job: RenameJob,
    result: RenameResult,
) -> None:
    if result.renamed_count == 0:
        return

    job.status = JobStatus.COMPLETED
    job.undo_data = result.log_entry
    if result.errors:
        job.error_message = "; ".join(result.errors[:5])
    job_store.add_job(job)


def revert_queue_job(
    job_store: JobStore,
    job_id: str,
    *,
    revert_runner: Callable[[RenameJob], tuple[bool, list[str]]],
) -> tuple[bool, list[str]]:
    job = job_store.get_job(job_id)
    if job is None:
        return False, [f"Job {job_id} not found."]
    if not job.undo_data:
        return False, ["No undo data stored for this job."]

    success, errors = revert_runner(job)
    job_store.update_status(
        job_id,
        JobStatus.REVERTED if success else JobStatus.REVERT_FAILED,
        error_message="; ".join(errors[:3]) if errors else None,
    )
    return success, errors


def backfill_missing_queue_job_poster_paths(job_store: JobStore, tmdb: Any) -> int:
    cache: dict[tuple[str, int], str | None] = {}
    updated = 0

    for job in job_store.get_all():
        if job.poster_path or not job.tmdb_id:
            continue

        key = (job.media_type, job.tmdb_id)
        poster_path = cache.get(key)
        if key not in cache:
            poster_path = tmdb.get_cached_poster_path(job.tmdb_id, media_type=job.media_type)
            cache[key] = poster_path

        if poster_path:
            job_store.set_poster_path(job.job_id, poster_path)
            updated += 1

    return updated


def close_queue_resources(executor: QueueExecutor, job_store: JobStore) -> None:
    if executor.is_running:
        executor.stop()
    job_store.close()
