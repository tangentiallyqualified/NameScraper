"""Media workspace widget for TV Shows and Movies tabs.

Manages the EMPTY -> SCANNING -> READY state machine via a
QStackedWidget. The READY state shows a controller-backed 3-panel
workspace with roster, preview, and selection/detail summaries.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ...parsing import best_tv_match_title, clean_folder_name, extract_year
from ...parsing import build_movie_name, build_show_folder_name
from ._formatting import clamped_percent
from ._image_utils import ShimmerOverlay, build_placeholder_pixmap, pil_to_raw, raw_to_pixmap
from ._media_helpers import (
    auto_accept_threshold as _auto_accept_threshold,
    band_color as _band_color,
    companion_summary as _companion_summary,
    confidence_band as _confidence_band,
    confidence_fill_color as _confidence_fill_color,
    file_count_for_state as _file_count_for_state,
    format_batch_result as _format_batch_result,
    is_plex_ready_state as _is_plex_ready_state,
    is_state_queue_approvable as _is_state_queue_approvable,
    make_section_header as _make_section_header,
    match_label as _match_label,
    placeholder_initials as _placeholder_initials,
    preview_band as _preview_band,
    preview_band_name as _preview_band_name,
    preview_heading as _preview_heading,
    preview_status_label as _preview_status_label,
    preview_status_tone as _preview_status_tone,
    preview_target_text as _preview_target_text,
    repolish as _repolish,
    roster_group as _roster_group,
    roster_item_key as _roster_item_key,
    roster_selection_key as _roster_selection_key,
    roster_signature as _roster_signature,
    season_label as _season_label,
    state_key as _state_key,
    state_match_summary as _state_match_summary,
    state_status as _state_status,
    state_status_tone as _state_status_tone,
    tv_preview_sort_key as _tv_preview_sort_key,
)
from .media_detail_panel import MediaDetailPanel
from .empty_state import EmptyStateWidget
from .match_picker_dialog import MatchPickerDialog
from .scan_progress import ScanProgressWidget

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService

# Stack indices
_EMPTY = 0
_SCANNING = 1
_READY = 2
_CHECKED_ROLE = Qt.ItemDataRole.UserRole + 10
_ROSTER_ENTRY_KEY_ROLE = Qt.ItemDataRole.UserRole + 11
_ROSTER_ENTRY_KIND_ROLE = Qt.ItemDataRole.UserRole + 12
_ROSTER_SIGNATURE_ROLE = Qt.ItemDataRole.UserRole + 13
_MAX_ROSTER_POSTER_CACHE = 128


class _RosterPosterBridge(QObject):
    poster_ready = Signal(object, object)


class _MasterCheckBox(QCheckBox):
    """Tri-state display checkbox that toggles like a normal binary control.

    Uses QSS for indicator styling — see theme.qss _MasterCheckBox selectors.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("cssClass", "master-check")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def nextCheckState(self) -> None:
        self.setCheckState(
            Qt.CheckState.Unchecked
            if self.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )


