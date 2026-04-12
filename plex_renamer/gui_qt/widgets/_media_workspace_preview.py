"""Preview panel widget used by the media workspace."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ._media_helpers import (
    is_state_queue_approvable as _is_state_queue_approvable,
    make_section_header as _make_section_header,
    season_label as _season_label,
    state_key as _state_key,
    tv_preview_sort_key as _tv_preview_sort_key,
)
from ._workspace_widgets import (
    _CheckBinding,
    FolderPreviewRowWidget as _FolderPreviewRowWidget,
    MasterCheckBox as _MasterCheckBox,
    PreviewRowWidget as _PreviewRowWidget,
)

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService


_CHECKED_ROLE = Qt.ItemDataRole.UserRole + 10
_PREVIEW_ENTRY_KIND_ROLE = Qt.ItemDataRole.UserRole + 14
_PREVIEW_SECTION_ROLE = Qt.ItemDataRole.UserRole + 15


class MediaWorkspacePreviewPanel(QFrame):
    def __init__(
        self,
        *,
        media_type: str,
        settings_service: "SettingsService | None" = None,
        set_item_check_state_callback=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._set_item_check_state = set_item_check_state_callback
        self._master_syncing = False
        self._build_ui()

    @property
    def list_widget(self) -> QListWidget:
        return self._list_widget

    @property
    def master_check(self) -> _MasterCheckBox:
        return self._master_check

    @property
    def check_summary(self) -> QLabel:
        return self._check_summary

    @property
    def fix_match_button(self) -> QPushButton:
        return self._fix_match_button

    @property
    def primary_action_button(self) -> QPushButton:
        return self._primary_action_button

    @property
    def folder_plan_label(self) -> QLabel:
        return self._folder_plan_label

    @property
    def summary_label(self) -> QLabel:
        return self._summary_label

    @property
    def sticky_header(self) -> QLabel:
        return self._sticky_header

    @property
    def master_syncing(self) -> bool:
        return self._master_syncing

    def _build_ui(self) -> None:
        self.setProperty("cssClass", "panel")
        self.setProperty("panelVariant", "square")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()

        self._master_check = _MasterCheckBox("Select All")
        self._master_check.setTristate(True)
        self._master_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(self._master_check)

        self._check_summary = QLabel("")
        self._check_summary.setProperty("cssClass", "caption")
        header.addWidget(self._check_summary)
        header.addStretch()

        self._fix_match_button = QPushButton("Fix Match")
        self._fix_match_button.setProperty("cssClass", "secondary")
        self._fix_match_button.setEnabled(False)
        header.addWidget(self._fix_match_button)

        self._primary_action_button = QPushButton("")
        self._primary_action_button.setEnabled(False)
        header.addWidget(self._primary_action_button)
        layout.addLayout(header)

        self._folder_plan_label = QLabel("Select a roster item to see the planned folder rename.")
        self._folder_plan_label.setProperty("cssClass", "caption")
        self._folder_plan_label.setWordWrap(True)
        self._folder_plan_label.hide()
        layout.addWidget(self._folder_plan_label)

        self._summary_label = QLabel("Preview items will appear here once a scan is ready.")
        self._summary_label.setProperty("cssClass", "text-dim")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        self._list_widget = QListWidget()
        self._list_widget.setProperty("cssClass", "row-host-list")
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._list_widget, stretch=1)

        self._sticky_header = QLabel()
        self._sticky_header.setProperty("cssClass", "sticky-season-header")
        self._sticky_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._sticky_header.hide()
        self._sticky_header.setParent(self._list_widget)
        self._list_widget.verticalScrollBar().valueChanged.connect(self.update_sticky_header)

    def set_summary(self, text: str) -> None:
        self._summary_label.setText(text)
        self._summary_label.setVisible(bool(text))

    def populate_from_state(
        self,
        state: ScanState,
        *,
        preview_group_state: dict[str, set[int | str]],
        folder_section_key: str,
        ensure_check_bindings: Callable[[ScanState], None],
        folder_plan_text: Callable[[ScanState], str],
        folder_preview_data: Callable[[ScanState], tuple[str, str] | None],
        season_ratio_text: Callable[[ScanState, int | None, int], str],
    ) -> None:
        self._list_widget.clear()
        folder_preview = folder_preview_data(state)
        self._folder_plan_label.setText(folder_plan_text(state) if folder_preview is not None else "")
        if folder_preview is not None:
            self._add_folder_preview_section(
                state,
                folder_preview,
                preview_group_state=preview_group_state,
                folder_section_key=folder_section_key,
            )

        if not state.preview_items:
            if state.scanning:
                self.set_summary("Preview is still scanning for this item.")
            elif not state.scanned and state.show_id is not None:
                self.set_summary("Preview will appear once scanning completes.")
            else:
                self.set_summary("No preview items available for this selection.")
            return

        ensure_check_bindings(state)
        self.set_summary("")

        if self._media_type == "tv":
            collapsed = preview_group_state.setdefault(_state_key(state), set())
            season_groups: dict[int | None, list[int]] = {}
            for index, preview in enumerate(state.preview_items):
                season_groups.setdefault(preview.season, []).append(index)

            for season_num, indices in sorted(
                season_groups.items(),
                key=lambda entry: (entry[0] is None, entry[0] or 0),
            ):
                is_collapsed = season_num in collapsed
                ratio = season_ratio_text(state, season_num, len(indices))
                season_name = state.season_names.get(season_num, "") if season_num is not None else ""
                self.add_header(
                    ("▸ " if is_collapsed else "▾ ") + _season_label(season_num, name=season_name) + ratio,
                    season_num,
                )
                if is_collapsed:
                    continue
                for index in sorted(indices, key=lambda index: _tv_preview_sort_key(state.preview_items[index], index)):
                    item = self.build_preview_row(state, index, state.preview_items[index])
                    self._list_widget.addItem(item)
                    self.attach_preview_widget(item, state, index, state.preview_items[index])
        else:
            for index, preview in enumerate(state.preview_items):
                item = self.build_preview_row(state, index, preview)
                self._list_widget.addItem(item)
                self.attach_preview_widget(item, state, index, preview)

        self._restore_current_preview_row(state)

    def build_preview_row(self, state: ScanState, index: int, preview: PreviewItem) -> QListWidgetItem:
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, index)
        row.setData(_PREVIEW_ENTRY_KIND_ROLE, "preview")
        row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if preview.is_actionable and _is_state_queue_approvable(state, media_type=self._media_type):
            row.setData(_CHECKED_ROLE, state.check_vars[str(index)].get())
        return row

    def build_folder_preview_row(self) -> QListWidgetItem:
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, None)
        row.setData(_PREVIEW_ENTRY_KIND_ROLE, "folder")
        row.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return row

    def add_header(self, text: str, section_key: int | str) -> None:
        header = _make_section_header(text, selectable=True)
        header.setData(_PREVIEW_ENTRY_KIND_ROLE, "header")
        header.setData(_PREVIEW_SECTION_ROLE, section_key)
        self._list_widget.addItem(header)

    def _add_folder_preview_section(
        self,
        state: ScanState,
        folder_preview: tuple[str, str],
        *,
        preview_group_state: dict[str, set[int | str]],
        folder_section_key: str,
    ) -> None:
        collapsed = preview_group_state.setdefault(_state_key(state), set())
        is_collapsed = folder_section_key in collapsed
        self.add_header(("▸ " if is_collapsed else "▾ ") + "Folder", folder_section_key)
        if is_collapsed:
            return
        item = self.build_folder_preview_row()
        self._list_widget.addItem(item)
        self.attach_folder_preview_widget(item, *folder_preview)

    def attach_preview_widget(
        self,
        item: QListWidgetItem,
        state: ScanState,
        index: int,
        preview: PreviewItem,
    ) -> None:
        compact = self._settings is not None and self._settings.view_mode == "compact"
        show_confidence = self._settings is None or self._settings.show_confidence_bars
        show_companions = self._settings is not None and self._settings.show_companion_files
        widget = _PreviewRowWidget(
            preview,
            compact=compact,
            show_confidence=show_confidence,
            show_companions=show_companions,
            checked=state.check_vars.get(str(index), _CheckBinding(False)).get(),
            checkable=_is_state_queue_approvable(state, media_type=self._media_type),
            parent=self._list_widget,
        )
        widget.clicked.connect(lambda item=item: self._list_widget.setCurrentItem(item))
        if self._set_item_check_state is not None:
            widget.check_toggled.connect(lambda checked, item=item: self._set_item_check_state(item, checked))
        self._sync_item_height(item, widget)
        self._list_widget.setItemWidget(item, widget)

    def attach_folder_preview_widget(self, item: QListWidgetItem, source_name: str, target_name: str) -> None:
        widget = _FolderPreviewRowWidget(source_name, target_name, parent=self._list_widget)
        self._sync_item_height(item, widget)
        self._list_widget.setItemWidget(item, widget)

    def update_sticky_header(self) -> None:
        if self._media_type != "tv" or self._list_widget.count() == 0:
            self._sticky_header.hide()
            return
        top_item = self._list_widget.itemAt(4, 4)
        if top_item is None:
            self._sticky_header.hide()
            return
        top_row = self._list_widget.row(top_item)
        header_text = ""
        for row in range(top_row, -1, -1):
            item = self._list_widget.item(row)
            if item is not None and item.data(_PREVIEW_ENTRY_KIND_ROLE) == "header":
                header_text = item.text()
                break
        if not header_text or top_row == 0:
            self._sticky_header.hide()
            return
        self._sticky_header.setText(header_text)
        viewport = self._list_widget.viewport()
        self._sticky_header.setFixedWidth(viewport.width())
        self._sticky_header.setFixedHeight(30)
        self._sticky_header.move(0, 0)
        self._sticky_header.show()
        self._sticky_header.raise_()

    def update_master_state(self, state: ScanState | None) -> None:
        if state is None:
            self._master_check.setEnabled(False)
            self._check_summary.setText("")
            return
        actionable = [(index, preview) for index, preview in enumerate(state.preview_items) if preview.is_actionable]
        if not actionable or not _is_state_queue_approvable(state, media_type=self._media_type):
            self._master_check.setEnabled(False)
            self._master_check.setVisible(False)
            self._check_summary.setVisible(False)
            return
        self._master_check.setVisible(True)
        self._check_summary.setVisible(True)
        self._master_check.setEnabled(True)
        checked = 0
        for index, _preview in actionable:
            binding = state.check_vars.get(str(index))
            if binding is not None and binding.get():
                checked += 1
        total = len(actionable)
        self._master_syncing = True
        try:
            if checked == 0:
                self._master_check.setCheckState(Qt.CheckState.Unchecked)
                self._master_check.setText("Select All")
            elif checked == total:
                self._master_check.setCheckState(Qt.CheckState.Checked)
                self._master_check.setText("Deselect All")
            else:
                self._master_check.setCheckState(Qt.CheckState.PartiallyChecked)
                self._master_check.setText("Select All")
            self._check_summary.setText(f"{checked} of {total} checked")
        finally:
            self._master_syncing = False

    def _restore_current_preview_row(self, state: ScanState) -> None:
        target_index = state.selected_index
        if target_index is not None:
            for row in range(self._list_widget.count()):
                item = self._list_widget.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == target_index:
                    self._list_widget.setCurrentRow(row)
                    return

        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                self._list_widget.setCurrentRow(row)
                return

    def _sync_item_height(self, item: QListWidgetItem, widget: QWidget) -> None:
        item.setSizeHint(QSize(0, widget.sizeHint().height()))