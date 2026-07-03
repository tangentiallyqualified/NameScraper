"""Action orchestration helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QMessageBox,
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
    can_unassign_all as _can_unassign_all,
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
from .episode_assign_dialog import EpisodeAssignDialog


def _refresh_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "refresh_episode_guide"):
        media_ctrl.refresh_episode_guide(state)


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

    def _auto_check_for_queue(self, state: ScanState) -> None:
        """Pre-tick a show for queueing after Approve All.

        Sets every actionable item's check binding and the state-level checked
        flag. refresh_from_controller's normalize_queue_selection keeps these
        when the state is queue-approvable, or clears them if a conflict or
        unmapped file still blocks it (the show then stays in review).
        """
        workspace = self._workspace
        workspace._ensure_check_bindings(state)
        for index, item in enumerate(state.preview_items):
            binding = state.check_vars.get(str(index))
            if binding is not None and item.is_actionable:
                binding.set(True)
        state.checked = True

    def approve_all_episode_mappings(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        service = EpisodeMappingService()
        if state.assignments is not None:
            try:
                count = service.approve_all(state)
            except ValueError:
                return
            if count == 0:
                return
        else:
            # Legacy path: no assignment table — mutate status directly.
            count = 0
            for preview in state.preview_items:
                if not preview.is_episode_review:
                    continue
                preview.status = "OK"
                count += 1
            if count == 0:
                return
        _refresh_episode_projection(workspace, state)
        self._auto_check_for_queue(state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(f"Approved {count} episode mapping(s).", 3000)

    def unassign_all_episode_mappings(self) -> None:
        """Unassign every currently-assigned file in the selected show.

        Reuses the same per-file unassign path used by the episode row
        ``unassign`` action so the bulk action stays in lock-step with it.
        """
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        if state.assignments is None:
            return
        service = EpisodeMappingService()
        assigned_previews = [
            preview
            for preview in state.preview_items
            if preview.file_id is not None
            and state.assignments.assignment_for(preview.file_id) is not None
        ]
        if not assigned_previews:
            return
        count = 0
        for preview in assigned_previews:
            try:
                service.unassign_file(state, preview)
            except ValueError:
                continue
            count += 1
        if count == 0:
            return
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(f"Unassigned {count} file(s).", 3000)

    def handle_episode_row_action(
        self,
        state: ScanState,
        row,
        action_id: str,
        *,
        warning_box: Any = QMessageBox,
        assign_dialog: Any = EpisodeAssignDialog,
    ) -> None:
        workspace = self._workspace
        if state.queued or state.scanning:
            workspace.status_message.emit(
                "Finish or cancel the queued/scanning state first.", 3000,
            )
            return
        service = EpisodeMappingService()
        preview = row.primary_file
        try:
            if action_id == "approve" and preview is not None:
                service.approve_file(state, preview)
                message = "Episode mapping approved."
            elif action_id == "unassign" and preview is not None:
                service.unassign_file(state, preview)
                message = "File unassigned."
            elif action_id == "keep_this" and preview is not None:
                service.resolve_conflict(state, row.season, row.episode, preview)
                message = "Conflict resolved."
            elif action_id == "reassign" and preview is not None:
                slots = service.episode_slot_choices(state)
                if not slots:
                    workspace.status_message.emit("No episode choices are available.", 4000)
                    return
                current_keys = {
                    (preview.season, episode)
                    for episode in preview.episodes
                    if preview.season is not None
                }
                selection = assign_dialog.pick_episodes(
                    parent=workspace,
                    title="Reassign Episode",
                    slots=slots,
                    preselected=None,
                    current_keys=current_keys or None,
                    file_label=preview.original.name,
                )
                if selection is None:
                    return
                season = selection[0][0]
                episodes = [episode for _season, episode in selection]
                service.assign_file(state, preview, season=season, episodes=episodes)
                message = "Episode mapping updated."
            elif action_id == "assign_to_more" and preview is not None:
                if preview.season is None or not preview.episodes:
                    return
                season = preview.season
                run = sorted(preview.episodes)
                relevant = set(run) | {run[0] - 1, run[-1] + 1}
                slots = [
                    choice for choice in service.episode_slot_choices(state)
                    if choice.season == season and choice.episode in relevant
                ]
                # slots always includes the run itself; need a neighbor to extend into.
                if len(slots) <= len(run):
                    workspace.status_message.emit(
                        "No adjacent episode to extend into.", 4000,
                    )
                    return
                current_keys = {(season, episode) for episode in run}
                selection = assign_dialog.pick_episodes(
                    parent=workspace,
                    title="Assign to More Episodes",
                    slots=slots,
                    preselected=[(season, episode) for episode in run],
                    current_keys=current_keys,
                    file_label=preview.original.name,
                )
                if selection is None:
                    return
                episodes = sorted(set(run) | {episode for _season, episode in selection})
                service.assign_file(state, preview, season=season, episodes=episodes)
                message = "File extended to additional episode(s)."
            elif action_id == "assign_file":
                unassigned = service.unassigned_file_choices(state)
                unassigned_ids = {fid for fid, _label in unassigned}
                shareable = service.shareable_file_choices(
                    state, season=row.season, episode=row.episode,
                )
                shareable_ids = {fid for fid, _label in shareable}
                assigned = [
                    (item.file_id, item.original.name)
                    for item in state.preview_items
                    if item.file_id is not None
                    and item.new_name is not None
                    and item.file_id not in unassigned_ids
                    and item.file_id not in shareable_ids
                ]
                file_id = assign_dialog.pick_file(
                    parent=workspace,
                    title=f"Assign file to S{row.season:02d}E{row.episode:02d}",
                    unassigned=unassigned,
                    assigned=assigned,
                    shareable=shareable,
                )
                if file_id is None:
                    return
                target = next(
                    (item for item in state.preview_items if item.file_id == file_id),
                    None,
                )
                if target is None:
                    return
                service.assign_or_extend_file(
                    state, target, season=row.season, episode=row.episode,
                )
                message = "File assigned."
            else:
                return
        except ValueError as exc:
            warning_box.warning(workspace, "Episode Assignment Failed", str(exc))
            return
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(message, 3000)

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

    def can_unassign_all(self, state: ScanState | None) -> bool:
        return _can_unassign_all(state)
