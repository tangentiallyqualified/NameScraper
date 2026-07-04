"""Detail and selection view helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from ...engine import PreviewItem, ScanState
from ...parsing import build_movie_name, build_show_folder_name
from ._media_helpers import roster_selection_key as _roster_selection_key


class MediaWorkspaceViewCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def selected_preview(self) -> PreviewItem | None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None:
            return None
        current = workspace._work_panel.table_view.currentIndex()
        if not current.isValid():
            return None
        index = workspace._work_panel.model.preview_index_at(current.row())
        if index is None or not (0 <= index < len(state.preview_items)):
            return None
        return state.preview_items[index]

    def folder_plan_text(self, state: ScanState) -> str:
        folder_preview = self.folder_preview_data(state)
        if folder_preview is None:
            return ""
        source, target = folder_preview
        return f"Folder rename plan: {source} -> {target}"

    def folder_preview_data(self, state: ScanState) -> tuple[str, str] | None:
        workspace = self._workspace
        source = state.folder.name
        if workspace._media_type == "movie":
            target = build_movie_name(
                state.media_info.get("title", state.display_name),
                state.media_info.get("year", ""),
                "",
            )
        else:
            target = build_show_folder_name(
                state.media_info.get("name", state.display_name),
                state.media_info.get("year", ""),
            )
        if not source or not target:
            return None
        return source, target

    def restore_roster_selection_by_key(self, state_key: str | None) -> None:
        workspace = self._workspace
        if state_key is None:
            return
        for index, state in enumerate(workspace._current_states()):
            if _roster_selection_key(state) != state_key:
                continue
            workspace._set_roster_current_state(index, auto_selected=workspace._roster_selection_is_auto)
            workspace._roster_panel.scroll_state_into_context(index)
            return

    def season_ratio_text(self, state: ScanState, season_num: int | None, item_count: int) -> str:
        expected = self.season_expected_count(state, season_num)
        if expected <= 0:
            expected = item_count
        return f" — {item_count}/{expected}"

    def season_expected_count(self, state: ScanState, season_num: int | None) -> int:
        completeness = state.completeness
        if completeness is None:
            return 0
        if season_num == 0:
            return completeness.specials.expected if completeness.specials is not None else 0
        if season_num is None:
            return 0
        season = completeness.seasons.get(season_num)
        if season is None:
            return 0
        return season.expected
