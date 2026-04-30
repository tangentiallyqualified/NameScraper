"""Action orchestration helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from ...app.services.episode_mapping_service import EpisodeMappingService
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


class EpisodeChoiceDialog:
    """List-based episode picker used instead of a fragile combo popup."""

    @staticmethod
    def pick(
        *,
        parent,
        title: str,
        prompt: str,
        choices: list[tuple[str, int, int]],
        current_index: int = 0,
    ) -> tuple[int, int] | None:
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        prompt_label = QLabel(prompt)
        prompt_label.setWordWrap(True)
        layout.addWidget(prompt_label)

        list_widget = QListWidget()
        for label, season, episode in choices:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (season, episode))
            list_widget.addItem(item)
        if choices:
            list_widget.setCurrentRow(max(0, min(current_index, len(choices) - 1)))
        list_widget.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item = list_widget.currentItem()
        if item is None:
            return None
        selected = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(selected, tuple) or len(selected) != 2:
            return None
        return int(selected[0]), int(selected[1])


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

    def approve_all_episode_mappings(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        approved = 0
        for preview in state.preview_items:
            if not preview.is_episode_review:
                continue
            preview.status = "OK"
            approved += 1
        if approved == 0:
            return
        workspace._ensure_check_bindings(state)
        workspace._populate_preview(state)
        workspace._update_action_bar()
        workspace.status_message.emit(f"Approved {approved} episode mapping(s).", 3000)

    def prompt_fix_episode_mapping(
        self,
        state: ScanState,
        preview,
        *,
        input_dialog: Any,
        warning_box: Any = QMessageBox,
    ) -> None:
        workspace = self._workspace
        if state.queued or state.scanning or not preview.is_episode_review:
            workspace.status_message.emit("This episode cannot be fixed in its current state.", 3000)
            return
        service = EpisodeMappingService()
        choices = service.episode_choices(state)
        if not choices:
            workspace.status_message.emit("No episode choices are available for this show.", 4000)
            return
        current_index = 0
        if preview.season is not None and preview.episodes:
            current_key = (preview.season, preview.episodes[0])
            for index, (_label, season, episode) in enumerate(choices):
                if (season, episode) == current_key:
                    current_index = index
                    break
        selected = EpisodeChoiceDialog.pick(
            parent=workspace,
            title="Fix Episode",
            prompt=f"Episode for \"{preview.original.name}\":",
            choices=choices,
            current_index=current_index,
        )
        if selected is None:
            return
        season, episode = selected
        try:
            service.remap_preview_to_episode(state, preview, season=season, episode=episode)
        except Exception as exc:
            warning_box.warning(workspace, "Fix Episode Failed", str(exc))
            return
        workspace._ensure_check_bindings(state)
        workspace._populate_preview(state)
        workspace._update_action_bar()
        workspace.status_message.emit("Episode mapping updated.", 3000)

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
