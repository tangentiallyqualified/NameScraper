"""Action orchestration helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QMessageBox,
)

from ..._parsing_parts import split_part_marker
from ...app.services.command_gating_service import CommandGatingService
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
    switch_source as _switch_source,
)
from ._media_workspace_queue_actions import (
    queue_checked as _queue_checked,
    queue_eligibility as _queue_eligibility,
    queue_selected_state as _queue_selected_state,
    queue_states as _queue_states,
    summarize_skip_reasons as _summarize_skip_reasons,
)
from .busy_overlay import busy_scope
from .episode_assign_dialog import EpisodeAssignDialog


def _refresh_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "refresh_episode_guide"):
        media_ctrl.refresh_episode_guide(state)


class MediaWorkspaceActionCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace
        # The state bulk-assign mode was entered on; Apply commits against
        # this state (not the live roster selection), and a populate with a
        # different state discards the session. None while inactive.
        self._bulk_state: ScanState | None = None

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

    def switch_source(self, provider_name: str) -> None:
        _switch_source(self._workspace, provider_name)

    def _auto_check_for_queue(self, state: ScanState) -> None:
        """Pre-tick a show for queueing after Approve All.

        Sets every actionable item's check binding and the state-level checked
        flag. refresh_from_controller's normalize_queue_selection keeps these
        when the state is queue-approvable, or clears them if a conflict or
        unmapped file still blocks it (the show then stays in review).
        """
        workspace = self._workspace
        workspace._ensure_check_bindings(state)
        for index in range(len(state.preview_items)):
            binding = state.check_vars.get(str(index))
            if binding is not None and CommandGatingService.is_queue_relevant(state, index):
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

    def unassign_all_episode_mappings(self, *, warning_box: Any = QMessageBox) -> None:
        """Danger-treated Unassign All: exact-count confirm + bulk-assign offer."""
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        if state.assignments is None:
            return
        count = len(state.assignments.assignments())
        if count == 0:
            return
        if warning_box is QMessageBox:
            box = QMessageBox(workspace)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Unassign All")
            box.setText(
                f"Unassign all {count} assigned file(s) for {state.display_name}?\n"
                "Every episode mapping for this show will be cleared."
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.YesToAll
                | QMessageBox.StandardButton.Cancel
            )
            box.button(QMessageBox.StandardButton.Yes).setText("Unassign All")
            box.button(QMessageBox.StandardButton.YesToAll).setText("Unassign && Bulk Assign…")
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            answer = box.exec()
        else:
            answer = warning_box.question(
                workspace,
                "Unassign All",
                f"Unassign all {count} assigned file(s) for {state.display_name}?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.YesToAll
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
        if answer not in (
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.YesToAll,
        ):
            return
        with busy_scope(workspace._work_panel, "Unassigning all…", immediate=True):
            unassigned = EpisodeMappingService().unassign_all(state)
            if unassigned == 0:
                return
            _refresh_episode_projection(workspace, state)
            workspace.refresh_from_controller()
        workspace.status_message.emit(f"Unassigned {unassigned} file(s).", 3000)
        if answer == QMessageBox.StandardButton.YesToAll:
            self.enter_bulk_assign()

    def enter_bulk_assign(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        if workspace._media_type == "movie" or state.assignments is None:
            return
        panel = workspace._work_panel
        self._bulk_state = state
        panel.bulk_panel.show_state(state, EpisodeMappingService())
        panel.enter_bulk_assign()

    def apply_bulk_assignments(
        self,
        pairs: list[tuple[int, int, int]],
        unassign_file_ids: list[int] | None = None,
    ) -> None:
        workspace = self._workspace
        unassign_file_ids = list(unassign_file_ids or [])
        # Commit against the state bulk mode was entered on: the staged
        # file_ids/slot keys are only meaningful against that state's table.
        state = self._bulk_state
        self._bulk_state = None
        panel = workspace._work_panel
        panel.exit_bulk_assign()
        if state is None:
            return
        # Bulk Assign v2: assign pairs and unassigns applied together in one
        # reproject via apply_bulk.
        if not pairs and not unassign_file_ids:
            return
        if state.assignments is None:
            workspace.status_message.emit("No assignments were applied.", 4000)
            return
        with busy_scope(workspace._work_panel, "Applying assignments…", immediate=True):
            applied, skipped = EpisodeMappingService().apply_bulk(
                state,
                assign_pairs=pairs,
                unassign_file_ids=unassign_file_ids,
            )
            _refresh_episode_projection(workspace, state)
            workspace.refresh_from_controller()
        tone = "error" if skipped else "success"
        parts = []
        if applied:
            parts.append(f"Assigned {applied} file(s).")
        if unassign_file_ids:
            parts.append(f"Unassigned {len(unassign_file_ids)} file(s).")
        if skipped:
            parts.append(f"{skipped} skipped (slot already claimed or no longer valid).")
        message = " ".join(parts) if parts else "No assignments were applied."
        workspace.toast_requested.emit("Bulk Assign", message, tone)

    def cancel_bulk_assign(self) -> None:
        workspace = self._workspace
        self._bulk_state = None
        workspace._work_panel.exit_bulk_assign()
        workspace.status_message.emit("Bulk Assign cancelled - nothing was changed.", 3000)

    def discard_bulk_assign_on_state_change(self, state: ScanState | None) -> None:
        """Exit bulk mode when the work panel is populated with a different
        state than the one bulk mode was entered on (roster switch, or a
        rescan replacing the state object). Same-state repopulates keep the
        mode: staging staleness up to Apply/Cancel is the plan's boundary.
        """
        workspace = self._workspace
        panel = workspace._work_panel
        if not panel.bulk_assign_active() or state is self._bulk_state:
            return
        self._bulk_state = None
        panel.bulk_panel.reset_staging()
        panel.exit_bulk_assign()
        workspace.status_message.emit("Bulk Assign discarded - selection changed.", 3000)

    def assign_unmapped_file(
        self,
        state: ScanState,
        preview,
        *,
        warning_box: Any = QMessageBox,
        assign_dialog: Any = EpisodeAssignDialog,
    ) -> None:
        """Assign an unmapped/duplicate primary file to episode slot(s) (R2 M2)."""
        workspace = self._workspace
        if state.queued or state.scanning:
            workspace.status_message.emit(
                "Finish or cancel the queued/scanning state first.",
                3000,
            )
            return
        service = EpisodeMappingService()
        slots = service.episode_slot_choices(state)
        if not slots:
            workspace.status_message.emit("No episode choices are available.", 4000)
            return
        selection = assign_dialog.pick_episodes(
            parent=workspace,
            title="Assign File",
            slots=slots,
            preselected=None,
            current_keys=None,
            file_label=preview.original.name,
        )
        if selection is None:
            return
        season = selection[0][0]
        episodes = [episode for _season, episode in selection]
        try:
            service.assign_file(state, preview, season=season, episodes=episodes)
        except ValueError as exc:
            warning_box.warning(workspace, "Episode Assignment Failed", str(exc))
            return
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        workspace.status_message.emit("File assigned.", 3000)

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
                "Finish or cancel the queued/scanning state first.",
                3000,
            )
            return
        service = EpisodeMappingService()
        preview = row.primary_file
        try:
            if action_id == "approve" and preview is not None:
                try:
                    p_index = state.preview_items.index(preview)
                except ValueError:
                    p_index = -1
                if p_index in state.merge_gate_errors:
                    workspace.status_message.emit(
                        f"Cannot approve: {state.merge_gate_errors[p_index]}", 5000
                    )
                    return
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
                    choice
                    for choice in service.episode_slot_choices(state)
                    if choice.season == season and choice.episode in relevant
                ]
                # slots always includes the run itself; need a neighbor to extend into.
                if len(slots) <= len(run):
                    workspace.status_message.emit(
                        "No adjacent episode to extend into.",
                        4000,
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
                    state,
                    season=row.season,
                    episode=row.episode,
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
                    state,
                    target,
                    season=row.season,
                    episode=row.episode,
                )
                message = "File assigned."
            elif action_id == "merge_parts":
                table = state.assignments
                if table is None:
                    workspace.status_message.emit(
                        "Need at least two files claiming this episode to merge.", 4000
                    )
                    return
                claims = table.claims(row.season, row.episode)
                # M1: part_marker is only backfilled when auto-detection
                # GROUPED the files -- merge_parts is exactly the manual
                # path taken when detection declined, so it is unset here
                # more often than not. Parse the marker live from the
                # filename instead of trusting it, or "Part 10" sorts
                # before "Part 2" (lexicographic name fallback).
                ordered = sorted(
                    (claim.file_id for claim in claims),
                    key=lambda fid: (
                        split_part_marker(table.files[fid].path.stem)[1] or 99,
                        table.files[fid].path.name.casefold(),
                    ),
                )
                if len(ordered) < 2:
                    workspace.status_message.emit(
                        "Need at least two files claiming this episode to merge.", 4000
                    )
                    return
                service.merge_files(state, ordered, season=row.season, episodes=[row.episode])
                message = f"Merged {len(ordered)} parts into one episode."
            elif action_id == "ungroup" and preview is not None:
                service.ungroup_file(state, preview)
                message = "Parts ungrouped."
            else:
                return
        except ValueError as exc:
            warning_box.warning(workspace, "Episode Assignment Failed", str(exc))
            return
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(message, 3000)

    def toggle_episode_mux_optout(self, state: ScanState, preview_index: int) -> None:
        """Flip this episode's session-scoped AutoMux opt-out (round5 §4b).

        No persistence: the exclusion lives only on ``state.mux_opt_outs`` and
        is honored at queue time by ``effective_mux_plans``. Refreshes the
        collapsed rows' MUX pill, the roster chip, the header toggle button,
        and the open expansion card so every surface follows immediately."""
        workspace = self._workspace
        if state.queued or state.scanning:
            workspace.status_message.emit(
                "Finish or cancel the queued/scanning state first.",
                3000,
            )
            return
        if preview_index in state.mux_opt_outs:
            state.mux_opt_outs.discard(preview_index)
        else:
            state.mux_opt_outs.add(preview_index)
        workspace._work_panel.model.refresh_row_data(state)
        workspace._automux._refresh_roster_row(state)
        if state is workspace._selected_state():
            workspace._automux.update_button(state)
        workspace._state_coordinator.refresh_expansion_card()

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
