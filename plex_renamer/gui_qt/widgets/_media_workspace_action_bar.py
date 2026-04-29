"""Button-state orchestration for the media workspace action bar."""

from __future__ import annotations

from ...app.services.episode_mapping_service import EpisodeMappingService
from ...engine import ScanState
from ._media_helpers import is_state_queue_approvable as _is_state_queue_approvable
from ._media_workspace_action_state import (
    can_fix_match as _can_fix_match,
    can_inline_approve as _can_inline_approve,
    can_inline_assign_season as _can_inline_assign_season,
    fix_match_label as _fix_match_label,
    needs_inline_match_choice as _needs_inline_match_choice,
    primary_action_label as _primary_action_label,
)
from ._media_workspace_queue_actions import queue_eligibility as _queue_eligibility


def update_action_bar(workspace) -> None:
    states = workspace._current_states()
    checked = [state for state in states if state.checked]
    workspace._update_roster_selection_header(states)
    selected_state = workspace._selected_state()

    _update_fix_match_button(workspace, selected_state)
    _update_inline_action_button(workspace, selected_state)
    _update_checked_queue_button(workspace, checked)
    _update_queue_preflight(workspace, selected_state)

    if selected_state is not None:
        workspace._render_detail(selected_state, workspace._selected_preview())


def set_roster_queue_button_text(workspace, text: str) -> None:
    workspace._roster_panel.set_queue_button_text(text)
    sync_action_button_metrics(workspace)


def sync_action_button_metrics(workspace) -> None:
    if not hasattr(workspace, "_queue_inline_btn"):
        return
    button_height = max(
        workspace._queue_inline_btn.sizeHint().height(),
        workspace._roster_queue_btn.sizeHint().height(),
    )
    workspace._queue_inline_btn.setMinimumHeight(button_height)
    workspace._roster_queue_btn.setMinimumHeight(button_height)


def _update_fix_match_button(workspace, selected_state: ScanState | None) -> None:
    can_fix = bool(selected_state and _can_fix_match(selected_state))
    workspace._fix_match_btn.setEnabled(can_fix)
    workspace._fix_match_btn.setText(_fix_match_label(workspace, selected_state))
    if can_fix or selected_state is None:
        workspace._fix_match_btn.setToolTip("")
    elif selected_state.queued:
        workspace._fix_match_btn.setToolTip("Already queued items cannot be rematched.")
    elif selected_state.scanning:
        workspace._fix_match_btn.setToolTip("Wait for scanning to finish before fixing the match.")
    elif selected_state.show_id is None and not selected_state.search_results:
        workspace._fix_match_btn.setToolTip("No source results are available to choose from.")
    else:
        workspace._fix_match_btn.setToolTip("This match cannot be changed right now.")


def _update_inline_action_button(workspace, selected_state: ScanState | None) -> None:
    workspace._queue_inline_btn.setText(_primary_action_label(workspace, selected_state))
    if selected_state is None:
        workspace._queue_inline_btn.setEnabled(False)
        workspace._queue_inline_btn.setToolTip("")
        return

    if (
        _can_inline_assign_season(workspace, selected_state)
        or _needs_inline_match_choice(selected_state)
        or _can_inline_approve(selected_state)
    ):
        workspace._queue_inline_btn.setEnabled(True)
        workspace._queue_inline_btn.setToolTip("")
        return

    approvable = _is_state_queue_approvable(selected_state, media_type=workspace._media_type)
    workspace._queue_inline_btn.setEnabled(approvable)
    if approvable:
        workspace._queue_inline_btn.setToolTip("")
        return

    inline_eligibility = _queue_eligibility(workspace, [selected_state])
    workspace._queue_inline_btn.setToolTip(inline_eligibility.reason or "")


def _update_checked_queue_button(workspace, checked: list[ScanState]) -> None:
    if checked:
        eligibility = _queue_eligibility(workspace, checked)
        set_roster_queue_button_text(workspace, f"Queue {len(checked)} Checked")
        workspace._roster_queue_btn.setEnabled(eligibility.enabled)
        workspace._roster_queue_btn.setToolTip("" if eligibility.enabled else (eligibility.reason or ""))
        return

    set_roster_queue_button_text(workspace, "Queue Checked")
    workspace._roster_queue_btn.setEnabled(False)
    workspace._roster_queue_btn.setToolTip("Check at least one item to queue.")


def _update_queue_preflight(workspace, selected_state: ScanState | None) -> None:
    label = getattr(workspace, "_queue_preflight_label", None)
    if label is None:
        return
    if workspace._media_type != "tv" or selected_state is None or selected_state.show_id is None:
        label.clear()
        label.hide()
        return
    preflight = EpisodeMappingService().build_queue_preflight(selected_state)
    label.setText("Queue preflight: " + preflight.summary_text)
    label.show()
