"""Rematch and approval workflows for the media workspace."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QMessageBox

from ...engine import ScanState, score_tv_results
from ...parsing import best_tv_match_title, clean_folder_name, extract_year
from ._media_helpers import roster_selection_key as _roster_selection_key
from ._media_workspace_action_state import fix_match_label


def _invalidate_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "invalidate_episode_guide"):
        media_ctrl.invalidate_episode_guide(state)


def _refresh_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "refresh_episode_guide"):
        media_ctrl.refresh_episode_guide(state)


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
        workspace.status_message.emit(
            "Remove the item from the queue before changing its match.", 4000
        )
        return

    tmdb = workspace._tmdb_provider()
    if tmdb is None:
        workspace.status_message.emit("Metadata source is unavailable.", 4000)
        return

    score_results_callback: Callable[[Any], list[tuple[dict, float]]] | None = None
    if workspace._media_type == "movie":
        query_source = (
            state.preview_items[0].original.stem if state.preview_items else state.folder.name
        )
        title_key = "title"
        search_callback = tmdb.search_movie
        dialog_title = f"{fix_match_label(workspace, state)}: {query_source}"
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

    def _score_tv_results(results):
        return score_tv_results(
            results,
            query,
            year_hint,
            tmdb,
            folder=state.folder,
        )

    if workspace._media_type == "tv":
        score_results_callback = _score_tv_results

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
        f'Season number for "{state.display_name}":',
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
    if workspace._media_type == "tv" and season_num > 0 and follow_up_state.show_id is not None:
        tmdb = workspace._provider_for_state(follow_up_state)
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

        # An explicit *tmdb* (fix_match's search dialog result) stays on the
        # window's active provider by design. Otherwise (e.g. an alternate
        # match chosen from state.alternate_matches, which was populated by
        # whichever provider originally matched this show) resolve through
        # the state's own provider — a fallback/pinned/switched show's
        # alternates are foreign-provider dicts the active client can't
        # score correctly.
        active_tmdb = tmdb
        if active_tmdb is None:
            active_tmdb = workspace._provider_for_state(state)
        if active_tmdb is None:
            workspace.status_message.emit("Metadata source is unavailable.", 4000)
            return

        _invalidate_episode_projection(workspace, state)
        updated_state = workspace._media_ctrl.rematch_tv_state(state, chosen, active_tmdb)
        finish_tv_rematch(workspace, updated_state, active_tmdb)
    except Exception as exc:
        warning_box.warning(workspace, "Fix Match Failed", str(exc))


def finish_tv_rematch(workspace, updated_state: ScanState, tmdb: Any) -> None:
    workspace.refresh_from_controller()
    workspace._restore_roster_selection_by_key(_roster_selection_key(updated_state))
    workspace._media_ctrl.scan_show(updated_state, tmdb)
    if updated_state.scanned or updated_state.preview_items:
        _refresh_episode_projection(workspace, updated_state)
        workspace.refresh_from_controller()
        workspace._restore_roster_selection_by_key(_roster_selection_key(updated_state))
    workspace.status_message.emit(f"Re-matching {updated_state.display_name}...", 4000)


def _pruned_provider_overrides(overrides: dict) -> dict:
    """Drop pins whose provider isn't in the pool (Task 8 note: corrupt
    pins are pruned the next time the GUI writes the overrides dict)."""
    from ...providers import TV_PROVIDERS

    return {
        key: pin
        for key, pin in overrides.items()
        if isinstance(pin, dict) and pin.get("provider") in TV_PROVIDERS
    }


def _persist_provider_pin(workspace, state: ScanState, provider_name: str) -> None:
    settings = getattr(workspace, "_settings", None)
    if settings is None:
        return
    from ...engine.models import show_pin_key

    overrides = _pruned_provider_overrides(settings.tv_provider_overrides)
    key = show_pin_key(state.folder)
    if provider_name == settings.tv_metadata_source:
        # Switching back to the configured default source clears the pin
        # instead of persisting a redundant one.
        overrides.pop(key, None)
    else:
        overrides[key] = {"provider": provider_name, "show_id": state.show_id}
    settings.tv_provider_overrides = overrides


def switch_source(workspace, provider_name: str) -> None:
    """Re-resolve the selected show on another pooled provider (workspace
    Source control), persist the pin, and rescan through the new
    provider's client — mirrors the rematch flow in ``finish_tv_rematch``.
    """
    state = workspace._selected_state()
    if state is None or workspace._media_ctrl is None:
        return
    orchestrator = getattr(workspace._media_ctrl, "batch_orchestrator", None)
    if orchestrator is None:
        workspace.status_message.emit("Source switching is unavailable right now.", 4000)
        return
    if provider_name == state.provider_name:
        return

    _invalidate_episode_projection(workspace, state)
    merged_state, switched = orchestrator.switch_provider(state, provider_name)
    if not switched:
        workspace.status_message.emit(
            f"Could not find {merged_state.display_name} on that source.", 4000
        )
        return

    _persist_provider_pin(workspace, merged_state, provider_name)
    client = workspace._provider_for_state(merged_state)
    if client is None:
        workspace.refresh_from_controller()
        workspace._restore_roster_selection_by_key(_roster_selection_key(merged_state))
        workspace.status_message.emit(
            f"Switched {merged_state.display_name} to {provider_name}.", 4000
        )
        return
    finish_tv_rematch(workspace, merged_state, client)
