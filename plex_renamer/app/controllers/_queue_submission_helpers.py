"""Helpers for queue job creation and batch submission."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ...constants import MediaType
from ...engine import (
    PreviewItem,
    ScanState,
    build_rename_job_from_items,
    build_rename_job_from_state,
)
from ...job_store import DuplicateJobError, RenameJob
from ...parsing import build_movie_name, build_show_folder_name
from ..services.automux_service import (
    automux_active,
    effective_mux_plans,
    ensure_state_plans,
)
from ..services.command_gating_service import CommandGatingService
from ..services.metadata_service import attach_metadata_plan, metadata_active

_log = logging.getLogger(__name__)


def _mux_plans_for_state(state, settings_service, library_root) -> dict[int, dict] | None:
    """Ensure and collect this entry's mux plans at queue time (spec §5.1:
    plans are baked into the job's ops when it is queued)."""
    if settings_service is None or not automux_active(settings_service):
        return None
    ensure_state_plans(state, settings_service, library_root)
    return effective_mux_plans(state)


def _bake_metadata_plan(job, settings_service, tmdb_client, library_root) -> None:
    """Attach the metadata plan when the feature is active (spec:
    local-metadata-artwork; baked at queue time like mux plans)."""
    if settings_service is None or tmdb_client is None:
        return
    if not metadata_active(settings_service):
        return
    try:
        attach_metadata_plan(
            job,
            tmdb_client=tmdb_client,
            settings_service=settings_service,
            library_root=library_root,
        )
    except Exception:
        # A single show's metadata bake (e.g. a TMDB call raising) must
        # never abort queueing the whole batch — leave the job
        # undecorated and continue. Core invariant: metadata must never
        # fail a job or block queueing.
        _log.warning(
            "Metadata plan bake failed for job %r; queueing without "
            "metadata plan.", getattr(job, "job_id", None), exc_info=True)
        job.metadata_plan = None


@dataclass
class BatchQueueResult:
    """Summary of a batch queue submission."""

    added: int = 0
    skipped_duplicate: int = 0
    skipped_queued: int = 0
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_skipped(self) -> int:
        return self.skipped_duplicate + self.skipped_queued


class _QueueJobStore(Protocol):
    def add_job(self, job: RenameJob) -> RenameJob: ...


def add_single_queue_job(
    job_store: _QueueJobStore,
    *,
    items: list[PreviewItem],
    checked_indices: set[int],
    media_type: str,
    tmdb_id: int,
    media_name: str,
    library_root: Path,
    output_root: Path,
    source_folder: Path,
    show_folder_rename: str | None = None,
    poster_path: str | None = None,
    settings_service=None,
    tmdb_client=None,
) -> RenameJob:
    job = build_rename_job_from_items(
        items=items,
        checked_indices=checked_indices,
        media_type=media_type,
        tmdb_id=tmdb_id,
        media_name=media_name,
        library_root=library_root,
        output_root=output_root,
        source_folder=source_folder,
        show_folder_rename=show_folder_rename,
        poster_path=poster_path,
    )
    if not job.selected_ops:
        raise ValueError("No actionable rename operations are selected.")
    _bake_metadata_plan(job, settings_service, tmdb_client, library_root)
    job_store.add_job(job)
    return job


def add_tv_batch_jobs(
    job_store: _QueueJobStore,
    *,
    states: list[ScanState],
    library_root: Path,
    output_root: Path,
    command_gating: CommandGatingService,
    settings_service=None,
    tmdb_client=None,
) -> BatchQueueResult:
    result = BatchQueueResult()

    for state in states:
        if not state.checked:
            continue

        eligibility = command_gating.evaluate_scan_state(
            state,
            require_resolved_review=True,
            allow_show_level_queue=True,
        )
        if not eligibility.enabled:
            if eligibility.command_state.value == "disabled_already_queued":
                result.skipped_queued += 1
            else:
                result.blocked.append(f"{state.display_name}: {eligibility.reason}")
            continue

        checked = set(eligibility.selected_indices)
        if not checked and any(command_gating.is_actionable_item(item) for item in state.preview_items):
            result.blocked.append(f"{state.display_name}: Select at least one file before queueing")
            continue

        show_folder = build_show_folder_name(
            state.media_info.get("name", ""),
            state.media_info.get("year", ""),
        )
        mux_plans = _mux_plans_for_state(state, settings_service, library_root)
        job = build_rename_job_from_state(
            state=state,
            library_root=library_root,
            output_root=output_root,
            show_folder_rename=show_folder,
            checked_indices=checked,
            mux_plans=mux_plans,
        )
        _bake_metadata_plan(job, settings_service, tmdb_client, library_root)

        try:
            job_store.add_job(job)
            state.queued = True
            result.added += 1
        except DuplicateJobError:
            result.skipped_duplicate += 1
        except Exception as exc:
            result.errors.append(f"{state.display_name}: {exc}")

    return result


def add_movie_batch_jobs(
    job_store: _QueueJobStore,
    *,
    states: list[ScanState],
    library_root: Path,
    output_root: Path,
    command_gating: CommandGatingService,
    settings_service=None,
    tmdb_client=None,
) -> BatchQueueResult:
    result = BatchQueueResult()

    for state in states:
        if not state.checked:
            continue

        eligibility = command_gating.evaluate_scan_state(state, require_resolved_review=True)
        if not eligibility.enabled:
            if eligibility.command_state.value == "disabled_already_queued":
                result.skipped_queued += 1
            else:
                result.blocked.append(f"{state.display_name}: {eligibility.reason}")
            continue

        checked = set(eligibility.selected_indices)
        if not checked:
            result.blocked.append(f"{state.display_name}: Select at least one file before queueing")
            continue

        if not state.preview_items:
            result.skipped_queued += 1
            continue

        item = state.preview_items[0]
        movie_folder = build_movie_name(
            state.media_info.get("title", ""),
            state.media_info.get("year", ""),
            "",
        )
        mux_plans = _mux_plans_for_state(state, settings_service, library_root)
        job = build_rename_job_from_items(
            items=[item],
            checked_indices=checked,
            media_type=MediaType.MOVIE,
            tmdb_id=state.show_id or 0,
            media_name=state.display_name,
            library_root=library_root,
            output_root=output_root,
            source_folder=item.original.parent,
            show_folder_rename=movie_folder,
            poster_path=state.media_info.get("poster_path"),
            mux_plans=mux_plans,
        )
        _bake_metadata_plan(job, settings_service, tmdb_client, library_root)

        try:
            job_store.add_job(job)
            state.queued = True
            result.added += 1
        except DuplicateJobError:
            result.skipped_duplicate += 1

    return result
