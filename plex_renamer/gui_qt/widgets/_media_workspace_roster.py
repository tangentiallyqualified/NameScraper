"""Roster panel widget used by the media workspace."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from ._image_utils import pil_to_raw, raw_to_pixmap
from ._media_helpers import (
    auto_accept_threshold as _auto_accept_threshold,
    is_state_queue_approvable as _is_state_queue_approvable,
    make_section_header as _make_section_header,
    roster_group as _roster_group,
    roster_item_key as _roster_item_key,
    roster_signature as _roster_signature,
)
from ._workspace_widgets import (
    MasterCheckBox as _MasterCheckBox,
    RosterPosterBridge as _RosterPosterBridge,
    RosterRowWidget as _RosterRowWidget,
)

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService


_CHECKED_ROLE = Qt.ItemDataRole.UserRole + 10
_ROSTER_ENTRY_KEY_ROLE = Qt.ItemDataRole.UserRole + 11
_ROSTER_ENTRY_KIND_ROLE = Qt.ItemDataRole.UserRole + 12
_ROSTER_SIGNATURE_ROLE = Qt.ItemDataRole.UserRole + 13
_POSTER_KEY_ROLE = Qt.ItemDataRole.UserRole + 2
_MAX_ROSTER_POSTER_CACHE = 128


class MediaWorkspaceRosterPanel(QFrame):
    def __init__(
        self,
        *,
        media_type: str,
        settings_service: "SettingsService | None" = None,
        tmdb_provider=None,
        set_item_check_state_callback: Callable[[QListWidgetItem, bool], None] | None = None,
        prompt_assign_season_callback: Callable[[ScanState], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._tmdb_provider = tmdb_provider
        self._set_item_check_state = set_item_check_state_callback
        self._prompt_assign_season = prompt_assign_season_callback
        self._poster_cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._poster_inflight: set[tuple[str, int]] = set()
        self._master_syncing = False
        self._poster_bridge = _RosterPosterBridge(self)
        self._poster_bridge.poster_ready.connect(self._apply_poster)
        self._build_ui()

    @property
    def list_widget(self) -> QListWidget:
        return self._list_widget

    @property
    def master_check(self) -> _MasterCheckBox:
        return self._master_check

    @property
    def selection_summary(self) -> QLabel:
        return self._selection_summary

    @property
    def queue_button(self) -> QPushButton:
        return self._queue_button

    @property
    def master_syncing(self) -> bool:
        return self._master_syncing

    def _build_ui(self) -> None:
        self.setProperty("cssClass", "panel")
        self.setProperty("panelVariant", "square")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self._master_check = _MasterCheckBox("Select All")
        self._master_check.setTristate(True)
        self._master_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(self._master_check)

        self._selection_summary = QLabel("0 checked")
        self._selection_summary.setProperty("cssClass", "caption")
        header.addWidget(self._selection_summary)
        header.addStretch()

        self._queue_button = QPushButton("Queue Checked")
        self._queue_button.setProperty("cssClass", "primary")
        self._queue_button.setProperty("sizeVariant", "compact")
        self._queue_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._queue_button.setEnabled(False)
        header.addWidget(self._queue_button)
        layout.addLayout(header)

        self._list_widget = QListWidget()
        self._list_widget.setProperty("cssClass", "row-host-list")
        self._list_widget.setIconSize(QSize(42, 60))
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._list_widget, stretch=1)

    def set_queue_button_text(self, text: str) -> None:
        self._queue_button.setText(text)
        option = QStyleOptionButton()
        option.initFrom(self._queue_button)
        option.text = text
        size = self._queue_button.style().sizeFromContents(
            QStyle.ContentsType.CT_PushButton,
            option,
            QSize(),
            self._queue_button,
        )
        self._queue_button.setMinimumWidth(max(108, size.width()))

    def update_selection_header(self, states: list[ScanState]) -> None:
        eligible_states = [
            state for state in states
            if _is_state_queue_approvable(state, media_type=self._media_type)
        ]
        checked_count = sum(1 for state in eligible_states if state.checked)
        total_eligible = len(eligible_states)
        if total_eligible:
            self._selection_summary.setText(f"{checked_count} of {total_eligible} checked")
        else:
            self._selection_summary.setText("No eligible items")

        self._master_syncing = True
        try:
            self._master_check.setEnabled(bool(total_eligible))
            if total_eligible == 0 or checked_count == 0:
                self._master_check.setCheckState(Qt.CheckState.Unchecked)
                self._master_check.setText("Select All")
            elif checked_count == total_eligible:
                self._master_check.setCheckState(Qt.CheckState.Checked)
                self._master_check.setText("Deselect All")
            else:
                self._master_check.setCheckState(Qt.CheckState.PartiallyChecked)
                self._master_check.setText("Select All")
        finally:
            self._master_syncing = False

    def sync_items(self, states: list[ScanState], *, collapsed_groups: dict[str, bool]) -> None:
        existing_items: dict[str, list[QListWidgetItem]] = {}
        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            key = item.data(_ROSTER_ENTRY_KEY_ROLE)
            if isinstance(key, str):
                existing_items.setdefault(key, []).append(item)

        desired_entries = list(self._desired_entries(states, collapsed_groups))
        for target_row, entry in enumerate(desired_entries):
            key = entry["key"]
            items_for_key = existing_items.get(key)
            item = items_for_key.pop(0) if items_for_key else None
            if items_for_key == []:
                existing_items.pop(key, None)
            if item is None:
                item = QListWidgetItem()
            self._place_item(item, target_row)
            if entry["kind"] == "header":
                self._configure_header(item, entry["group"], entry["title"])
                continue
            self._configure_state_item(item, entry["index"], entry["state"])

        for items in existing_items.values():
            for item in items:
                self._remove_item(item)

    def find_item_by_index(self, index: int) -> QListWidgetItem | None:
        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            if item.data(_ROSTER_ENTRY_KIND_ROLE) != "state":
                continue
            if item.data(Qt.ItemDataRole.UserRole) == index:
                return item
        return None

    def _desired_entries(self, states: list[ScanState], collapsed_groups: dict[str, bool]):
        groups = [
            ("queued", "Queued"),
            ("plex-ready", "Plex Ready"),
            ("matched", "Matched"),
            ("review", "Needs Review"),
            ("unmatched", "Unmatched"),
            ("duplicate", "Duplicates"),
        ]
        for group, title in groups:
            indices = [index for index, state in enumerate(states) if _roster_group(state) == group]
            if not indices:
                continue
            collapsed = collapsed_groups.get(group, False)
            arrow = "▶" if collapsed else "▼"
            yield {
                "kind": "header",
                "key": f"header:{group}",
                "group": group,
                "title": f"{arrow}  {title} ({len(indices)})",
            }
            if not collapsed:
                for index in indices:
                    state = states[index]
                    yield {
                        "kind": "state",
                        "key": _roster_item_key(state),
                        "index": index,
                        "state": state,
                    }

    def _place_item(self, item: QListWidgetItem, target_row: int) -> None:
        current_row = self._list_widget.row(item)
        if current_row == -1:
            self._list_widget.insertItem(target_row, item)
            return
        if current_row == target_row:
            return
        widget = self._list_widget.itemWidget(item)
        if widget is not None:
            self._list_widget.removeItemWidget(item)
            widget.deleteLater()
            item.setData(_ROSTER_SIGNATURE_ROLE, None)
        moved = self._list_widget.takeItem(current_row)
        self._list_widget.insertItem(target_row, moved)

    def _configure_header(self, item: QListWidgetItem, group: str, title: str) -> None:
        configured = _make_section_header(title)
        item.setText(configured.text())
        item.setFlags(configured.flags())
        item.setForeground(configured.foreground())
        item.setBackground(configured.background())
        item.setFont(configured.font())
        item.setSizeHint(configured.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, None)
        item.setData(_CHECKED_ROLE, None)
        item.setData(_ROSTER_ENTRY_KIND_ROLE, "header")
        item.setData(_ROSTER_ENTRY_KEY_ROLE, f"header:{group}")
        item.setData(_ROSTER_SIGNATURE_ROLE, None)
        widget = self._list_widget.itemWidget(item)
        if widget is not None:
            self._list_widget.removeItemWidget(item)
            widget.deleteLater()

    def _configure_state_item(self, item: QListWidgetItem, index: int, state: ScanState) -> None:
        signature = _roster_signature(state, compact=self._is_compact_mode(), media_type=self._media_type)
        item.setData(Qt.ItemDataRole.UserRole, index)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setData(_CHECKED_ROLE, state.checked)
        item.setData(_ROSTER_ENTRY_KIND_ROLE, "state")
        item.setData(_ROSTER_ENTRY_KEY_ROLE, _roster_item_key(state))

        if item.data(_ROSTER_SIGNATURE_ROLE) != signature:
            self._attach_row_widget(item, state)
            item.setData(_ROSTER_SIGNATURE_ROLE, signature)
        else:
            widget = self._list_widget.itemWidget(item)
            if isinstance(widget, _RosterRowWidget):
                widget.set_checked(state.checked)
        self._request_poster(state, item)

    def _remove_item(self, item: QListWidgetItem) -> None:
        row = self._list_widget.row(item)
        if row < 0:
            return
        widget = self._list_widget.itemWidget(item)
        if widget is not None:
            self._list_widget.removeItemWidget(item)
            widget.deleteLater()
        self._list_widget.takeItem(row)

    def _attach_row_widget(self, item: QListWidgetItem, state: ScanState) -> None:
        existing = self._list_widget.itemWidget(item)
        if existing is not None:
            self._list_widget.removeItemWidget(item)
            existing.deleteLater()
        widget = _RosterRowWidget(
            state,
            compact=self._is_compact_mode(),
            media_type=self._media_type,
            auto_accept_threshold=_auto_accept_threshold(self._settings),
            checkable=_is_state_queue_approvable(state, media_type=self._media_type),
            parent=self._list_widget,
        )
        widget.clicked.connect(lambda item=item: self._list_widget.setCurrentItem(item))
        if self._set_item_check_state is not None:
            widget.check_toggled.connect(
                lambda checked, item=item: self._set_item_check_state(item, checked)
            )
        if self._prompt_assign_season is not None:
            widget.season_assign_requested.connect(lambda state=state: self._prompt_assign_season(state))
        widget.geometry_changed.connect(lambda item=item, widget=widget: self._sync_item_height(item, widget))
        self._sync_item_height(item, widget)
        self._list_widget.setItemWidget(item, widget)
        key = item.data(_POSTER_KEY_ROLE)
        if key in self._poster_cache:
            widget.set_poster(self._poster_cache[key])

    def _sync_item_height(self, item: QListWidgetItem, widget: QWidget) -> None:
        item.setSizeHint(QSize(0, widget.sizeHint().height()))

    def _request_poster(self, state: ScanState, item: QListWidgetItem) -> None:
        if state.show_id is None or self._tmdb_provider is None:
            return
        key = (self._media_type, state.show_id)
        item.setData(_POSTER_KEY_ROLE, key)
        cached = self._poster_cache.get(key)
        if cached is not None:
            self._poster_cache.move_to_end(key)
            widget = self._list_widget.itemWidget(item)
            if isinstance(widget, _RosterRowWidget):
                widget.set_poster(cached)
            return

        if key in self._poster_inflight:
            return
        tmdb = self._tmdb_provider()
        if tmdb is None:
            return
        self._poster_inflight.add(key)
        target_width = self._poster_fetch_width(item)

        def _worker() -> None:
            try:
                image = tmdb.fetch_poster(state.show_id, media_type=self._media_type, target_width=target_width)
                if image is None:
                    return
                try:
                    self._poster_bridge.poster_ready.emit(key, pil_to_raw(image))
                except RuntimeError:
                    return
            finally:
                self._poster_inflight.discard(key)

        _submit_bg(_worker)

    def _poster_fetch_width(self, item: QListWidgetItem) -> int:
        widget = self._list_widget.itemWidget(item)
        if isinstance(widget, _RosterRowWidget):
            return widget.poster_request_width()
        return 240

    def _apply_poster(self, key, raw_data) -> None:
        pixmap = raw_to_pixmap(raw_data)
        if pixmap.isNull():
            return
        self._poster_cache[key] = pixmap
        self._poster_cache.move_to_end(key)
        while len(self._poster_cache) > _MAX_ROSTER_POSTER_CACHE:
            self._poster_cache.popitem(last=False)
        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            if item.data(_POSTER_KEY_ROLE) == key:
                widget = self._list_widget.itemWidget(item)
                if isinstance(widget, _RosterRowWidget):
                    widget.set_poster(pixmap)

    def _is_compact_mode(self) -> bool:
        return self._settings is not None and self._settings.view_mode == "compact"