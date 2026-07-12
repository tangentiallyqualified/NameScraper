"""Queue-oriented action workflows for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState
from ._media_helpers import (
    format_batch_result as _format_batch_result,
    is_fully_ready_state as _is_fully_ready_state,
    is_state_queue_approvable as _is_state_queue_approvable,
    roster_selection_key as _roster_selection_key,
)
from ._media_workspace_action_state import media_noun
from .busy_overlay import busy_scope


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
    try:
        queue_states(
            workspace,
            [state],
            empty_message=f"Select a {media_noun(workspace)} before queueing.",
            warning_box=warning_box,
        )
    finally:
        if not state.queued:
            if original_checked:
                state.checked = True
            else:
                # The auto-check above was ours: unwind it through the same
                # sync hook so the check_vars bindings (and the visible
                # roster checkbox) revert together with the flag. Early
                # returns inside queue_states (missing output folder,
                # eligibility bail) and exceptions all land here without a
                # refresh, so a bare flag reset would leave the checkbox
                # visibly checked over an unchecked state.
                workspace._set_state_checked(state, False)


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
        state for state in checked
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
) -> None:
    if workspace._media_ctrl is None or workspace._queue_ctrl is None:
        return
    if not states:
        workspace.status_message.emit(empty_message, 4000)
        return

    selected_key = _roster_selection_key(workspace._selected_state())
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
        output_root = workspace._settings.valid_movie_output_folder if workspace._settings else None
        if output_root is None:
            workspace.status_message.emit("Set a Movies output folder in Settings before queueing.", 4000)
            return
        add_batch = workspace._queue_ctrl.add_movie_batch
    else:
        root = workspace._media_ctrl.tv_root_folder
        if root is None:
            workspace.status_message.emit("No TV folder is loaded.", 4000)
            return
        output_root = workspace._settings.valid_tv_output_folder if workspace._settings else None
        if output_root is None:
            workspace.status_message.emit("Set a TV Shows output folder in Settings before queueing.", 4000)
            return
        add_batch = workspace._queue_ctrl.add_tv_batch

    sync_error: Exception | None = None
    try:
        # An exception unwinds through the scope (dismissing the overlay)
        # before any box appears — never a scrim under a modal.
        with busy_scope(workspace, "Queueing…", immediate=True):
            result = add_batch(
                states,
                root,
                output_root,
                workspace._media_ctrl.command_gating,
                settings_service=workspace._settings,
                tmdb_client=(workspace._tmdb_provider()
                             if workspace._tmdb_provider is not None else None),
            )
            try:
                workspace._media_ctrl.sync_queued_states()
                workspace.refresh_from_controller()
                workspace._restore_roster_selection_by_key(selected_key)
            except Exception as exc:    # batch queued; only the view refresh failed
                sync_error = exc
    except Exception as exc:
        warning_box.warning(workspace, "Queue Failed", str(exc))
        return

    workspace.queue_changed.emit()
    if sync_error is not None:
        warning_box.warning(
            workspace,
            "Queued With Warnings",
            f"The items were queued, but the view failed to refresh.\n\n{sync_error}",
        )
        return
    workspace.status_message.emit(_format_batch_result(result), 5000)


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
