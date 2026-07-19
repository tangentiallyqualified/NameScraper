"""Roster panel: RosterListView + RosterModel + RosterDelegate (GUI V4 §3.1/§7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import ScanState
from ._media_helpers import is_state_queue_approvable as _is_state_queue_approvable
from ._roster_delegate import RosterDelegate, RosterListView
from ._roster_model import ROW_DATA_ROLE, RosterModel
from ._workspace_widget_primitives import MasterCheckBox as _MasterCheckBox

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService


class MediaWorkspaceRosterPanel(QFrame):
    state_selected = Signal(int)
    check_toggled = Signal(int, bool)
    group_toggled = Signal(str)

    def __init__(
        self,
        *,
        media_type: str,
        settings_service: SettingsService | None = None,
        tmdb_provider=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._syncing = False
        self._master_syncing = False
        self._model = RosterModel(
            media_type=media_type,
            settings_service=settings_service,
            tmdb_provider=tmdb_provider,
        )
        self._build_ui()

    @property
    def master_check(self) -> _MasterCheckBox:
        return self._master_check

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

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)

        self._master_check = _MasterCheckBox("Select All")
        self._master_check.setTristate(True)
        self._master_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        controls.addWidget(self._master_check)

        self._selection_summary = QLabel("0 checked")
        self._selection_summary.setProperty("cssClass", "caption")
        controls.addWidget(self._selection_summary)
        controls.addStretch()

        self._queue_button = QPushButton("Queue Checked")
        self._queue_button.setProperty("cssClass", "primary")
        self._queue_button.setProperty("sizeVariant", "compact")
        self._queue_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._queue_button.setEnabled(False)
        controls.addWidget(self._queue_button)

        layout.addLayout(controls)

        self._view = RosterListView()
        self._delegate = RosterDelegate(self._view, media_type=self._media_type)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.toggle_clicked.connect(self._on_toggle_clicked)
        self._view.header_clicked.connect(self._on_header_clicked)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self._view, stretch=1)

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
            state
            for state in states
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

    @property
    def model(self) -> RosterModel:
        return self._model

    @property
    def view(self) -> RosterListView:
        return self._view

    def sync_items(self, states: list[ScanState], *, collapsed_groups: dict[str, bool]) -> None:
        previous = self.current_state_index()
        self._syncing = True
        try:
            self._model.set_states(states, collapsed_groups=collapsed_groups)
        finally:
            self._syncing = False
        if previous is not None:
            self.set_current_state(previous)
        else:
            self.select_first_state()

    def refresh_state(self, state_index: int) -> None:
        self._model.refresh_state(state_index)

    def current_state_index(self) -> int | None:
        index = self._view.currentIndex()
        if not index.isValid():
            return None
        return self._model.state_index_at(index.row())

    def set_current_state(self, state_index: int) -> bool:
        row = self._model.row_for_state_index(state_index)
        if row < 0:
            return False
        self._syncing = True
        try:
            self._view.setCurrentIndex(self._model.index(row, 0))
        finally:
            self._syncing = False
        return True

    def select_first_state(self) -> bool:
        row = self._model.first_state_row()
        if row < 0:
            return False
        # Set current OUTSIDE the syncing guard so _on_current_changed fires
        # and drives the work panel.
        self._view.setCurrentIndex(self._model.index(row, 0))
        return True

    def scroll_state_into_context(self, state_index: int) -> None:
        row = self._model.row_for_state_index(state_index)
        if row < 0:
            return
        anchor_row = self._model.header_row_before(row)
        anchor = self._model.index(anchor_row if anchor_row >= 0 else row, 0)
        self._view.scrollTo(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

    def set_compact(self, compact: bool) -> None:
        self._delegate.set_compact(compact)
        self._model.set_compact(compact)

    def is_compact(self) -> bool:
        return self._model.is_compact()

    # ── internal slots ────────────────────────────────────────────
    def _on_toggle_clicked(self, index: QModelIndex) -> None:
        state_index = self._model.state_index_at(index.row())
        row_data = index.data(ROW_DATA_ROLE)
        if state_index is None or row_data is None or not row_data.checkable:
            return
        self.check_toggled.emit(state_index, not row_data.checked)

    def _on_header_clicked(self, group: str) -> None:
        self.group_toggled.emit(group)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        state_index = self._model.state_index_at(current.row())
        if state_index is not None:
            self.state_selected.emit(state_index)