class MediaWorkspace(QWidget):
    """TV or Movie tab workspace with state-driven content switching."""

    # Emitted when a folder is selected — MainWindow handles the
    # controller call and state transitions.
    folder_selected = Signal(str)
    queue_changed = Signal()
    status_message = Signal(str, int)

    def __init__(
        self,
        media_type: str = "tv",
        media_controller=None,
        queue_controller=None,
        tmdb_provider=None,
        settings_service: "SettingsService | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._media_ctrl = media_controller
        self._queue_ctrl = queue_controller
        self._tmdb_provider = tmdb_provider
        self._settings = settings_service
        self._roster_syncing = False
        self._preview_syncing = False
        self._roster_poster_cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._poster_inflight: set[tuple[str, int]] = set()
        self._preview_group_state: dict[str, set[int]] = {}
        self._roster_master_syncing = False
        self._roster_collapsed: dict[str, bool] = {"plex-ready": True}
        self._poster_bridge = _RosterPosterBridge(self)
        self._poster_bridge.poster_ready.connect(self._apply_roster_poster)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Page 0: Empty state ──────────────────────────────────
        self._empty_state = EmptyStateWidget(
            media_type=self._media_type,
            settings_service=self._settings,
        )
        self._empty_state.folder_selected.connect(self._on_folder_selected)
        self._stack.addWidget(self._empty_state)

        # ── Page 1: Scanning state ───────────────────────────────
        self._scan_progress = ScanProgressWidget(
            media_type=self._media_type,
        )
        self._scan_progress.cancel_requested.connect(self._on_cancel_scan)
        self._stack.addWidget(self._scan_progress)

        # ── Page 2: Ready state (3-panel + action bar) ───────────
        ready_container = QWidget()
        ready_layout = QVBoxLayout(ready_container)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(0)

        # 3-panel splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._roster_panel = QFrame()
        self._roster_panel.setProperty("cssClass", "panel")
        self._roster_panel.setMinimumWidth(320)
        roster_layout = QVBoxLayout(self._roster_panel)
        roster_layout.setContentsMargins(12, 12, 12, 12)
        roster_layout.setSpacing(8)
        self._roster_title = QLabel("Library")
        self._roster_title.setProperty("cssClass", "heading")
        roster_layout.addWidget(self._roster_title)
        self._roster_hint = QLabel("Scanned items appear here.")
        self._roster_hint.setProperty("cssClass", "caption")
        roster_layout.addWidget(self._roster_hint)

        roster_select_row = QHBoxLayout()
        roster_select_row.setContentsMargins(0, 0, 0, 0)
        roster_select_row.setSpacing(8)
        self._roster_master_check = _MasterCheckBox("Select All")
        self._roster_master_check.setTristate(True)
        self._roster_master_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._roster_master_check.stateChanged.connect(self._on_roster_master_changed)
        roster_select_row.addWidget(self._roster_master_check)
        self._roster_selection_summary = QLabel("0 checked")
        self._roster_selection_summary.setProperty("cssClass", "caption")
        roster_select_row.addWidget(self._roster_selection_summary)
        roster_select_row.addStretch()
        self._roster_queue_btn = QPushButton("Queue Checked")
        self._roster_queue_btn.setProperty("cssClass", "primary")
        self._roster_queue_btn.setEnabled(False)
        self._roster_queue_btn.clicked.connect(self._queue_checked)
        roster_select_row.addWidget(self._roster_queue_btn)
        roster_layout.addLayout(roster_select_row)

        self._roster_list = QListWidget()
        self._roster_list.setProperty("cssClass", "row-host-list")
        self._roster_list.setIconSize(QSize(42, 60))
        self._roster_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._roster_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._roster_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._roster_list.itemChanged.connect(self._on_roster_item_changed)
        self._roster_list.itemClicked.connect(self._on_roster_item_clicked)
        self._roster_list.currentItemChanged.connect(self._on_roster_current_item_changed)
        roster_layout.addWidget(self._roster_list, stretch=1)

        self._preview_panel = QFrame()
        self._preview_panel.setProperty("cssClass", "panel")
        self._preview_panel.setMinimumWidth(500)
        preview_layout = QVBoxLayout(self._preview_panel)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(8)
        preview_header = QHBoxLayout()
        self._preview_title = QLabel("Preview")
        self._preview_title.setProperty("cssClass", "heading")
        preview_header.addWidget(self._preview_title)
        preview_header.addStretch()
        self._fix_match_btn = QPushButton("Fix Match")
        self._fix_match_btn.setProperty("cssClass", "secondary")
        self._fix_match_btn.setEnabled(False)
        self._fix_match_btn.clicked.connect(self._fix_match)
        preview_header.addWidget(self._fix_match_btn)
        self._queue_inline_btn = QPushButton("Queue This Show")
        self._queue_inline_btn.setEnabled(False)
        self._queue_inline_btn.clicked.connect(self._queue_selected_state)
        preview_header.addWidget(self._queue_inline_btn)
        preview_layout.addLayout(preview_header)
        self._folder_plan_label = QLabel("Select a roster item to see the planned folder rename.")
        self._folder_plan_label.setProperty("cssClass", "caption")
        self._folder_plan_label.setWordWrap(True)
        preview_layout.addWidget(self._folder_plan_label)
        self._preview_summary = QLabel("Preview items will appear here once a scan is ready.")
        self._preview_summary.setProperty("cssClass", "text-dim")
        self._preview_summary.setWordWrap(True)
        preview_layout.addWidget(self._preview_summary)

        preview_check_row = QHBoxLayout()
        preview_check_row.setContentsMargins(0, 0, 0, 0)
        preview_check_row.setSpacing(8)
        self._preview_master_check = _MasterCheckBox("Select All Files")
        self._preview_master_check.setTristate(True)
        self._preview_master_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_master_check.stateChanged.connect(self._on_preview_master_changed)
        preview_check_row.addWidget(self._preview_master_check)
        self._preview_check_summary = QLabel("")
        self._preview_check_summary.setProperty("cssClass", "caption")
        preview_check_row.addWidget(self._preview_check_summary)
        preview_check_row.addStretch()
        preview_layout.addLayout(preview_check_row)
        self._preview_master_syncing = False

        self._preview_list = QListWidget()
        self._preview_list.setProperty("cssClass", "row-host-list")
        self._preview_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._preview_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_list.itemChanged.connect(self._on_preview_item_changed)
        self._preview_list.currentItemChanged.connect(self._on_preview_current_item_changed)
        self._preview_list.itemClicked.connect(self._on_preview_item_clicked)
        preview_layout.addWidget(self._preview_list, stretch=1)

        # Sticky season header overlay (TV only)
        self._sticky_header = QLabel()
        self._sticky_header.setProperty("cssClass", "sticky-season-header")
        self._sticky_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._sticky_header.hide()
        self._sticky_header.setParent(self._preview_list)
        self._preview_list.verticalScrollBar().valueChanged.connect(self._update_sticky_header)

        self._detail_panel = MediaDetailPanel(
            tmdb_provider=self._tmdb_provider,
            settings_service=self._settings,
        )
        self._detail_panel.setMinimumWidth(340)

        self._splitter.addWidget(self._roster_panel)
        self._splitter.addWidget(self._preview_panel)
        self._splitter.addWidget(self._detail_panel)

        # Default proportions: ~20% roster, ~50% preview, ~30% detail
        self._splitter.setSizes([320, 540, 380])
        self._splitter.setChildrenCollapsible(False)

        ready_layout.addWidget(self._splitter, stretch=1)

        # Bottom action bar
        # Bottom action bar removed — queue button is now in the roster panel header.

        self._stack.addWidget(ready_container)

        # ── Restore splitter positions ───────────────────────────
        if self._settings:
            positions = self._settings.splitter_positions
            if positions and len(positions) == 3:
                self._splitter.setSizes(positions)

        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        # Start in empty state
        self._stack.setCurrentIndex(_EMPTY)

    # ── Public API ───────────────────────────────────────────────

    def open_folder_dialog(self) -> None:
        """Trigger the empty state's folder picker dialog."""
        self._empty_state.open_folder_dialog()

    def load_folder(self, path: str) -> None:
        """Load a specific folder path (e.g. from recent folders menu)."""
        self._on_folder_selected(path)

    def show_empty(self) -> None:
        """Switch to the empty state."""
        self._scan_progress.stop()
        self._detail_panel.clear_metadata_cache()
        self._stack.setCurrentIndex(_EMPTY)
        self._empty_state.refresh_recent_folders()

    def show_scanning(self) -> None:
        """Switch to the scanning state and start the timer."""
        self._scan_progress.start()
        self._detail_panel.clear_metadata_cache()
        self._stack.setCurrentIndex(_SCANNING)

    def show_ready(self) -> None:
        """Switch to the 3-panel ready state."""
        self._scan_progress.stop()
        self._stack.setCurrentIndex(_READY)
        self.refresh_from_controller()

    def is_showing_ready(self) -> bool:
        return self._stack.currentIndex() == _READY

    @property
    def scan_progress_widget(self) -> ScanProgressWidget:
        return self._scan_progress

    @property
    def splitter(self) -> QSplitter:
        return self._splitter

    def apply_settings(self) -> None:
        compact = self._settings is not None and self._settings.view_mode == "compact"
        self._roster_list.setIconSize(QSize(32, 46) if compact else QSize(42, 60))
        self.refresh_from_controller()
        self._detail_panel.refresh_current()

    def queue_selected(self) -> None:
        self._queue_selected_state()

    def queue_checked(self) -> None:
        self._queue_checked()

    def toggle_focused_check(self) -> None:
        """Toggle the checkbox on the currently focused roster item (Space)."""
        if self._stack.currentIndex() != _READY:
            return
        item = self._roster_list.currentItem()
        if item is None or item.data(_ROSTER_ENTRY_KIND_ROLE) != "state":
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        states = self._current_states()
        if row is None or not (0 <= row < len(states)):
            return
        state = states[row]
        state.checked = not state.checked
        item.setData(_CHECKED_ROLE, state.checked)
        widget = self._roster_list.itemWidget(item)
        if isinstance(widget, _RosterRowWidget):
            widget.set_checked(state.checked)
        self._update_action_bar()

    def force_rematch(self) -> None:
        """Open the Fix Match dialog for the currently selected roster item (F5)."""
        if self._stack.currentIndex() != _READY:
            return
        self._fix_match()

    def cancel_scan(self) -> bool:
        """Cancel a running scan. Returns True if a cancel was initiated."""
        if self._stack.currentIndex() != _SCANNING:
            return False
        self._on_cancel_scan()
        return True

    # ── Internals ────────────────────────────────────────────────

    def _on_folder_selected(self, path: str) -> None:
        # Emit the signal — MainWindow will call the controller and
        # transition us to scanning via show_scanning().
        self.folder_selected.emit(path)
        # Transition to scanning immediately.  If the controller
        # cannot start (e.g. no API key), MainWindow calls show_empty().
        self.show_scanning()

    def _on_cancel_scan(self) -> None:
        if self._media_ctrl is None:
            self.show_empty()
            return
        if self._media_ctrl.cancel_scan():
            self.status_message.emit("Cancelling scan...", 3000)
            return
        self.status_message.emit("No active scan to cancel.", 3000)

    def _on_splitter_moved(self) -> None:
        if self._settings:
            self._settings.splitter_positions = list(self._splitter.sizes())

    def _on_roster_master_changed(self, state: int) -> None:
        if self._roster_master_syncing:
            return
        checked_value = Qt.CheckState.Checked.value
        unchecked_value = Qt.CheckState.Unchecked.value
        if state == checked_value:
            self._check_all()
        elif state == unchecked_value:
            self._uncheck_all()

    def refresh_from_controller(self) -> None:
        """Synchronize the ready-state roster and preview from controller state."""
        if self._media_ctrl is None:
            return

        states = self._current_states()
        self._normalize_queue_selection(states)
        selected_state_key = _roster_selection_key(self._selected_state())
        self._roster_syncing = True
        self._roster_list.setUpdatesEnabled(False)
        self._sync_roster_items(states)
        self._roster_syncing = False
        self._roster_list.setUpdatesEnabled(True)

        if not states:
            self._preview_list.clear()
            self._folder_plan_label.setText("Select a roster item to see the planned folder rename.")
            self._preview_summary.setText("Preview items will appear here once a scan is ready.")
            self._detail_panel.clear()
            self._roster_queue_btn.setEnabled(False)
            self._roster_queue_btn.setText("Queue Checked")
            self._roster_queue_btn.setToolTip("")
            self._update_roster_selection_header([])
            self._fix_match_btn.setEnabled(False)
            self._queue_inline_btn.setEnabled(False)
            self._queue_inline_btn.setText("Queue This Show")
            return

        selected_index = self._media_ctrl.library_selected_index
        if selected_state_key is not None:
            matched_index = next(
                (index for index, state in enumerate(states) if _roster_selection_key(state) == selected_state_key),
                None,
            )
            if matched_index is not None:
                selected_index = matched_index

        if selected_index is None or not (0 <= selected_index < len(states)):
            selected_index = 0
        selected_state = self._media_ctrl.select_show(selected_index)

        selected_item = self._find_roster_item_by_index(selected_index)
        if selected_item is not None:
            self._roster_list.setCurrentItem(selected_item)

        if selected_state is not None:
            self._ensure_check_bindings(selected_state)
            self._populate_preview(selected_state)
            self._render_detail(selected_state, self._selected_preview())
        self._update_action_bar()
        self._sync_row_selection(self._roster_list)

    def _sync_roster_items(self, states: list[ScanState]) -> None:
        existing_items: dict[str, QListWidgetItem] = {}
        for row in range(self._roster_list.count()):
            item = self._roster_list.item(row)
            key = item.data(_ROSTER_ENTRY_KEY_ROLE)
            if isinstance(key, str):
                existing_items[key] = item

        desired_entries = list(self._desired_roster_entries(states))
        for target_row, entry in enumerate(desired_entries):
            key = entry["key"]
            item = existing_items.pop(key, None)
            if item is None:
                item = QListWidgetItem()
            self._place_roster_item(item, target_row)
            if entry["kind"] == "header":
                self._configure_roster_header(item, entry["group"], entry["title"])
                continue
            self._configure_roster_state_item(item, entry["index"], entry["state"])

        for item in existing_items.values():
            self._remove_roster_item(item)

    def _desired_roster_entries(self, states: list[ScanState]):
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
            collapsed = self._roster_collapsed.get(group, False)
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

    def _place_roster_item(self, item: QListWidgetItem, target_row: int) -> None:
        current_row = self._roster_list.row(item)
        if current_row == -1:
            self._roster_list.insertItem(target_row, item)
            return
        if current_row == target_row:
            return
        widget = self._roster_list.itemWidget(item)
        if widget is not None:
            self._roster_list.removeItemWidget(item)
            widget.deleteLater()
            item.setData(_ROSTER_SIGNATURE_ROLE, None)
        moved = self._roster_list.takeItem(current_row)
        self._roster_list.insertItem(target_row, moved)

    def _configure_roster_header(self, item: QListWidgetItem, group: str, title: str) -> None:
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
        widget = self._roster_list.itemWidget(item)
        if widget is not None:
            self._roster_list.removeItemWidget(item)
            widget.deleteLater()

    def _configure_roster_state_item(self, item: QListWidgetItem, index: int, state: ScanState) -> None:
        signature = _roster_signature(state, compact=self._is_compact_mode(), media_type=self._media_type)
        item.setData(Qt.ItemDataRole.UserRole, index)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setData(_CHECKED_ROLE, state.checked)
        item.setData(_ROSTER_ENTRY_KIND_ROLE, "state")
        item.setData(_ROSTER_ENTRY_KEY_ROLE, _roster_item_key(state))

        if item.data(_ROSTER_SIGNATURE_ROLE) != signature:
            self._attach_roster_widget(item, state)
            item.setData(_ROSTER_SIGNATURE_ROLE, signature)
        else:
            widget = self._roster_list.itemWidget(item)
            if isinstance(widget, _RosterRowWidget):
                widget.set_checked(state.checked)
        self._request_roster_poster(state, item)

    def _remove_roster_item(self, item: QListWidgetItem) -> None:
        row = self._roster_list.row(item)
        if row < 0:
            return
        widget = self._roster_list.itemWidget(item)
        if widget is not None:
            self._roster_list.removeItemWidget(item)
            widget.deleteLater()
        self._roster_list.takeItem(row)

    def _find_roster_item_by_index(self, index: int) -> QListWidgetItem | None:
        for row in range(self._roster_list.count()):
            item = self._roster_list.item(row)
            if item.data(_ROSTER_ENTRY_KIND_ROLE) != "state":
                continue
            if item.data(Qt.ItemDataRole.UserRole) == index:
                return item
        return None

    def _is_compact_mode(self) -> bool:
        return self._settings is not None and self._settings.view_mode == "compact"

    def _current_states(self) -> list[ScanState]:
        if self._media_ctrl is None:
            return []
        if self._media_type == "movie":
            return list(self._media_ctrl.movie_library_states)
        return list(self._media_ctrl.batch_states)

    def _selected_state(self) -> ScanState | None:
        states = self._current_states()
        item = self._roster_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and 0 <= index < len(states):
            return states[index]
        return None

    def _ensure_check_bindings(self, state: ScanState) -> None:
        for index, item in enumerate(state.preview_items):
            key = str(index)
            if key not in state.check_vars:
                state.check_vars[key] = _CheckBinding(
                    item.is_actionable and _is_state_queue_approvable(state, media_type=self._media_type)
                )

    def _normalize_queue_selection(self, states: list[ScanState]) -> None:
        for state in states:
            if _is_state_queue_approvable(state, media_type=self._media_type):
                # Re-enable check bindings for items that became approvable
                # again (e.g. after unqueueing).
                for index, item in enumerate(state.preview_items):
                    key = str(index)
                    binding = state.check_vars.get(key)
                    if binding is not None and hasattr(binding, "set") and item.is_actionable:
                        binding.set(True)
                if state.preview_items and not state.checked:
                    state.checked = True
                continue
            state.checked = False
            for binding in state.check_vars.values():
                if hasattr(binding, "set"):
                    binding.set(False)

    def _on_roster_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(_ROSTER_ENTRY_KIND_ROLE) != "header":
            return
        key = item.data(_ROSTER_ENTRY_KEY_ROLE) or ""
        group = key.removeprefix("header:")
        if not group:
            return
        self._roster_collapsed[group] = not self._roster_collapsed.get(group, False)
        states = self._current_states()
        if states:
            self._roster_syncing = True
            try:
                self._sync_roster_items(states)
            finally:
                self._roster_syncing = False

    def _on_roster_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self._roster_syncing or self._media_ctrl is None:
            return
        if current is None:
            return
        self._sync_row_selection(self._roster_list)
        row = current.data(Qt.ItemDataRole.UserRole)
        if row is None:
            return
        state = self._media_ctrl.select_show(row)
        if state is None:
            return
        self._ensure_check_bindings(state)
        self._populate_preview(state)
        self._render_detail(state)
        self._update_action_bar()

    def _on_roster_item_changed(self, item: QListWidgetItem) -> None:
        if self._roster_syncing:
            return
        states = self._current_states()
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is None or not (0 <= row < len(states)):
            return
        state = states[row]
        state.checked = bool(item.data(_CHECKED_ROLE))
        widget = self._roster_list.itemWidget(item)
        if isinstance(widget, _RosterRowWidget):
            widget.set_checked(state.checked)
        self._update_action_bar()
        if row == self._roster_list.currentRow():
            self._render_detail(state)

    def _populate_preview(self, state: ScanState) -> None:
        self._preview_syncing = True
        self._preview_list.setUpdatesEnabled(False)
        self._preview_list.clear()
        self._folder_plan_label.setText(self._folder_plan_text(state))

        if not state.preview_items:
            if state.scanning:
                self._preview_summary.setText("Preview is still scanning for this item.")
            elif not state.scanned and state.show_id is not None:
                self._preview_summary.setText("Preview will appear once scanning completes.")
            else:
                self._preview_summary.setText("No preview items available for this selection.")
            self._preview_syncing = False
            self._preview_list.setUpdatesEnabled(True)
            return

        self._ensure_check_bindings(state)
        self._preview_summary.setText(
            f"{len(state.preview_items)} preview item(s) · {_state_status(state)[0]}"
        )

        if self._media_type == "tv":
            collapsed = self._preview_group_state.setdefault(_state_key(state), set())
            season_groups: dict[int | None, list[int]] = {}
            for index, preview in enumerate(state.preview_items):
                season_groups.setdefault(preview.season, []).append(index)

            for season_num, indices in sorted(
                season_groups.items(),
                key=lambda entry: (entry[0] is None, entry[0] or 0),
            ):
                is_collapsed = season_num in collapsed
                matched = sum(1 for i in indices if state.preview_items[i].status == "OK")
                ratio_text = f" — {matched}/{len(indices)}"
                sn_name = state.season_names.get(season_num, "") if season_num is not None else ""
                header = _make_section_header(
                    ("▸ " if is_collapsed else "▾ ") + _season_label(season_num, name=sn_name) + ratio_text,
                    selectable=True,
                )
                header.setData(Qt.ItemDataRole.UserRole + 1, season_num)
                self._preview_list.addItem(header)
                if is_collapsed:
                    continue
                ordered_indices = sorted(
                    indices,
                    key=lambda index: _tv_preview_sort_key(state.preview_items[index], index),
                )
                for index in ordered_indices:
                    item = self._build_preview_row(state, index, state.preview_items[index])
                    self._preview_list.addItem(item)
                    self._attach_preview_widget(item, state, index, state.preview_items[index])
        else:
            for index, preview in enumerate(state.preview_items):
                item = self._build_preview_row(state, index, preview)
                self._preview_list.addItem(item)
                self._attach_preview_widget(item, state, index, preview)

        if state.selected_index is not None:
            for row in range(self._preview_list.count()):
                item = self._preview_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == state.selected_index:
                    self._preview_list.setCurrentRow(row)
                    break
        else:
            for row in range(self._preview_list.count()):
                item = self._preview_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) is not None:
                    self._preview_list.setCurrentRow(row)
                    break
        self._preview_syncing = False
        self._preview_list.setUpdatesEnabled(True)
        self._sync_row_selection(self._preview_list)
        self._update_preview_master_state(state)

    def _build_preview_row(self, state: ScanState, index: int, preview: PreviewItem) -> QListWidgetItem:
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, index)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if preview.is_actionable and _is_state_queue_approvable(state, media_type=self._media_type):
            row.setData(_CHECKED_ROLE, state.check_vars[str(index)].get())
        row.setFlags(flags)
        return row

    def _on_preview_item_clicked(self, item: QListWidgetItem) -> None:
        if self._preview_syncing or self._media_type != "tv":
            return
        state = self._selected_state()
        if state is None:
            return
        season_num = item.data(Qt.ItemDataRole.UserRole + 1)
        if season_num is None or item.data(Qt.ItemDataRole.UserRole) is not None:
            return
        collapsed = self._preview_group_state.setdefault(_state_key(state), set())
        if season_num in collapsed:
            collapsed.remove(season_num)
        else:
            collapsed.add(season_num)
        self._populate_preview(state)

    def _update_sticky_header(self) -> None:
        """Show a floating season header at the top of the preview list when scrolled."""
        if self._media_type != "tv" or self._preview_list.count() == 0:
            self._sticky_header.hide()
            return
        # Find the topmost visible item; walk backwards to find its season header
        top_item = self._preview_list.itemAt(4, 4)
        if top_item is None:
            self._sticky_header.hide()
            return
        top_row = self._preview_list.row(top_item)
        header_text = ""
        for row in range(top_row, -1, -1):
            item = self._preview_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole + 1) is not None:
                header_text = item.text()
                break
        if not header_text or top_row == 0:
            self._sticky_header.hide()
            return
        self._sticky_header.setText(header_text)
        vp = self._preview_list.viewport()
        self._sticky_header.setFixedWidth(vp.width())
        self._sticky_header.setFixedHeight(30)
        self._sticky_header.move(0, 0)
        self._sticky_header.show()
        self._sticky_header.raise_()

    def _on_preview_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self._preview_syncing:
            return
        state = self._selected_state()
        if state is None:
            return
        preview = None
        if current is not None:
            index = current.data(Qt.ItemDataRole.UserRole)
            if index is not None and 0 <= index < len(state.preview_items):
                state.selected_index = index
                preview = state.preview_items[index]
        self._sync_row_selection(self._preview_list)
        self._render_detail(state, preview)

    def _on_preview_item_changed(self, item: QListWidgetItem) -> None:
        if self._preview_syncing:
            return
        state = self._selected_state()
        if state is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        binding = state.check_vars.get(str(index))
        if binding is None:
            return
        binding.set(bool(item.data(_CHECKED_ROLE)))
        widget = self._preview_list.itemWidget(item)
        if isinstance(widget, _PreviewRowWidget):
            widget.set_checked(binding.get())
        state.checked = any(
            state.check_vars[str(i)].get()
            for i, preview in enumerate(state.preview_items)
            if preview.is_actionable
        )
        current_roster_item = self._roster_list.item(self._roster_list.currentRow())
        if current_roster_item is not None and current_roster_item.data(Qt.ItemDataRole.UserRole) is not None:
            self._roster_syncing = True
            current_roster_item.setData(_CHECKED_ROLE, state.checked)
            self._roster_syncing = False
            roster_widget = self._roster_list.itemWidget(current_roster_item)
            if isinstance(roster_widget, _RosterRowWidget):
                roster_widget.set_checked(state.checked)
        preview = state.preview_items[index]
        self._render_detail(state, preview)
        self._update_preview_master_state(state)
        self._update_action_bar()

    def _on_preview_master_changed(self, check_state: int) -> None:
        if self._preview_master_syncing:
            return
        state = self._selected_state()
        if state is None:
            return
        target = check_state == int(Qt.CheckState.Checked.value)
        self._preview_syncing = True
        try:
            for i, preview in enumerate(state.preview_items):
                if not preview.is_actionable:
                    continue
                binding = state.check_vars.get(str(i))
                if binding is not None:
                    binding.set(target)
                for row in range(self._preview_list.count()):
                    item = self._preview_list.item(row)
                    if item is not None and item.data(Qt.ItemDataRole.UserRole) == i:
                        item.setData(_CHECKED_ROLE, target)
                        w = self._preview_list.itemWidget(item)
                        if isinstance(w, _PreviewRowWidget):
                            w.set_checked(target)
                        break
        finally:
            self._preview_syncing = False
        state.checked = target
        current_roster_item = self._roster_list.item(self._roster_list.currentRow())
        if current_roster_item is not None and current_roster_item.data(Qt.ItemDataRole.UserRole) is not None:
            self._roster_syncing = True
            current_roster_item.setData(_CHECKED_ROLE, state.checked)
            self._roster_syncing = False
            roster_widget = self._roster_list.itemWidget(current_roster_item)
            if isinstance(roster_widget, _RosterRowWidget):
                roster_widget.set_checked(state.checked)
        self._update_preview_master_state(state)
        self._update_action_bar()

    def _update_preview_master_state(self, state: ScanState | None) -> None:
        if state is None:
            self._preview_master_check.setEnabled(False)
            self._preview_check_summary.setText("")
            return
        actionable = [(i, p) for i, p in enumerate(state.preview_items) if p.is_actionable]
        if not actionable or not _is_state_queue_approvable(state, media_type=self._media_type):
            self._preview_master_check.setEnabled(False)
            self._preview_master_check.setVisible(False)
            self._preview_check_summary.setVisible(False)
            return
        self._preview_master_check.setVisible(True)
        self._preview_check_summary.setVisible(True)
        self._preview_master_check.setEnabled(True)
        checked = 0
        for i, _ in actionable:
            binding = state.check_vars.get(str(i))
            if binding is not None and binding.get():
                checked += 1
        total = len(actionable)
        self._preview_master_syncing = True
        try:
            if checked == 0:
                self._preview_master_check.setCheckState(Qt.CheckState.Unchecked)
                self._preview_master_check.setText("Select All Files")
            elif checked == total:
                self._preview_master_check.setCheckState(Qt.CheckState.Checked)
                self._preview_master_check.setText("Deselect All Files")
            else:
                self._preview_master_check.setCheckState(Qt.CheckState.PartiallyChecked)
                self._preview_master_check.setText("Select All Files")
            self._preview_check_summary.setText(f"{checked} of {total} files checked")
        finally:
            self._preview_master_syncing = False

    def _render_detail(self, state: ScanState | None, preview: PreviewItem | None = None) -> None:
        if state is None:
            self._detail_panel.clear()
            return

        eligibility = self._queue_eligibility([state])
        self._detail_panel.set_selection(
            state,
            preview=preview,
            queue_reason=eligibility.reason,
            folder_plan=self._folder_plan_text(state),
        )

    def _check_all(self) -> None:
        for state in self._current_states():
            state.checked = _is_state_queue_approvable(state, media_type=self._media_type)
            self._ensure_check_bindings(state)
            for index, preview in enumerate(state.preview_items):
                state.check_vars[str(index)].set(bool(state.checked and preview.is_actionable))
        self.refresh_from_controller()

    def _uncheck_all(self) -> None:
        for state in self._current_states():
            state.checked = False
            for index in range(len(state.preview_items)):
                binding = state.check_vars.get(str(index))
                if binding is not None:
                    binding.set(False)
        self.refresh_from_controller()

    def _queue_selected_state(self) -> None:
        state = self._selected_state()
        if state is None:
            self.status_message.emit("Select a show before queueing.", 4000)
            return
        if not _is_state_queue_approvable(state, media_type=self._media_type):
            self.status_message.emit("This item is not approved for queueing.", 4000)
            return
        original_checked = state.checked
        state.checked = True
        try:
            self._queue_states([state], empty_message="Select a show before queueing.")
        finally:
            if not state.queued:
                state.checked = original_checked

    def _queue_checked(self) -> None:
        checked = [state for state in self._current_states() if state.checked]
        if not checked:
            self.status_message.emit("Select at least one actionable item before queueing.", 4000)
            return
        eligible = [s for s in checked if _is_state_queue_approvable(s, media_type=self._media_type)]
        skipped = len(checked) - len(eligible)
        if skipped and eligible:
            skip_reasons = self._summarize_skip_reasons(checked)
            detail = ", ".join(f"{count} {reason}" for reason, count in skip_reasons.items())
            answer = QMessageBox.question(
                self,
                "Queue Checked Items",
                f"Queueing {len(eligible)} of {len(checked)} checked — {detail} will be skipped.\n\nProceed?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._queue_states(checked, empty_message="Select at least one actionable item before queueing.")

    def _summarize_skip_reasons(self, states: list[ScanState]) -> dict[str, int]:
        reasons: dict[str, int] = {}
        for state in states:
            if _is_state_queue_approvable(state, media_type=self._media_type):
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

    def _queue_states(self, states: list[ScanState], *, empty_message: str) -> None:
        if self._media_ctrl is None or self._queue_ctrl is None:
            return
        if not states:
            self.status_message.emit(empty_message, 4000)
            return

        eligibility = self._queue_eligibility(states)
        if not eligibility.enabled:
            self.status_message.emit(eligibility.reason or "The selected items cannot be queued right now.", 4000)
            return

        try:
            if self._media_type == "movie":
                root = self._media_ctrl.movie_folder
                if root is None:
                    self.status_message.emit("No movie folder is loaded.", 4000)
                    return
                result = self._queue_ctrl.add_movie_batch(states, root, self._media_ctrl.command_gating)
            else:
                root = self._media_ctrl.tv_root_folder
                if root is None:
                    self.status_message.emit("No TV folder is loaded.", 4000)
                    return
                result = self._queue_ctrl.add_tv_batch(states, root, self._media_ctrl.command_gating)
        except Exception as exc:
            QMessageBox.warning(self, "Queue Failed", str(exc))
            return

        self._media_ctrl.sync_queued_states()
        self.refresh_from_controller()
        self.queue_changed.emit()
        self.status_message.emit(_format_batch_result(result), 5000)

    def _fix_match(self) -> None:
        state = self._selected_state()
        if state is None or self._media_ctrl is None or self._tmdb_provider is None:
            return
        if state.queued:
            self.status_message.emit("Remove the item from the queue before changing its match.", 4000)
            return

        tmdb = self._tmdb_provider()
        if tmdb is None:
            self.status_message.emit("TMDB is unavailable.", 4000)
            return

        if self._media_type == "movie":
            query_source = state.preview_items[0].original.stem if state.preview_items else state.folder.name
            title_key = "title"
            search_callback = tmdb.search_movie
            dialog_title = f"Fix Match: {query_source}"
        else:
            query_source = state.folder.name
            title_key = "name"
            search_callback = tmdb.search_tv
            dialog_title = f"Fix Match: {state.folder.name}"

        query = (
            best_tv_match_title(state.folder, include_year=False)
            if self._media_type == "tv"
            else clean_folder_name(query_source, include_year=False)
        )
        year_hint = extract_year(query_source)
        chosen = MatchPickerDialog.pick(
            title=dialog_title,
            title_key=title_key,
            initial_query=query,
            initial_results=state.search_results,
            search_callback=search_callback,
            year_hint=year_hint,
            raw_name=query,
            parent=self,
        )
        if not chosen:
            return

        try:
            if self._media_type == "movie":
                self._media_ctrl.rematch_movie_state(state, chosen)
                self.status_message.emit(f"Updated match to {state.display_name}.", 4000)
                self.refresh_from_controller()
                return

            self._media_ctrl.rematch_tv_state(state, chosen)
            self.refresh_from_controller()
            self._media_ctrl.scan_show(state, tmdb)
            self.status_message.emit(f"Re-matching {state.display_name}...", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Fix Match Failed", str(exc))

    def _queue_eligibility(self, states: list[ScanState]):
        if not states:
            return self._media_ctrl.command_gating.summarize_scan_states([], require_resolved_review=True)
        return self._media_ctrl.command_gating.summarize_scan_states(
            states,
            require_resolved_review=True,
            allow_show_level_queue=self._media_type == "tv",
        )

    def _update_action_bar(self) -> None:
        states = self._current_states()
        checked = [state for state in states if state.checked]
        self._update_roster_selection_header(states)
        selected_state = self._selected_state()
        self._fix_match_btn.setEnabled(bool(selected_state and not selected_state.queued and not selected_state.scanning))
        self._queue_inline_btn.setText("Queue This Show")
        if selected_state is None:
            self._queue_inline_btn.setEnabled(False)
            self._queue_inline_btn.setToolTip("")
        else:
            approvable = _is_state_queue_approvable(selected_state, media_type=self._media_type)
            self._queue_inline_btn.setEnabled(approvable)
            if approvable:
                self._queue_inline_btn.setToolTip("")
            else:
                inline_eligibility = self._queue_eligibility([selected_state])
                self._queue_inline_btn.setToolTip(inline_eligibility.reason or "")
        if checked:
            eligibility = self._queue_eligibility(checked)
            self._roster_queue_btn.setText(f"Queue {len(checked)} Checked")
            self._roster_queue_btn.setEnabled(eligibility.enabled)
            self._roster_queue_btn.setToolTip("" if eligibility.enabled else (eligibility.reason or ""))
        else:
            self._roster_queue_btn.setText("Queue Checked")
            self._roster_queue_btn.setEnabled(False)
            self._roster_queue_btn.setToolTip("Check at least one item to queue.")
        if selected_state is not None:
            self._render_detail(selected_state, self._selected_preview())

    def _update_roster_selection_header(self, states: list[ScanState]) -> None:
        eligible_states = [
            state for state in states
            if _is_state_queue_approvable(state, media_type=self._media_type)
        ]
        checked_count = sum(1 for state in eligible_states if state.checked)
        total_eligible = len(eligible_states)
        if total_eligible:
            noun = "item" if total_eligible == 1 else "items"
            self._roster_selection_summary.setText(f"{checked_count} of {total_eligible} eligible {noun} checked")
        else:
            self._roster_selection_summary.setText("No eligible items")

        self._roster_master_syncing = True
        try:
            self._roster_master_check.setEnabled(bool(total_eligible))
            if total_eligible == 0 or checked_count == 0:
                self._roster_master_check.setCheckState(Qt.CheckState.Unchecked)
                self._roster_master_check.setText("Select All")
            elif checked_count == total_eligible:
                self._roster_master_check.setCheckState(Qt.CheckState.Checked)
                self._roster_master_check.setText("Deselect All")
            else:
                self._roster_master_check.setCheckState(Qt.CheckState.PartiallyChecked)
                self._roster_master_check.setText("Select All")
        finally:
            self._roster_master_syncing = False

    def _request_roster_poster(self, state: ScanState, item: QListWidgetItem) -> None:
        if state.show_id is None or self._tmdb_provider is None:
            return
        key = (self._media_type, state.show_id)
        item.setData(Qt.ItemDataRole.UserRole + 2, key)
        cached = self._roster_poster_cache.get(key)
        if cached is not None:
            self._roster_poster_cache.move_to_end(key)
            widget = self._roster_list.itemWidget(item)
            if isinstance(widget, _RosterRowWidget):
                widget.set_poster(cached)
            return

        # Skip if a fetch for this key is already in flight.
        if key in self._poster_inflight:
            return
        tmdb = self._tmdb_provider()
        if tmdb is None:
            return
        self._poster_inflight.add(key)

        def _worker() -> None:
            try:
                image = tmdb.fetch_poster(state.show_id, media_type=self._media_type, target_width=185)
                if image is None:
                    return
                self._poster_bridge.poster_ready.emit(key, pil_to_raw(image))
            finally:
                self._poster_inflight.discard(key)

        threading.Thread(target=_worker, daemon=True, name="QtRosterPoster").start()

    def _apply_roster_poster(self, key, raw_data) -> None:
        pixmap = raw_to_pixmap(raw_data)
        if pixmap.isNull():
            return
        self._roster_poster_cache[key] = pixmap
        self._roster_poster_cache.move_to_end(key)
        while len(self._roster_poster_cache) > _MAX_ROSTER_POSTER_CACHE:
            self._roster_poster_cache.popitem(last=False)
        for row in range(self._roster_list.count()):
            item = self._roster_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole + 2) == key:
                widget = self._roster_list.itemWidget(item)
                if isinstance(widget, _RosterRowWidget):
                    widget.set_poster(pixmap)

    def _attach_roster_widget(self, item: QListWidgetItem, state: ScanState) -> None:
        existing = self._roster_list.itemWidget(item)
        if existing is not None:
            self._roster_list.removeItemWidget(item)
            existing.deleteLater()
        compact = self._is_compact_mode()
        widget = _RosterRowWidget(
            state,
            compact=compact,
            media_type=self._media_type,
            auto_accept_threshold=_auto_accept_threshold(self._settings),
            checkable=_is_state_queue_approvable(state, media_type=self._media_type),
            parent=self._roster_list,
        )
        widget.clicked.connect(lambda item=item: self._set_current_item(self._roster_list, item))
        widget.check_toggled.connect(
            lambda checked, item=item: self._set_item_check_state(item, checked, preview=False)
        )
        widget.alternate_confirmed.connect(
            lambda match, state=state: self._apply_alternate_match(state, match)
        )
        widget.approve_requested.connect(
            lambda state=state: self._approve_match(state)
        )
        widget.season_assign_requested.connect(
            lambda state=state: self._prompt_assign_season(state)
        )
        widget.geometry_changed.connect(lambda item=item, widget=widget: self._sync_item_height(item, widget))
        self._sync_item_height(item, widget)
        self._roster_list.setItemWidget(item, widget)
        key = item.data(Qt.ItemDataRole.UserRole + 2)
        if key in self._roster_poster_cache:
            widget.set_poster(self._roster_poster_cache[key])

    def _attach_preview_widget(self, item: QListWidgetItem, state: ScanState, index: int, preview: PreviewItem) -> None:
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
            parent=self._preview_list,
        )
        widget.clicked.connect(lambda item=item: self._set_current_item(self._preview_list, item))
        widget.check_toggled.connect(
            lambda checked, item=item: self._set_item_check_state(item, checked, preview=True)
        )
        self._sync_item_height(item, widget)
        self._preview_list.setItemWidget(item, widget)

    def _sync_item_height(self, item: QListWidgetItem, widget: QWidget) -> None:
        item.setSizeHint(QSize(0, widget.sizeHint().height()))

    def _set_current_item(self, list_widget: QListWidget, item: QListWidgetItem) -> None:
        list_widget.setCurrentItem(item)

    def _set_item_check_state(self, item: QListWidgetItem, checked: bool, *, preview: bool) -> None:
        syncing_attr = "_preview_syncing" if preview else "_roster_syncing"
        if getattr(self, syncing_attr):
            return
        setattr(self, syncing_attr, True)
        item.setData(_CHECKED_ROLE, checked)
        setattr(self, syncing_attr, False)
        if preview:
            self._on_preview_item_changed(item)
        else:
            self._on_roster_item_changed(item)

    def _sync_row_selection(self, list_widget: QListWidget) -> None:
        current = list_widget.currentItem()
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            widget = list_widget.itemWidget(item)
            if isinstance(widget, (_RosterRowWidget, _PreviewRowWidget)):
                widget.set_selected(item is current)

    def _approve_match(self, state: ScanState) -> None:
        if self._media_ctrl is None:
            return
        self._media_ctrl.approve_match(state)
        self.refresh_from_controller()
        self.status_message.emit("Match approved.", 3000)

    def _prompt_assign_season(self, state: ScanState) -> None:
        if self._media_ctrl is None:
            return
        current = state.season_assignment or 1
        season_num, ok = QInputDialog.getInt(
            self, "Assign Season",
            f"Season number for \"{state.display_name}\":",
            current, 0, 99,
        )
        if not ok:
            return
        self._media_ctrl.assign_season(state, season_num if season_num > 0 else None)
        label = f"Season {season_num}" if season_num > 0 else "cleared"
        self.status_message.emit(f"Season assignment: {label}.", 3000)

    def _apply_alternate_match(self, state: ScanState, match: dict) -> None:
        if self._media_ctrl is None:
            return
        try:
            if self._media_type == "movie":
                self._media_ctrl.rematch_movie_state(state, match)
                self.status_message.emit(f"Updated match to {state.display_name}.", 4000)
                self.refresh_from_controller()
                return

            tmdb = self._tmdb_provider() if self._tmdb_provider is not None else None
            if tmdb is None:
                self.status_message.emit("TMDB is unavailable.", 4000)
                return
            self._media_ctrl.rematch_tv_state(state, match)
            self.refresh_from_controller()
            self._media_ctrl.scan_show(state, tmdb)
            self.status_message.emit(f"Re-matching {state.display_name}...", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Fix Match Failed", str(exc))

    def _selected_preview(self) -> PreviewItem | None:
        state = self._selected_state()
        current = self._preview_list.currentItem()
        if state is None or current is None:
            return None
        index = current.data(Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= index < len(state.preview_items)):
            return None
        return state.preview_items[index]

    def _folder_plan_text(self, state: ScanState) -> str:
        source = state.folder.name
        if self._media_type == "movie":
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
        return f"Folder rename plan: {source} -> {target}"

class _CheckBinding:
    """Small checkbox binding used to reuse engine/controller helpers in Qt."""

    def __init__(self, value: bool) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


class _ClickableRow(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class _ToggleSwitch(QCheckBox):
    _SIZE = 20
    _RADIUS = 4
    _BG_OFF = QColor("#3a3a3a")
    _BG_ON = QColor("#3ea463")
    _BG_PARTIAL = QColor("#4a9eda")
    _BORDER_OFF = QColor("#555555")
    _BORDER_ON = QColor("#2d7a4a")
    _CHECK_COLOR = QColor("#ffffff")

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._SIZE, self._SIZE)

    def sizeHint(self) -> QSize:
        return QSize(self._SIZE, self._SIZE)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        state = self.checkState()
        if state == Qt.CheckState.Checked:
            bg, border = self._BG_ON, self._BORDER_ON
        elif state == Qt.CheckState.PartiallyChecked:
            bg, border = self._BG_PARTIAL, self._BG_PARTIAL
        else:
            bg, border = self._BG_OFF, self._BORDER_OFF

        s = self._SIZE
        margin = 1.5
        rect_f = QRectF(margin, margin, s - 2 * margin, s - 2 * margin)
        p.setBrush(bg)
        p.setPen(QPen(border, 1.5))
        p.drawRoundedRect(rect_f, self._RADIUS, self._RADIUS)

        pen = QPen(self._CHECK_COLOR, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if state == Qt.CheckState.Checked:
            # Checkmark
            p.drawLine(int(s * 0.25), int(s * 0.50), int(s * 0.43), int(s * 0.68))
            p.drawLine(int(s * 0.43), int(s * 0.68), int(s * 0.75), int(s * 0.32))
        elif state == Qt.CheckState.PartiallyChecked:
            # Dash
            y = s // 2
            p.drawLine(int(s * 0.28), y, int(s * 0.72), y)

        p.end()


class _MiniProgressBar(QWidget):
    def __init__(self, *, color: str, value: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._value = max(0, min(100, value))
        self.setFixedHeight(4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setValue(self, value: int) -> None:
        self._value = max(0, min(100, value))
        self.update()

    def setColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(120, 4)

    def paintEvent(self, event) -> None:
        del event
        rect = self.rect()
        if not rect.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(rect, 2, 2)
        fill_width = int(rect.width() * (self._value / 100.0))
        if fill_width <= 0:
            return
        fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
        painter.setBrush(self._color)
        painter.drawRoundedRect(fill_rect, 2, 2)


class _RosterRowWidget(_ClickableRow):
    check_toggled = Signal(bool)
    alternate_confirmed = Signal(object)
    approve_requested = Signal()
    season_assign_requested = Signal()
    geometry_changed = Signal()

    def __init__(
        self,
        state: ScanState,
        *,
        compact: bool,
        media_type: str,
        auto_accept_threshold: float,
        checkable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("rosterRowCard")
        self.setProperty("cssClass", "roster-row-card")
        self._state = state
        self._compact = compact
        self._media_type = media_type
        self._auto_accept_threshold = auto_accept_threshold
        self._selected = False
        self._pending_alternate: dict | None = None
        self._poster = QLabel()
        self._poster_size = QSize(34, 50) if compact else QSize(48, 70)
        self._poster.setFixedSize(self._poster_size)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shimmer: ShimmerOverlay | None = None
        if not compact:
            self._apply_placeholder_poster()
            self._shimmer = ShimmerOverlay(self._poster)
        self._poster.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = _ToggleSwitch(state.checked if checkable else False, self)
        self._check.setVisible(checkable)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        if not compact:
            layout.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title = QLabel(state.display_name)
        self._title.setProperty("cssClass", "row-title")
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self._title, stretch=1)

        self._status = QLabel(_state_status(state)[0].upper())
        self._status.setProperty("cssClass", "status-pill")
        self._status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(
            self._status,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        body.addLayout(title_row)

        meta_parts = [f"{_file_count_for_state(state)} file(s)"]
        if state.season_assignment is not None:
            meta_parts.append(f"Season {state.season_assignment}")
        if state.show_id is not None:
            meta_parts.append(_state_match_summary(state, auto_accept_threshold))
        if state.needs_review and state.alternate_matches and not state.queued:
            n_alts = min(len(state.alternate_matches), 2)
            meta_parts.append(f"{n_alts} alternative{'s' if n_alts != 1 else ''}")
        self._meta = QLabel(" · ".join(meta_parts))
        self._meta.setProperty("cssClass", "caption")
        self._meta.setWordWrap(True)
        self._meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._meta)

        self._confidence = _MiniProgressBar(
            color=_confidence_fill_color(self._state.confidence, state=self._state),
            value=clamped_percent(state.confidence),
        )
        body.addWidget(self._confidence)

        self._approve_btn = None
        if state.needs_review and state.show_id is not None and not state.queued and state.duplicate_of is None:
            self._approve_btn = QPushButton("Approve Match")
            self._approve_btn.setProperty("cssClass", "primary")
            self._approve_btn.setProperty("sizeVariant", "compact")
            self._approve_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._approve_btn.clicked.connect(self.approve_requested.emit)
            body.addWidget(self._approve_btn)

        self._season_btn = None
        if state.duplicate_of is not None and state.show_id is not None and self._media_type == "tv":
            label = f"Assign Season ({state.season_assignment})" if state.season_assignment else "Assign Season"
            self._season_btn = QPushButton(label)
            self._season_btn.setProperty("cssClass", "secondary")
            self._season_btn.setProperty("sizeVariant", "compact")
            self._season_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._season_btn.clicked.connect(self.season_assign_requested.emit)
            body.addWidget(self._season_btn)

        self._alternates_layout = None
        self._alternates_widget = None
        self._confirm_row = None
        if state.needs_review and state.alternate_matches and not state.queued:
            self._alternates_widget = QWidget()
            self._alternates_layout = QVBoxLayout()
            self._alternates_layout.setSpacing(3)
            self._alternates_layout.setContentsMargins(0, 0, 0, 0)
            alt_matches = state.alternate_matches[:2]
            for alt in alt_matches:
                alt_btn = QPushButton(_match_label(alt, media_type=self._media_type))
                alt_btn.setProperty("cssClass", "secondary")
                alt_btn.setProperty("sizeVariant", "compact")
                alt_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                alt_btn.clicked.connect(lambda _checked=False, alt=alt: self._begin_alternate_confirm(alt))
                self._alternates_layout.addWidget(alt_btn)
            self._alternates_widget.setLayout(self._alternates_layout)
            body.addWidget(self._alternates_widget)

            self._confirm_row = QWidget()
            confirm_layout = QVBoxLayout(self._confirm_row)
            confirm_layout.setContentsMargins(0, 0, 0, 0)
            confirm_layout.setSpacing(4)
            self._confirm_label = QLabel("")
            self._confirm_label.setProperty("cssClass", "caption")
            self._confirm_label.setWordWrap(True)
            confirm_layout.addWidget(self._confirm_label)
            confirm_actions = QHBoxLayout()
            confirm_actions.setContentsMargins(0, 0, 0, 0)
            confirm_actions.setSpacing(6)
            self._confirm_accept = QPushButton("Accept")
            self._confirm_accept.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._confirm_accept.clicked.connect(self._confirm_alternate)
            confirm_actions.addWidget(self._confirm_accept)
            self._confirm_cancel = QPushButton("Cancel")
            self._confirm_cancel.setProperty("cssClass", "secondary")
            self._confirm_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._confirm_cancel.clicked.connect(self._cancel_alternate)
            confirm_actions.addWidget(self._confirm_cancel)
            confirm_actions.addStretch()
            confirm_layout.addLayout(confirm_actions)
            self._confirm_row.hide()
            body.addWidget(self._confirm_row)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_checked(self, checked: bool) -> None:
        blocked = self._check.blockSignals(True)
        self._check.setChecked(checked)
        self._check.blockSignals(blocked)

    def set_poster(self, pixmap: QPixmap) -> None:
        if self._compact or pixmap.isNull():
            if not self._compact:
                self._apply_placeholder_poster()
            return
        if self._shimmer is not None:
            self._shimmer.stop()
            self._shimmer = None
        self._poster.setText("")
        self._poster.setPixmap(
            pixmap.scaled(
                self._poster.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _apply_placeholder_poster(self) -> None:
        title = _placeholder_initials(self._state.display_name)
        placeholder = build_placeholder_pixmap(
            self._poster_size,
            title=title,
            subtitle="",
            accent=_state_status(self._state)[1].name(),
        )
        self._poster.setPixmap(placeholder)
        self._poster.setText("")

    def _apply_style(self) -> None:
        self.setProperty("band", _confidence_band(self._state.confidence, state=self._state))
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        self._status.setProperty("tone", _state_status_tone(self._state))
        _repolish(self)
        _repolish(self._status)
        self._confidence.setColor(_confidence_fill_color(self._state.confidence, state=self._state))

    def _begin_alternate_confirm(self, match: dict) -> None:
        self._pending_alternate = match
        if self._confirm_row is None:
            return
        self._confirm_label.setText(f"Switch match to {_match_label(match, media_type=self._media_type)}?")
        if self._alternates_widget is not None:
            self._alternates_widget.hide()
        self._confirm_row.show()
        self.geometry_changed.emit()

    def _confirm_alternate(self) -> None:
        if self._pending_alternate is None:
            return
        pending = self._pending_alternate
        self._pending_alternate = None
        if self._confirm_row is not None:
            self._confirm_row.hide()
        if self._alternates_widget is not None:
            self._alternates_widget.show()
        self.geometry_changed.emit()
        self.alternate_confirmed.emit(pending)

    def _cancel_alternate(self) -> None:
        self._pending_alternate = None
        if self._confirm_row is not None:
            self._confirm_row.hide()
        if self._alternates_widget is not None:
            self._alternates_widget.show()
        self.geometry_changed.emit()


class _PreviewRowWidget(_ClickableRow):
    check_toggled = Signal(bool)

    def __init__(
        self,
        preview: PreviewItem,
        *,
        compact: bool,
        show_confidence: bool,
        show_companions: bool,
        checked: bool,
        checkable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self._preview = preview
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = _ToggleSwitch(checked if preview.is_actionable and checkable else False, self)
        self._check.setVisible(preview.is_actionable and checkable)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        original = _preview_heading(preview, compact=compact)
        self._original = QLabel(original)
        self._original.setProperty("cssClass", "row-title")
        self._original.setWordWrap(True)
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._original, stretch=1)

        self._status = QLabel(_preview_status_label(preview))
        self._status.setProperty("cssClass", "status-pill")
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(top_row)

        self._target = QLabel(_preview_target_text(preview))
        self._target.setProperty("cssClass", "row-target")
        self._target.setWordWrap(True)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._target)

        if show_companions and preview.companions:
            self._companions = QLabel(_companion_summary(preview))
            self._companions.setProperty("cssClass", "caption")
            self._companions.setWordWrap(True)
            self._companions.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            body.addWidget(self._companions)
        else:
            self._companions = None

        self._confidence = None
        if show_confidence:
            self._confidence = _MiniProgressBar(
                color=_preview_band(self._preview),
                value=clamped_percent(preview.episode_confidence),
            )
            body.addWidget(self._confidence)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_checked(self, checked: bool) -> None:
        if not self._check.isVisible():
            return
        blocked = self._check.blockSignals(True)
        self._check.setChecked(checked)
        self._check.blockSignals(blocked)

    def _apply_style(self) -> None:
        self.setProperty("band", _preview_band_name(self._preview))
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        self._status.setProperty("tone", _preview_status_tone(self._preview))
        _repolish(self)
        _repolish(self._status)
        if self._confidence is not None:
            self._confidence.setColor(_preview_band(self._preview))


