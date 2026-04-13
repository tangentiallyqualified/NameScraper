"""Tree presentation helpers for JobDetailPanel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


def job_detail_empty_message(*, history_mode: bool) -> str:
    if history_mode:
        return "History entries will appear here. Select one to review its rename preview, poster, and file locations."
    return "Queued jobs will appear here. Select one to review its rename preview, poster, and file locations."


def create_preview_group_header(parent, label: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem(parent, [""])
    item.setData(0, Qt.ItemDataRole.UserRole, label)
    item.setFirstColumnSpanned(True)
    font = item.font(0)
    font.setBold(True)
    item.setFont(0, font)
    set_preview_group_header_label(item, expanded=False)
    return item


def set_preview_group_header_label(item: QTreeWidgetItem, *, expanded: bool) -> None:
    base_label = str(item.data(0, Qt.ItemDataRole.UserRole) or item.text(0))
    prefix = "▾ " if expanded else "▸ "
    item.setText(0, f"{prefix}{base_label}")


def toggle_preview_group_item(item: QTreeWidgetItem) -> bool:
    if item.childCount() <= 0:
        return False
    item.setExpanded(not item.isExpanded())
    return True


def refresh_preview_item_sizes(tree: QTreeWidget) -> None:
    reserved_scrollbar = tree.verticalScrollBar().sizeHint().width() + 6
    viewport_width = max(220, tree.viewport().width() - reserved_scrollbar)

    def _walk(parent: QTreeWidgetItem | None, depth: int) -> None:
        count = parent.childCount() if parent is not None else tree.topLevelItemCount()
        for row in range(count):
            item = parent.child(row) if parent is not None else tree.topLevelItem(row)
            widget = tree.itemWidget(item, 0)
            if widget is not None:
                available_width = max(180, viewport_width - (depth * tree.indentation()))
                widget.setFixedWidth(available_width)
                widget.adjustSize()
                sync_tooltip = getattr(widget, "_sync_tooltip", None)
                if callable(sync_tooltip):
                    sync_tooltip()
                item.setSizeHint(0, widget.sizeHint())
            _walk(item, depth + 1)

    _walk(None, 0)
