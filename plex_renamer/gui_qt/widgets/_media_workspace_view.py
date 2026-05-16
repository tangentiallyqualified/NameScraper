"""Detail and selection view helpers for the media workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QListWidgetItem

from ...engine import PreviewItem, ScanState
from ...parsing import build_movie_name, build_show_folder_name
from ._media_helpers import roster_selection_key as _roster_selection_key
from ._media_workspace_roster import _ROSTER_ENTRY_KIND_ROLE


class MediaWorkspaceViewCoordinator:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def render_detail(self, state: ScanState | None, preview: PreviewItem | None = None) -> None:
        workspace = self._workspace
        if state is None:
            workspace._detail_panel.clear()
            return

        eligibility = workspace._queue_eligibility([state])
        workspace._detail_panel.set_selection(
            state,
            preview=preview,
            queue_reason=eligibility.reason,
            folder_plan=self.folder_plan_text(state),
        )

    def selected_preview(self) -> PreviewItem | None:
        workspace = self._workspace
        state = workspace._selected_state()
        current = workspace._preview_list.currentItem()
        if state is None or current is None:
            return None
        index = current.data(Qt.ItemDataRole.UserRole)
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
            item = workspace._find_roster_item_by_index(index)
            if item is not None:
                workspace._set_roster_current_item(item, auto_selected=workspace._roster_selection_is_auto)
                self.scroll_roster_item_into_context(item)
            return

    def scroll_roster_item_into_context(self, item: QListWidgetItem) -> None:
        workspace = self._workspace
        row = workspace._roster_list.row(item)
        if row < 0:
            return
        anchor = item
        for index in range(row - 1, -1, -1):
            header = workspace._roster_list.item(index)
            if header is not None and header.data(_ROSTER_ENTRY_KIND_ROLE) == "header":
                anchor = header
                break
        workspace._roster_list.scrollToItem(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

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
