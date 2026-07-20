"""Queue-oriented action workflows for the media workspace.

Batch submission is asynchronous: ``add_tv_batch``/``add_movie_batch`` run
per-file mkvmerge probes and TMDB metadata calls, which against a cold
network-share library takes minutes — far too long for the GUI thread (the
old synchronous handoff froze the app until force-killed). The slow call
runs in the shared thread pool; a ``_QueueSubmissionBridge`` marshals
per-show progress and completion back onto the GUI thread, where the busy
overlay stays live until the batch settles.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from ._media_helpers import (
    format_batch_result as _format_batch_result,
    is_fully_ready_state as _is_fully_ready_state,
    is_state_queue_approvable as _is_state_queue_approvable,
    roster_selection_key as _roster_selection_key,
)
from ._media_workspace_action_state import media_noun
from .busy_overlay import BusyOverlay


class _QueueSubmissionBridge(QObject):
    """Marshals worker-thread progress/completion onto the GUI thread."""

    progress = Signal(str)
    finished = Signal(object, object)  # (BatchQueueResult | None, Exception | None)


def queue_selected_state(workspace, *, warning_box: Any = QMessageBox) -> None:
    state = workspace._selected_state()
    if state is None:
        workspace.status_message.emit(f"Select a {media_noun(workspace)} before queueing.", 4000)
        return
    if not _is_state_queue_approvable(state, media_type=workspace._media_type):
        workspace.status_message.emit(
            f"This {media_noun(workspace)} is not approved for queueing.",
            4000,
        )
        return
    original_checked = state.checked
    if not state.checked:
        # Clicking the queue button IS the approval (round5 5a): route the
        # auto-check through the same sync hook the roster's own row
        # checkbox uses (_set_state_checked), which flips both state.checked
        # and the per-file check_vars bindings. Gating reads check_vars, not
        # the state.checked flag alone, so setting only the flag would be
        # silently undone the next time the roster re-derives it. Shared for
        # both media types: this function always acts on one selected state,
        # whether it is a movie or a TV show.
        workspace._set_state_checked(state, True)

    def _unwind_auto_check() -> None:
        # Runs when the submission settles — synchronously for the early
        # returns inside queue_states (missing output folder, eligibility
        # bail), or from the completion handler once the async batch
        # finishes/fails. The auto-check above was ours: unwind it through
        # the same sync hook so the check_vars bindings (and the visible
        # roster checkbox) revert together with the flag.
        if not state.queued:
            if original_checked:
                state.checked = True
            else:
                workspace._set_state_checked(state, False)

    queue_states(
        workspace,
        [state],
        empty_message=f"Select a {media_noun(workspace)} before queueing.",
        warning_box=warning_box,
        on_settled=_unwind_auto_check,
    )


def queue_checked(
    workspace,
    *,
    question_box: Any = QMessageBox,
    warning_box: Any = QMessageBox,
) -> None:
    checked = [state for state in workspace._current_states() if state.checked]
    if not checked:
        workspace.status_message.emit("Select at least one actionable item before queueing.", 4000)
        return
    eligible = [
        state
        for state in checked
        if _is_state_queue_approvable(state, media_type=workspace._media_type)
    ]
    skipped = len(checked) - len(eligible)
    if skipped and eligible:
        skip_reasons = summarize_skip_reasons(workspace, checked)
        detail = ", ".join(f"{count} {reason}" for reason, count in skip_reasons.items())
        answer = question_box.question(
            workspace,
            "Queue Checked Items",
            f"Queueing {len(eligible)} of {len(checked)} checked — {detail} will be skipped.\n\nProceed?",
        )
        if answer != question_box.StandardButton.Yes:
            return
    queue_states(
        workspace,
        checked,
        empty_message="Select at least one actionable item before queueing.",
        warning_box=warning_box,
    )


def summarize_skip_reasons(workspace, states: list[ScanState]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for state in states:
        if _is_state_queue_approvable(state, media_type=workspace._media_type):
            continue
        if state.queued:
            reasons["already queued"] = reasons.get("already queued", 0) + 1
        elif state.scanning:
            reasons["still scanning"] = reasons.get("still scanning", 0) + 1
        elif state.needs_review:
            reasons["needs review"] = reasons.get("needs review", 0) + 1
        elif state.duplicate_of is not None:
            reasons["duplicate"] = reasons.get("duplicate", 0) + 1
        elif _is_fully_ready_state(state):
            reasons["already fully ready"] = reasons.get("already fully ready", 0) + 1
        else:
            reasons["ineligible"] = reasons.get("ineligible", 0) + 1
    return reasons


def queue_states(
    workspace,
    states: list[ScanState],
    *,
    empty_message: str,
    warning_box: Any = QMessageBox,
    on_settled: Callable[[], None] | None = None,
) -> None:
    """Validate then hand the batch to a background submission.

    Pre-checks run synchronously; the slow batch handoff (probes, TMDB
    metadata bake, job-store writes) runs in the thread pool. *on_settled*
    always fires exactly once — synchronously on any early return, or from
    the GUI-thread completion handler once the async submission finishes.
    """
    submitted = False
    try:
        if workspace._media_ctrl is None or workspace._queue_ctrl is None:
            return
        if getattr(workspace, "_queue_submission_inflight", False):
            workspace.status_message.emit(
                "A queue submission is already running — wait for it to finish.", 4000
            )
            return
        if not states:
            workspace.status_message.emit(empty_message, 4000)
            return

        eligibility = queue_eligibility(workspace, states)
        if not eligibility.enabled:
            workspace.status_message.emit(
                eligibility.reason or "The selected items cannot be queued right now.",
                4000,
            )
            return

        if workspace._media_type == "movie":
            root = workspace._media_ctrl.movie_folder
            if root is None:
                workspace.status_message.emit("No movie folder is loaded.", 4000)
                return
            output_root = (
                workspace._settings.valid_movie_output_folder if workspace._settings else None
            )
            if output_root is None:
                workspace.status_message.emit(
                    "Set a Movies output folder in Settings before queueing.", 4000
                )
                return
            add_batch = workspace._queue_ctrl.add_movie_batch
        else:
            root = workspace._media_ctrl.tv_root_folder
            if root is None:
                workspace.status_message.emit("No TV folder is loaded.", 4000)
                return
            output_root = (
                workspace._settings.valid_tv_output_folder if workspace._settings else None
            )
            if output_root is None:
                workspace.status_message.emit(
                    "Set a TV Shows output folder in Settings before queueing.", 4000
                )
                return
            add_batch = workspace._queue_ctrl.add_tv_batch

        _start_submission(
            workspace,
            states,
            add_batch=add_batch,
            root=root,
            output_root=output_root,
            warning_box=warning_box,
            on_settled=on_settled,
        )
        submitted = True
    finally:
        if not submitted and on_settled is not None:
            on_settled()


def _start_submission(
    workspace,
    states: list[ScanState],
    *,
    add_batch,
    root,
    output_root,
    warning_box: Any,
    on_settled: Callable[[], None] | None,
) -> None:
    """Run the batch handoff in the thread pool under a live overlay."""
    selected_key = _roster_selection_key(workspace._selected_state())
    gating = workspace._media_ctrl.command_gating
    settings = workspace._settings
    tmdb_client = workspace._tmdb_provider() if workspace._tmdb_provider is not None else None
    # A mixed batch can hold shows attributed to different providers (pins,
    # fallback matches, manual switches) — thread a per-state resolver so
    # each job's metadata bake uses ITS show's provider, not the single
    # window-level client. Only meaningful for TV (movies have no pool).
    provider_for_state = workspace._provider_for_state if workspace._media_type == "tv" else None

    bridge = _QueueSubmissionBridge(workspace)
    overlay = BusyOverlay(workspace, "Queueing…")

    def _report_progress(name: str, position: int, total: int) -> None:
        # Worker thread → GUI thread via the bridge signal; the suppress
        # covers the bridge being deleted during shutdown.
        with contextlib.suppress(RuntimeError):
            bridge.progress.emit(f"Queueing {name} ({position}/{total})…")

    def _worker() -> None:
        result = None
        error: Exception | None = None
        try:
            kwargs: dict[str, Any] = {
                "settings_service": settings,
                "tmdb_client": tmdb_client,
                "progress": _report_progress,
            }
            if provider_for_state is not None:
                kwargs["provider_for_state"] = provider_for_state
            result = add_batch(states, root, output_root, gating, **kwargs)
        except Exception as exc:
            error = exc
        with contextlib.suppress(RuntimeError):  # bridge deleted during shutdown
            bridge.finished.emit(result, error)

    def _on_finished(result, error) -> None:
        workspace._queue_submission_inflight = False
        # Overlay comes down before any box appears — never a scrim under
        # a modal (same invariant the old busy_scope kept).
        overlay.dismiss()
        bridge.deleteLater()
        try:
            if error is not None:
                warning_box.warning(workspace, "Queue Failed", str(error))
                return
            sync_error: Exception | None = None
            try:
                workspace._media_ctrl.sync_queued_states()
                workspace.refresh_from_controller()
                workspace._restore_roster_selection_by_key(selected_key)
            except Exception as exc:  # batch queued; only the view refresh failed
                sync_error = exc
            workspace.queue_changed.emit()
            if sync_error is not None:
                warning_box.warning(
                    workspace,
                    "Queued With Warnings",
                    f"The items were queued, but the view failed to refresh.\n\n{sync_error}",
                )
                return
            workspace.status_message.emit(_format_batch_result(result), 5000)
        finally:
            if on_settled is not None:
                on_settled()

    bridge.progress.connect(overlay.set_text)
    bridge.finished.connect(_on_finished)
    workspace._queue_submission_inflight = True
    overlay.show_now()
    try:
        _submit_bg(_worker)
    except Exception:
        # Pool rejected the submit (shutdown): unwind so the overlay
        # comes down and the guard doesn't wedge the session.
        workspace._queue_submission_inflight = False
        overlay.dismiss()
        bridge.deleteLater()
        raise


def queue_eligibility(workspace, states: list[ScanState]):
    if not states:
        return workspace._media_ctrl.command_gating.summarize_scan_states(
            [],
            require_resolved_review=True,
        )
    return workspace._media_ctrl.command_gating.summarize_scan_states(
        states,
        require_resolved_review=True,
        allow_show_level_queue=workspace._media_type == "tv",
    )
