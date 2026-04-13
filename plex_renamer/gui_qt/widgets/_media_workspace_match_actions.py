"""Rematch and approval workflows for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState, score_tv_results
from ...parsing import best_tv_match_title, clean_folder_name, extract_year
from ._media_helpers import roster_selection_key as _roster_selection_key
from ._media_workspace_action_state import fix_match_label


def fix_match(
    workspace,
    *,
    match_picker_dialog: Any,
    warning_box: Any = QMessageBox,
) -> None:
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
        dialog_title = f"{fix_match_label(workspace, state)}: {query_source}"
        score_results_callback = None
    else:
        query_source = state.folder.name
        title_key = "name"
        search_callback = tmdb.search_tv
        dialog_title = f"{fix_match_label(workspace, state)}: {state.folder.name}"

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

    apply_selected_match(workspace, state, chosen, tmdb=tmdb, warning_box=warning_box)


def approve_match(workspace, state: ScanState) -> None:
    if workspace._media_ctrl is None:
        return
    if state.duplicate_of is not None or state.queued or state.scanning:
        workspace.status_message.emit("This item cannot be approved in its current state.", 3000)
        return
    workspace._media_ctrl.approve_match(state)
    workspace.refresh_from_controller()
    workspace.status_message.emit("Match approved.", 3000)


def prompt_assign_season(
    workspace,
    state: ScanState,
    *,
    input_dialog: Any,
    warning_box: Any = QMessageBox,
) -> None:
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
    workspace,
    state: ScanState,
    match: dict,
    *,
    warning_box: Any = QMessageBox,
) -> None:
    apply_selected_match(workspace, state, match, warning_box=warning_box)


def apply_selected_match(
    workspace,
    state: ScanState,
    chosen: dict,
    *,
    tmdb: Any = None,
    warning_box: Any = QMessageBox,
) -> None:
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
        finish_tv_rematch(workspace, updated_state, active_tmdb)
    except Exception as exc:
        warning_box.warning(workspace, "Fix Match Failed", str(exc))


def finish_tv_rematch(workspace, updated_state: ScanState, tmdb: Any) -> None:
    workspace.refresh_from_controller()
    workspace._restore_roster_selection_by_key(_roster_selection_key(updated_state))
    workspace._media_ctrl.scan_show(updated_state, tmdb)
    if updated_state.scanned or updated_state.preview_items:
        workspace.refresh_from_controller()
        workspace._restore_roster_selection_by_key(_roster_selection_key(updated_state))
    workspace.status_message.emit(f"Re-matching {updated_state.display_name}...", 4000)
