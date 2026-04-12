"""Action orchestration helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState, score_tv_results
from ...parsing import best_tv_match_title, clean_folder_name, extract_year
from ._media_helpers import (
    format_batch_result as _format_batch_result,
    is_plex_ready_state as _is_plex_ready_state,
    is_state_queue_approvable as _is_state_queue_approvable,
    roster_selection_key as _roster_selection_key,
)


class MediaWorkspaceActionCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def queue_selected_state(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None:
            workspace.status_message.emit(f"Select a {self.media_noun()} before queueing.", 4000)
            return
        if not _is_state_queue_approvable(state, media_type=workspace._media_type):
            workspace.status_message.emit(f"This {self.media_noun()} is not approved for queueing.", 4000)
            return
        original_checked = state.checked
        state.checked = True
        try:
            self.queue_states([state], empty_message=f"Select a {self.media_noun()} before queueing.")
        finally:
            if not state.queued:
                state.checked = original_checked

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
        workspace = self._workspace
        checked = [state for state in workspace._current_states() if state.checked]
        if not checked:
            workspace.status_message.emit("Select at least one actionable item before queueing.", 4000)
            return
        eligible = [state for state in checked if _is_state_queue_approvable(state, media_type=workspace._media_type)]
        skipped = len(checked) - len(eligible)
        if skipped and eligible:
            skip_reasons = self.summarize_skip_reasons(checked)
            detail = ", ".join(f"{count} {reason}" for reason, count in skip_reasons.items())
            answer = question_box.question(
                workspace,
                "Queue Checked Items",
                f"Queueing {len(eligible)} of {len(checked)} checked — {detail} will be skipped.\n\nProceed?",
            )
            if answer != question_box.StandardButton.Yes:
                return
        self.queue_states(checked, empty_message="Select at least one actionable item before queueing.")

    def summarize_skip_reasons(self, states: list[ScanState]) -> dict[str, int]:
        workspace = self._workspace
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
        self,
        states: list[ScanState],
        *,
        empty_message: str,
        warning_box: Any = QMessageBox,
    ) -> None:
        workspace = self._workspace
        if workspace._media_ctrl is None or workspace._queue_ctrl is None:
            return
        if not states:
            workspace.status_message.emit(empty_message, 4000)
            return

        selected_key = _roster_selection_key(workspace._selected_state())
        eligibility = self.queue_eligibility(states)
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
                result = workspace._queue_ctrl.add_movie_batch(states, root, workspace._media_ctrl.command_gating)
            else:
                root = workspace._media_ctrl.tv_root_folder
                if root is None:
                    workspace.status_message.emit("No TV folder is loaded.", 4000)
                    return
                result = workspace._queue_ctrl.add_tv_batch(states, root, workspace._media_ctrl.command_gating)
        except Exception as exc:
            warning_box.warning(workspace, "Queue Failed", str(exc))
            return

        workspace._media_ctrl.sync_queued_states()
        workspace.refresh_from_controller()
        workspace._restore_roster_selection_by_key(selected_key)
        workspace.queue_changed.emit()
        workspace.status_message.emit(_format_batch_result(result), 5000)

    def fix_match(
        self,
        *,
        match_picker_dialog: Any,
        warning_box: Any = QMessageBox,
    ) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or workspace._media_ctrl is None or workspace._tmdb_provider is None:
            return
        if state.queued:
            workspace.status_message.emit("Remove the item from the queue before changing its match.", 4000)
            return

        tmdb = workspace._tmdb_provider()
        if tmdb is None:
            workspace.status_message.emit("TMDB is unavailable.", 4000)
            return

        if workspace._media_type == "movie":
            query_source = state.preview_items[0].original.stem if state.preview_items else state.folder.name
            title_key = "title"
            search_callback = tmdb.search_movie
            dialog_title = f"{self.fix_match_label(state)}: {query_source}"
            score_results_callback = None
        else:
            query_source = state.folder.name
            title_key = "name"
            search_callback = tmdb.search_tv
            dialog_title = f"{self.fix_match_label(state)}: {state.folder.name}"

        query = (
            best_tv_match_title(state.folder, include_year=False)
            if workspace._media_type == "tv"
            else clean_folder_name(query_source, include_year=False)
        )
        year_hint = extract_year(query_source)
        if workspace._media_type == "tv":
            score_results_callback = lambda results: score_tv_results(
                results,
                query,
                year_hint,
                tmdb,
                folder=state.folder,
            )

        chosen = match_picker_dialog.pick(
            title=dialog_title,
            title_key=title_key,
            initial_query=query,
            initial_results=state.search_results,
            search_callback=search_callback,
            score_results_callback=score_results_callback,
            year_hint=year_hint,
            raw_name=query,
            parent=workspace,
        )
        if not chosen:
            return

        self._apply_selected_match(state, chosen, tmdb=tmdb, warning_box=warning_box)

    def queue_eligibility(self, states: list[ScanState]):
        workspace = self._workspace
        if not states:
            return workspace._media_ctrl.command_gating.summarize_scan_states([], require_resolved_review=True)
        return workspace._media_ctrl.command_gating.summarize_scan_states(
            states,
            require_resolved_review=True,
            allow_show_level_queue=workspace._media_type == "tv",
        )

    def update_action_bar(self) -> None:
        workspace = self._workspace
        states = workspace._current_states()
        checked = [state for state in states if state.checked]
        workspace._update_roster_selection_header(states)
        selected_state = workspace._selected_state()
        can_fix = bool(selected_state and self.can_fix_match(selected_state))
        workspace._fix_match_btn.setEnabled(can_fix)
        workspace._fix_match_btn.setText(self.fix_match_label(selected_state))
        workspace._fix_match_btn.setToolTip("")
        workspace._queue_inline_btn.setText(self.primary_action_label(selected_state))
        if selected_state is None:
            workspace._queue_inline_btn.setEnabled(False)
            workspace._queue_inline_btn.setToolTip("")
        else:
            if (
                self.can_inline_assign_season(selected_state)
                or self.needs_inline_match_choice(selected_state)
                or self.can_inline_approve(selected_state)
            ):
                workspace._queue_inline_btn.setEnabled(True)
                workspace._queue_inline_btn.setToolTip("")
            else:
                approvable = _is_state_queue_approvable(selected_state, media_type=workspace._media_type)
                workspace._queue_inline_btn.setEnabled(approvable)
                if approvable:
                    workspace._queue_inline_btn.setToolTip("")
                else:
                    inline_eligibility = self.queue_eligibility([selected_state])
                    workspace._queue_inline_btn.setToolTip(inline_eligibility.reason or "")
        if checked:
            eligibility = self.queue_eligibility(checked)
            self.set_roster_queue_button_text(f"Queue {len(checked)} Checked")
            workspace._roster_queue_btn.setEnabled(eligibility.enabled)
            workspace._roster_queue_btn.setToolTip("" if eligibility.enabled else (eligibility.reason or ""))
        else:
            self.set_roster_queue_button_text("Queue Checked")
            workspace._roster_queue_btn.setEnabled(False)
            workspace._roster_queue_btn.setToolTip("Check at least one item to queue.")
        if selected_state is not None:
            workspace._render_detail(selected_state, workspace._selected_preview())

    def set_roster_queue_button_text(self, text: str) -> None:
        workspace = self._workspace
        workspace._roster_panel.set_queue_button_text(text)
        self.sync_action_button_metrics()

    def sync_action_button_metrics(self) -> None:
        workspace = self._workspace
        if not hasattr(workspace, "_queue_inline_btn"):
            return
        button_height = max(workspace._queue_inline_btn.sizeHint().height(), workspace._roster_queue_btn.sizeHint().height())
        workspace._queue_inline_btn.setMinimumHeight(button_height)
        workspace._roster_queue_btn.setMinimumHeight(button_height)

    def approve_match(self, state: ScanState) -> None:
        workspace = self._workspace
        if workspace._media_ctrl is None:
            return
        if state.duplicate_of is not None or state.queued or state.scanning:
            workspace.status_message.emit("This item cannot be approved in its current state.", 3000)
            return
        workspace._media_ctrl.approve_match(state)
        workspace.refresh_from_controller()
        workspace.status_message.emit("Match approved.", 3000)

    def prompt_assign_season(
        self,
        state: ScanState,
        *,
        input_dialog: Any,
        warning_box: Any = QMessageBox,
    ) -> None:
        workspace = self._workspace
        if workspace._media_ctrl is None:
            return
        current = state.season_assignment or 1
        season_num, ok = input_dialog.getInt(
            workspace,
            "Assign Season",
            f"Season number for \"{state.display_name}\":",
            current,
            0,
            99,
        )
        if not ok:
            return
        effective_state = workspace._media_ctrl.assign_season(
            state,
            season_num if season_num > 0 else None,
        )
        workspace.refresh_from_controller()
        follow_up_state = effective_state if effective_state is not None else state
        workspace._restore_roster_selection_by_key(_roster_selection_key(follow_up_state))
        if (
            workspace._media_type == "tv"
            and season_num > 0
            and follow_up_state.show_id is not None
        ):
            tmdb = workspace._tmdb_provider() if workspace._tmdb_provider is not None else None
            if tmdb is not None:
                try:
                    workspace._media_ctrl.scan_show(follow_up_state, tmdb)
                except Exception as exc:
                    warning_box.warning(workspace, "Scan Failed", str(exc))
                if follow_up_state.scanned or follow_up_state.preview_items:
                    workspace.refresh_from_controller()
                    workspace._restore_roster_selection_by_key(_roster_selection_key(follow_up_state))
        label = f"Season {season_num}" if season_num > 0 else "cleared"
        workspace.status_message.emit(f"Season assignment: {label}.", 3000)

    def apply_alternate_match(
        self,
        state: ScanState,
        match: dict,
        *,
        warning_box: Any = QMessageBox,
    ) -> None:
        self._apply_selected_match(state, match, warning_box=warning_box)

    def media_noun(self) -> str:
        return "movie" if self._workspace._media_type == "movie" else "show"

    def queue_selected_label(self) -> str:
        return f"Queue This {'Movie' if self._workspace._media_type == 'movie' else 'Show'}"

    def primary_action_label(self, state: ScanState | None) -> str:
        if state is not None and self.can_inline_assign_season(state):
            return "Assign Season"
        if state is not None and self.needs_inline_match_choice(state):
            return "Choose Match"
        if state is not None and self.can_inline_approve(state):
            return "Approve Match"
        return self.queue_selected_label()

    def fix_match_label(self, state: ScanState | None) -> str:
        if state is not None and self.needs_inline_match_choice(state):
            return "Choose Match"
        return "Fix Match"

    def needs_inline_match_choice(self, state: ScanState) -> bool:
        return (
            state.show_id is not None
            and state.tie_detected
            and state.needs_review
            and not state.queued
            and not state.scanning
            and state.duplicate_of is None
        )

    def can_inline_assign_season(self, state: ScanState) -> bool:
        return (
            self._workspace._media_type == "tv"
            and state.show_id is not None
            and state.duplicate_of is not None
            and state.season_assignment is None
            and not state.queued
            and not state.scanning
        )

    def can_inline_approve(self, state: ScanState) -> bool:
        return (
            state.show_id is not None
            and state.needs_review
            and not state.tie_detected
            and not state.queued
            and not state.scanning
            and state.duplicate_of is None
        )

    def can_fix_match(self, state: ScanState) -> bool:
        return not state.queued and not state.scanning

    def _apply_selected_match(
        self,
        state: ScanState,
        chosen: dict,
        *,
        tmdb: Any = None,
        warning_box: Any = QMessageBox,
    ) -> None:
        workspace = self._workspace
        if workspace._media_ctrl is None:
            return
        selected_key = _roster_selection_key(state)
        try:
            if workspace._media_type == "movie":
                workspace._media_ctrl.rematch_movie_state(state, chosen)
                workspace.refresh_from_controller()
                workspace._restore_roster_selection_by_key(selected_key)
                workspace.status_message.emit(f"Updated match to {state.display_name}.", 4000)
                return

            active_tmdb = tmdb
            if active_tmdb is None and workspace._tmdb_provider is not None:
                active_tmdb = workspace._tmdb_provider()
            if active_tmdb is None:
                workspace.status_message.emit("TMDB is unavailable.", 4000)
                return

            updated_state = workspace._media_ctrl.rematch_tv_state(state, chosen, active_tmdb)
            self._finish_tv_rematch(updated_state, active_tmdb)
        except Exception as exc:
            warning_box.warning(workspace, "Fix Match Failed", str(exc))

    def _finish_tv_rematch(self, updated_state: ScanState, tmdb: Any) -> None:
        workspace = self._workspace
        workspace.refresh_from_controller()
        workspace._restore_roster_selection_by_key(_roster_selection_key(updated_state))
        workspace._media_ctrl.scan_show(updated_state, tmdb)
        if updated_state.scanned or updated_state.preview_items:
            workspace.refresh_from_controller()
            workspace._restore_roster_selection_by_key(_roster_selection_key(updated_state))
        workspace.status_message.emit(f"Re-matching {updated_state.display_name}...", 4000)

