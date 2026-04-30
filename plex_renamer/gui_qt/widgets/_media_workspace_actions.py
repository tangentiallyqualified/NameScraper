"""Action orchestration helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState
from ._media_workspace_action_bar import (
    set_roster_queue_button_text as _set_roster_queue_button_text,
    sync_action_button_metrics as _sync_action_button_metrics,
    update_action_bar as _update_action_bar,
)
from ._media_workspace_action_state import (
    can_fix_match as _can_fix_match,
    can_inline_approve as _can_inline_approve,
    can_inline_assign_season as _can_inline_assign_season,
    fix_match_label as _fix_match_label,
    media_noun as _media_noun,
    needs_inline_match_choice as _needs_inline_match_choice,
    primary_action_label as _primary_action_label,
    queue_selected_label as _queue_selected_label,
)
from ._media_workspace_match_actions import (
    apply_alternate_match as _apply_alternate_match,
    approve_match as _approve_match,
    fix_match as _fix_match,
    prompt_assign_season as _prompt_assign_season,
)
from ._media_workspace_queue_actions import (
    queue_checked as _queue_checked,
    queue_eligibility as _queue_eligibility,
    queue_selected_state as _queue_selected_state,
    queue_states as _queue_states,
    summarize_skip_reasons as _summarize_skip_reasons,
)


class MediaWorkspaceActionCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def queue_selected_state(self) -> None:
        _queue_selected_state(self._workspace)

    def activate_selected_primary_action(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None:
            workspace.status_message.emit(f"Select a {self.media_noun()} first.", 4000)
            return
        selected_preview = workspace._selected_preview()
        if selected_preview is not None and selected_preview.is_episode_review:
            self.approve_episode_mapping(state, selected_preview)
            return
        if self.can_inline_assign_season(state):
            workspace._prompt_assign_season(state)
            return
        if self.needs_inline_match_choice(state):
            workspace._fix_match()
            return
        if self.can_inline_approve(state):
            workspace._approve_match(state)
            return
        self.queue_selected_state()

    def queue_checked(self, *, question_box: Any = QMessageBox) -> None:
        _queue_checked(self._workspace, question_box=question_box)

    def summarize_skip_reasons(self, states: list[ScanState]) -> dict[str, int]:
        return _summarize_skip_reasons(self._workspace, states)

    def queue_states(
        self,
        states: list[ScanState],
        *,
        empty_message: str,
        warning_box: Any = QMessageBox,
    ) -> None:
        _queue_states(
            self._workspace,
            states,
            empty_message=empty_message,
            warning_box=warning_box,
        )

    def fix_match(
        self,
        *,
        match_picker_dialog: Any,
        warning_box: Any = QMessageBox,
    ) -> None:
        _fix_match(
            self._workspace,
            match_picker_dialog=match_picker_dialog,
            warning_box=warning_box,
        )

    def queue_eligibility(self, states: list[ScanState]):
        return _queue_eligibility(self._workspace, states)

    def update_action_bar(self) -> None:
        _update_action_bar(self._workspace)

    def set_roster_queue_button_text(self, text: str) -> None:
        _set_roster_queue_button_text(self._workspace, text)

    def sync_action_button_metrics(self) -> None:
        _sync_action_button_metrics(self._workspace)

    def approve_match(self, state: ScanState) -> None:
        _approve_match(self._workspace, state)

    def approve_episode_mapping(self, state: ScanState, preview) -> None:
        workspace = self._workspace
        if state.queued or state.scanning:
            workspace.status_message.emit("This episode cannot be approved in its current state.", 3000)
            return
        if not preview.is_episode_review:
            return
        preview.status = "OK"
        workspace._ensure_check_bindings(state)
        if state.checked:
            for index, item in enumerate(state.preview_items):
                binding = state.check_vars.get(str(index))
                if binding is not None and hasattr(binding, "set"):
                    binding.set(item.is_actionable and not item.is_review)
        workspace._populate_preview(state)
        workspace._update_action_bar()
        workspace.status_message.emit("Episode mapping approved.", 3000)

    def prompt_assign_season(
        self,
        state: ScanState,
        *,
        input_dialog: Any,
        warning_box: Any = QMessageBox,
    ) -> None:
        _prompt_assign_season(
            self._workspace,
            state,
            input_dialog=input_dialog,
            warning_box=warning_box,
        )

    def apply_alternate_match(
        self,
        state: ScanState,
        match: dict,
        *,
        warning_box: Any = QMessageBox,
    ) -> None:
        _apply_alternate_match(
            self._workspace,
            state,
            match,
            warning_box=warning_box,
        )

    def media_noun(self) -> str:
        return _media_noun(self._workspace)

    def queue_selected_label(self) -> str:
        return _queue_selected_label(self._workspace)

    def primary_action_label(self, state: ScanState | None) -> str:
        return _primary_action_label(self._workspace, state)

    def fix_match_label(self, state: ScanState | None) -> str:
        return _fix_match_label(self._workspace, state)

    def needs_inline_match_choice(self, state: ScanState) -> bool:
        return _needs_inline_match_choice(state)

    def can_inline_assign_season(self, state: ScanState) -> bool:
        return _can_inline_assign_season(self._workspace, state)

    def can_inline_approve(self, state: ScanState) -> bool:
        return _can_inline_approve(state)

    def can_fix_match(self, state: ScanState) -> bool:
        return _can_fix_match(state)
