"""Queue-oriented action workflows for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState
from ._media_helpers import (
    format_batch_result as _format_batch_result,
    is_plex_ready_state as _is_plex_ready_state,
    is_state_queue_approvable as _is_state_queue_approvable,
    roster_selection_key as _roster_selection_key,
)
from ._media_workspace_action_state import media_noun


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
    state.checked = True
    try:
        queue_states(
            workspace,
            [state],
            empty_message=f"Select a {media_noun(workspace)} before queueing.",
            warning_box=warning_box,
        )
    finally:
        if not state.queued:
            state.checked = original_checked


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
        elif _is_plex_ready_state(state):
            reasons["already Plex-ready"] = reasons.get("already Plex-ready", 0) + 1
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

    try:
        if workspace._media_type == "movie":
            root = workspace._media_ctrl.movie_folder
            if root is None:
                workspace.status_message.emit("No movie folder is loaded.", 4000)
                return
            result = workspace._queue_ctrl.add_movie_batch(
                states,
                root,
                workspace._media_ctrl.command_gating,
            )
        else:
            root = workspace._media_ctrl.tv_root_folder
            if root is None:
                workspace.status_message.emit("No TV folder is loaded.", 4000)
                return
            result = workspace._queue_ctrl.add_tv_batch(
                states,
                root,
                workspace._media_ctrl.command_gating,
            )
    except Exception as exc:
        warning_box.warning(workspace, "Queue Failed", str(exc))
        return

    workspace._media_ctrl.sync_queued_states()
    workspace.refresh_from_controller()
    workspace._restore_roster_selection_by_key(selected_key)
    workspace.queue_changed.emit()
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
