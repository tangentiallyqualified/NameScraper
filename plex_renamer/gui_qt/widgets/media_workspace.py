"""Media workspace widget for TV Shows and Movies tabs.

Manages the EMPTY -> SCANNING -> READY state machine via a
QStackedWidget. The READY state shows a controller-backed 3-panel
workspace with roster, preview, and selection/detail summaries.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ...parsing import clean_folder_name, extract_year
from ...parsing import build_movie_name, build_show_folder_name
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


class _RosterPosterBridge(QObject):
    poster_ready = Signal(object, object)


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
        self._roster_poster_cache: dict[tuple[str, int], QIcon] = {}
        self._preview_group_state: dict[str, set[int]] = {}
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
        roster_layout = QVBoxLayout(self._roster_panel)
        roster_layout.setContentsMargins(12, 12, 12, 12)
        roster_layout.setSpacing(8)
        self._roster_title = QLabel("Library")
        self._roster_title.setProperty("cssClass", "heading")
        roster_layout.addWidget(self._roster_title)
        self._roster_hint = QLabel("Scanned items appear here.")
        self._roster_hint.setProperty("cssClass", "caption")
        roster_layout.addWidget(self._roster_hint)
        self._roster_list = QListWidget()
        self._roster_list.setIconSize(QSize(42, 60))
        self._roster_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._roster_list.itemChanged.connect(self._on_roster_item_changed)
        self._roster_list.currentItemChanged.connect(self._on_roster_current_item_changed)
        roster_layout.addWidget(self._roster_list, stretch=1)

        self._preview_panel = QFrame()
        self._preview_panel.setProperty("cssClass", "panel")
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
        self._queue_inline_btn = QPushButton("Add to Queue")
        self._queue_inline_btn.setEnabled(False)
        self._queue_inline_btn.clicked.connect(self._queue_checked)
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
        self._preview_list = QListWidget()
        self._preview_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._preview_list.itemChanged.connect(self._on_preview_item_changed)
        self._preview_list.currentItemChanged.connect(self._on_preview_current_item_changed)
        self._preview_list.itemClicked.connect(self._on_preview_item_clicked)
        preview_layout.addWidget(self._preview_list, stretch=1)

        self._detail_panel = MediaDetailPanel(
            tmdb_provider=self._tmdb_provider,
            settings_service=self._settings,
        )

        self._splitter.addWidget(self._roster_panel)
        self._splitter.addWidget(self._preview_panel)
        self._splitter.addWidget(self._detail_panel)

        # Default proportions: ~20% roster, ~50% preview, ~30% detail
        self._splitter.setSizes([250, 600, 370])
        self._splitter.setChildrenCollapsible(False)

        ready_layout.addWidget(self._splitter, stretch=1)

        # Bottom action bar
        self._action_bar = _ActionBar(media_type=self._media_type)
        self._action_bar.check_all_requested.connect(self._check_all)
        self._action_bar.uncheck_all_requested.connect(self._uncheck_all)
        self._action_bar.queue_requested.connect(self._queue_checked)
        ready_layout.addWidget(self._action_bar)

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
        self._stack.setCurrentIndex(_EMPTY)
        self._empty_state.refresh_recent_folders()

    def show_scanning(self) -> None:
        """Switch to the scanning state and start the timer."""
        self._scan_progress.start()
        self._stack.setCurrentIndex(_SCANNING)

    def show_ready(self) -> None:
        """Switch to the 3-panel ready state."""
        self._scan_progress.stop()
        self._stack.setCurrentIndex(_READY)
        self.refresh_from_controller()

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

    def refresh_from_controller(self) -> None:
        """Rebuild the ready-state roster and preview from controller state."""
        if self._media_ctrl is None:
            return

        states = self._current_states()
        self._roster_syncing = True
        self._roster_list.clear()
        groups = [
            ("queued", "Queued"),
            ("plex-ready", "Plex Ready"),
            ("matched", "Matched"),
            ("review", "Needs Review"),
            ("unmatched", "Unmatched"),
            ("duplicate", "Duplicates"),
        ]
        for key, title in groups:
            indices = [index for index, state in enumerate(states) if _roster_group(state) == key]
            if not indices:
                continue
            header = _make_section_header(title)
            self._roster_list.addItem(header)

            for index in indices:
                state = states[index]
                item = QListWidgetItem(self._format_roster_text(state))
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(self._state_tooltip(state))
                item.setForeground(self._state_color(state))
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(
                    Qt.CheckState.Checked if state.checked else Qt.CheckState.Unchecked
                )
                self._roster_list.addItem(item)
                self._attach_roster_widget(item, state)
                self._request_roster_poster(state, item)
        self._roster_syncing = False

        if not states:
            self._preview_list.clear()
            self._folder_plan_label.setText("Select a roster item to see the planned folder rename.")
            self._preview_summary.setText("Preview items will appear here once a scan is ready.")
            self._detail_panel.clear()
            self._action_bar.update_summary(0, 0)
            self._action_bar.set_queue_enabled(False)
            self._fix_match_btn.setEnabled(False)
            self._fix_match_btn.setEnabled(False)
            self._queue_inline_btn.setEnabled(False)
            self._queue_inline_btn.setText("Add to Queue")
            return

        selected_index = self._media_ctrl.library_selected_index
        if selected_index is None or selected_index >= len(states):
            selected_index = 0
            self._media_ctrl.select_show(0)

        for row in range(self._roster_list.count()):
            item = self._roster_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == selected_index:
                self._roster_list.setCurrentRow(row)
                break
        self._update_action_bar()
        self._sync_row_selection(self._roster_list)

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
                state.check_vars[key] = _CheckBinding(item.is_actionable)

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
        state.checked = item.checkState() == Qt.CheckState.Checked
        widget = self._roster_list.itemWidget(item)
        if isinstance(widget, _RosterRowWidget):
            widget.set_checked(state.checked)
        self._update_action_bar()
        if row == self._roster_list.currentRow():
            self._render_detail(state)

    def _populate_preview(self, state: ScanState) -> None:
        self._preview_syncing = True
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
                header = _make_section_header(
                    ("▸ " if is_collapsed else "▾ ") + _season_label(season_num),
                    selectable=True,
                )
                header.setData(Qt.ItemDataRole.UserRole + 1, season_num)
                self._preview_list.addItem(header)
                if is_collapsed:
                    continue
                for index in indices:
                    self._preview_list.addItem(self._build_preview_row(state, index, state.preview_items[index]))
        else:
            for index, preview in enumerate(state.preview_items):
                self._preview_list.addItem(self._build_preview_row(state, index, preview))

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
        self._sync_row_selection(self._preview_list)

    def _build_preview_row(self, state: ScanState, index: int, preview: PreviewItem) -> QListWidgetItem:
        row = QListWidgetItem(self._format_preview_text(preview))
        row.setData(Qt.ItemDataRole.UserRole, index)
        row.setToolTip(self._preview_tooltip(preview))
        row.setForeground(_preview_color(preview))
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if preview.is_actionable:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
            row.setCheckState(
                Qt.CheckState.Checked
                if state.check_vars[str(index)].get()
                else Qt.CheckState.Unchecked
            )
        row.setFlags(flags)
        self._attach_preview_widget(row, state, index, preview)
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
        binding.set(item.checkState() == Qt.CheckState.Checked)
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
            current_roster_item.setCheckState(
                Qt.CheckState.Checked if state.checked else Qt.CheckState.Unchecked
            )
            self._roster_syncing = False
            roster_widget = self._roster_list.itemWidget(current_roster_item)
            if isinstance(roster_widget, _RosterRowWidget):
                roster_widget.set_checked(state.checked)
        preview = state.preview_items[index]
        self._render_detail(state, preview)
        self._update_action_bar()

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
            state.checked = True
            self._ensure_check_bindings(state)
            for index, preview in enumerate(state.preview_items):
                if preview.is_actionable:
                    state.check_vars[str(index)].set(True)
        self.refresh_from_controller()

    def _uncheck_all(self) -> None:
        for state in self._current_states():
            state.checked = False
            for index in range(len(state.preview_items)):
                binding = state.check_vars.get(str(index))
                if binding is not None:
                    binding.set(False)
        self.refresh_from_controller()

    def _queue_checked(self) -> None:
        if self._media_ctrl is None or self._queue_ctrl is None:
            return
        states = [state for state in self._current_states() if state.checked]
        if not states:
            self.status_message.emit("Select at least one actionable item before queueing.", 4000)
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

        query = clean_folder_name(query_source, include_year=False)
        year_hint = extract_year(query_source)
        chosen = MatchPickerDialog.pick(
            title=dialog_title,
            title_key=title_key,
            initial_query=query,
            initial_results=state.search_results,
            search_callback=search_callback,
            year_hint=year_hint,
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
            return self._media_ctrl.command_gating.summarize_scan_states([])
        return self._media_ctrl.command_gating.summarize_scan_states(
            states,
            allow_show_level_queue=self._media_type == "tv",
        )

    def _update_action_bar(self) -> None:
        states = self._current_states()
        checked = [state for state in states if state.checked]
        self._action_bar.update_summary(len(checked), len(states))
        selected_state = self._selected_state()
        self._fix_match_btn.setEnabled(bool(selected_state and not selected_state.queued and not selected_state.scanning))
        if not checked:
            self._action_bar.set_queue_enabled(False)
            self._queue_inline_btn.setEnabled(False)
            self._queue_inline_btn.setText("Add to Queue")
            return
        eligibility = self._queue_eligibility(checked)
        self._action_bar.set_queue_enabled(eligibility.enabled)
        self._queue_inline_btn.setEnabled(eligibility.enabled)
        self._queue_inline_btn.setText(f"Add {len(checked)} to Queue")
        if selected_state is not None:
            self._render_detail(selected_state, self._selected_preview())

    def _request_roster_poster(self, state: ScanState, item: QListWidgetItem) -> None:
        if state.show_id is None or self._tmdb_provider is None:
            return
        key = (self._media_type, state.show_id)
        item.setData(Qt.ItemDataRole.UserRole + 2, key)
        cached = self._roster_poster_cache.get(key)
        if cached is not None:
            item.setIcon(cached)
            widget = self._roster_list.itemWidget(item)
            if isinstance(widget, _RosterRowWidget):
                widget.set_poster(cached.pixmap(self._roster_list.iconSize()))
            return

        tmdb = self._tmdb_provider()
        if tmdb is None:
            return

        def _worker() -> None:
            image = tmdb.fetch_poster(state.show_id, media_type=self._media_type, target_width=42)
            if image is None:
                return
            pixmap = QPixmap.fromImage(ImageQt(image.convert("RGBA")))
            self._poster_bridge.poster_ready.emit(key, pixmap)

        threading.Thread(target=_worker, daemon=True, name="QtRosterPoster").start()

    def _apply_roster_poster(self, key, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        icon = QIcon(pixmap)
        self._roster_poster_cache[key] = icon
        for row in range(self._roster_list.count()):
            item = self._roster_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole + 2) == key:
                item.setIcon(icon)
                widget = self._roster_list.itemWidget(item)
                if isinstance(widget, _RosterRowWidget):
                    widget.set_poster(pixmap)

    def _attach_roster_widget(self, item: QListWidgetItem, state: ScanState) -> None:
        compact = self._settings is not None and self._settings.view_mode == "compact"
        widget = _RosterRowWidget(state, compact=compact, parent=self._roster_list)
        widget.clicked.connect(lambda item=item: self._set_current_item(self._roster_list, item))
        widget.check_toggled.connect(
            lambda checked, item=item: self._set_item_check_state(item, checked, preview=False)
        )
        item.setSizeHint(widget.sizeHint())
        self._roster_list.setItemWidget(item, widget)
        key = item.data(Qt.ItemDataRole.UserRole + 2)
        if key in self._roster_poster_cache:
            widget.set_poster(self._roster_poster_cache[key].pixmap(self._roster_list.iconSize()))

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
            parent=self._preview_list,
        )
        widget.clicked.connect(lambda item=item: self._set_current_item(self._preview_list, item))
        widget.check_toggled.connect(
            lambda checked, item=item: self._set_item_check_state(item, checked, preview=True)
        )
        item.setSizeHint(widget.sizeHint())
        self._preview_list.setItemWidget(item, widget)

    def _set_current_item(self, list_widget: QListWidget, item: QListWidgetItem) -> None:
        list_widget.setCurrentItem(item)

    def _set_item_check_state(self, item: QListWidgetItem, checked: bool, *, preview: bool) -> None:
        syncing_attr = "_preview_syncing" if preview else "_roster_syncing"
        if getattr(self, syncing_attr):
            return
        setattr(self, syncing_attr, True)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
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

    def _selected_preview(self) -> PreviewItem | None:
        state = self._selected_state()
        current = self._preview_list.currentItem()
        if state is None or current is None:
            return None
        index = current.data(Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= index < len(state.preview_items)):
            return None
        return state.preview_items[index]

    def _format_roster_text(self, state: ScanState) -> str:
        status, _color = _state_status(state)
        compact = self._settings is not None and self._settings.view_mode == "compact"
        if self._media_type == "movie":
            if compact:
                return f"{state.display_name} · {status} · {len(state.preview_items)} file(s)"
            return f"{state.display_name}\n{status} · {len(state.preview_items)} file(s)"
        if compact:
            return f"{state.display_name} · {status} · {state.file_count} file(s)"
        return f"{state.display_name}\n{status} · {state.file_count} file(s)"

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

    def _state_tooltip(self, state: ScanState) -> str:
        lines = [state.display_name, _state_status(state)[0], f"Folder: {state.folder}"]
        if state.duplicate_of:
            lines.append(f"Duplicate of {state.duplicate_of}")
        if state.discovery_reason:
            lines.append(f"Discovery: {state.discovery_reason}")
        return "\n".join(lines)

    def _state_color(self, state: ScanState) -> QColor:
        return _state_status(state)[1]

    def _format_preview_text(self, preview: PreviewItem) -> str:
        rename = preview.new_name or "No rename target"
        extra = ""
        compact = self._settings is not None and self._settings.view_mode == "compact"
        if preview.season is not None and preview.episodes:
            episode_text = ", ".join(f"E{ep:02d}" for ep in preview.episodes)
            extra = f"S{preview.season:02d} {episode_text} · "
        companion_suffix = ""
        if self._settings is not None and self._settings.show_companion_files and preview.companions:
            noun = "file" if len(preview.companions) == 1 else "files"
            companion_suffix = f" · +{len(preview.companions)} companion {noun}"
        if compact:
            return f"{extra}{preview.original.name} -> {rename}{companion_suffix}"
        return f"{extra}{preview.original.name}\n-> {rename}{companion_suffix}"

    def _preview_tooltip(self, preview: PreviewItem) -> str:
        target_dir = preview.target_dir or preview.original.parent
        lines = [
            preview.status,
            f"Source: {preview.original}",
            f"Target: {target_dir / (preview.new_name or preview.original.name)}",
        ]
        if self._settings is not None and self._settings.show_companion_files and preview.companions:
            companion_names = ", ".join(companion.original.name for companion in preview.companions)
            lines.append(f"Companions: {companion_names}")
        return "\n".join(lines)


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

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class _RosterRowWidget(_ClickableRow):
    check_toggled = Signal(bool)

    def __init__(self, state: ScanState, *, compact: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._compact = compact
        self._selected = False
        self._poster = QLabel()
        self._poster.setFixedSize(32, 46) if compact else self._poster.setFixedSize(42, 60)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster.setText("No Poster" if not compact else "")
        self._poster.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self._check = QCheckBox()
        self._check.setChecked(state.checked)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        if not compact:
            layout.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._title = QLabel(state.display_name)
        self._title.setWordWrap(True)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self._title, stretch=1)

        self._status = QLabel(_state_status(state)[0].upper())
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignRight)
        body.addLayout(title_row)

        meta_parts = [f"{_file_count_for_state(state)} file(s)"]
        if state.show_id is not None:
            meta_parts.append(f"{int(state.confidence * 100)}% match")
        self._meta = QLabel(" · ".join(meta_parts))
        self._meta.setProperty("cssClass", "caption")
        self._meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._meta)

        self._confidence = QProgressBar()
        self._confidence.setTextVisible(False)
        self._confidence.setFixedHeight(4)
        self._confidence.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._confidence.setRange(0, 100)
        self._confidence.setValue(int(state.confidence * 100))
        body.addWidget(self._confidence)

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
            return
        self._poster.setText("")
        self._poster.setPixmap(
            pixmap.scaled(
                self._poster.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _apply_style(self) -> None:
        band = _confidence_band(self._state.confidence, state=self._state)
        band_color = {"high": "#3ea463", "medium": "#e5a00d", "low": "#d44040", "muted": "#777777"}[band]
        bg = "#1f1a0e" if self._selected else "#1c1c1c"
        border = "#e5a00d" if self._selected else "#2a2a2a"
        self.setStyleSheet(
            f"background-color: {bg}; border: 1px solid {border}; border-left: 4px solid {band_color}; border-radius: 8px;"
        )
        self._title.setStyleSheet("font-weight: 600; color: #e0e0e0;")
        self._meta.setStyleSheet("color: #777777; font-size: 11px;")
        self._status.setStyleSheet(_status_pill_stylesheet(_state_status_tone(self._state)))
        self._confidence.setStyleSheet(_confidence_bar_stylesheet(_confidence_fill_color(self._state.confidence)))


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preview = preview
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self._check = QCheckBox()
        self._check.setVisible(preview.is_actionable)
        self._check.setChecked(checked if preview.is_actionable else False)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        original = _preview_heading(preview, compact=compact)
        self._original = QLabel(original)
        self._original.setWordWrap(True)
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._original, stretch=1)

        self._status = QLabel(_preview_status_label(preview))
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(top_row)

        self._target = QLabel(_preview_target_text(preview, compact=compact))
        self._target.setWordWrap(True)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._target)

        if show_companions and preview.companions:
            self._companions = QLabel(_companion_summary(preview))
            self._companions.setWordWrap(True)
            self._companions.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            body.addWidget(self._companions)
        else:
            self._companions = None

        self._confidence = None
        if show_confidence:
            self._confidence = QProgressBar()
            self._confidence.setTextVisible(False)
            self._confidence.setFixedHeight(4)
            self._confidence.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._confidence.setRange(0, 100)
            self._confidence.setValue(int(preview.episode_confidence * 100))
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
        bg = "#1f1a0e" if self._selected else "#1c1c1c"
        border = "#e5a00d" if self._selected else "#2a2a2a"
        band = _preview_band(self._preview)
        self.setStyleSheet(
            f"background-color: {bg}; border: 1px solid {border}; border-left: 3px solid {band}; border-radius: 8px;"
        )
        self._original.setStyleSheet("font-weight: 600; color: #e0e0e0;")
        self._target.setStyleSheet("color: #e5a00d;")
        self._status.setStyleSheet(_status_pill_stylesheet(_preview_status_tone(self._preview)))
        if self._companions is not None:
            self._companions.setStyleSheet("color: #777777; font-size: 11px;")
        if self._confidence is not None:
            self._confidence.setStyleSheet(_confidence_bar_stylesheet(_preview_band(self._preview)))


def _file_count_for_state(state: ScanState) -> int:
    if state.preview_items:
        return len(state.preview_items)
    if state.file_count:
        return state.file_count
    return 0


def _confidence_band(score: float, *, state: ScanState | None = None) -> str:
    if state is not None and (state.duplicate_of is not None or state.queued or state.scanning):
        return "muted"
    if score >= 0.85:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _confidence_fill_color(score: float) -> str:
    return {
        "high": "#3ea463",
        "medium": "#e5a00d",
        "low": "#d44040",
        "muted": "#777777",
    }[_confidence_band(score)]


def _state_status_tone(state: ScanState) -> str:
    if state.queued:
        return "info"
    if state.duplicate_of is not None:
        return "muted"
    if state.scanning:
        return "accent"
    if state.show_id is None:
        return "error"
    if state.needs_review:
        return "accent"
    if state.scanned and state.all_skipped:
        return "muted"
    if state.scanned:
        return "success"
    return "info"


def _preview_status_label(preview: PreviewItem) -> str:
    if preview.is_conflict:
        return "CONFLICT"
    if preview.is_unmatched:
        return "UNMATCHED"
    if preview.is_review:
        return "NEEDS REVIEW"
    if preview.is_skipped:
        return "SKIP"
    return "OK"


def _preview_status_tone(preview: PreviewItem) -> str:
    if preview.is_conflict or preview.is_unmatched:
        return "error"
    if preview.is_review:
        return "accent"
    if preview.is_skipped:
        return "muted"
    return "success"


def _preview_band(preview: PreviewItem) -> str:
    if preview.is_conflict or preview.is_unmatched:
        return "#d44040"
    if preview.is_skipped:
        return "#777777"
    return _confidence_fill_color(preview.episode_confidence)


def _status_pill_stylesheet(tone: str) -> str:
    palette = {
        "success": ("#1a3328", "#3ea463"),
        "accent": ("#2a2210", "#e5a00d"),
        "error": ("#2d1414", "#d44040"),
        "info": ("#142030", "#4a9eda"),
        "muted": ("#1e1e1e", "#888888"),
    }
    bg, fg = palette[tone]
    return (
        f"background-color: {bg}; color: {fg}; border: 1px solid {fg}; "
        "border-radius: 10px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
    )


def _confidence_bar_stylesheet(color: str) -> str:
    return (
        "QProgressBar { background: #2a2a2a; border: 0; border-radius: 2px; }"
        f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
    )


def _preview_heading(preview: PreviewItem, *, compact: bool) -> str:
    if compact:
        if preview.season is not None and preview.episodes:
            episode_text = ", ".join(f"E{ep:02d}" for ep in preview.episodes)
            return f"S{preview.season:02d} {episode_text} · {preview.original.name}"
        return preview.original.name
    return preview.original.name


def _preview_target_text(preview: PreviewItem, *, compact: bool) -> str:
    rename = preview.new_name or "No rename target"
    if compact:
        return f"-> {rename}"
    return f"-> {rename}"


def _companion_summary(preview: PreviewItem) -> str:
    if not preview.companions:
        return ""
    names = ", ".join(companion.original.name for companion in preview.companions[:2])
    extra = ""
    if len(preview.companions) > 2:
        extra = f" +{len(preview.companions) - 2} more"
    return f"Companions: {names}{extra}"


def _state_status(state: ScanState) -> tuple[str, QColor]:
    if state.queued:
        return "Queued", QColor("#4a9eda")
    if state.duplicate_of is not None:
        return "Duplicate", QColor("#777777")
    if state.scanning:
        return "Scanning", QColor("#e5a00d")
    if state.show_id is None:
        return "Unmatched", QColor("#d44040")
    if state.needs_review:
        return "Needs Review", QColor("#e5a00d")
    if state.scanned and state.all_skipped:
        return "No Action Needed", QColor("#777777")
    if state.scanned:
        return "Ready", QColor("#3ea463")
    return "Matched", QColor("#4a9eda")


def _roster_group(state: ScanState) -> str:
    if state.queued:
        return "queued"
    if state.duplicate_of is not None:
        return "duplicate"
    if state.show_id is None:
        return "unmatched"
    if state.needs_review:
        return "review"
    if state.scanned:
        return "plex-ready"
    return "matched"


def _state_key(state: ScanState) -> str:
    return f"{state.folder}:{state.show_id or 'unmatched'}"


def _season_label(season_num: int | None) -> str:
    if season_num is None:
        return "Other Files"
    return f"Season {season_num}"


def _make_section_header(text: str, *, selectable: bool = False) -> QListWidgetItem:
    header = QListWidgetItem(text.upper())
    header.setData(Qt.ItemDataRole.UserRole, None)
    flags = Qt.ItemFlag.ItemIsEnabled
    if selectable:
        flags |= Qt.ItemFlag.ItemIsSelectable
    header.setFlags(flags)
    header.setForeground(QColor("#f0b429"))
    header.setBackground(QColor("#2a2110"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(10)
    header.setFont(font)
    header.setSizeHint(QSize(0, 34))
    return header


def _preview_color(preview: PreviewItem) -> QColor:
    if preview.is_conflict or preview.is_unmatched:
        return QColor("#d44040")
    if preview.is_review:
        return QColor("#e5a00d")
    if preview.is_skipped:
        return QColor("#777777")
    return QColor("#e0e0e0")


def _format_batch_result(result) -> str:
    parts = []
    if result.added:
        parts.append(f"Queued {result.added} job(s)")
    if result.total_skipped:
        parts.append(f"Skipped {result.total_skipped}")
    if result.blocked:
        parts.append(f"Blocked {len(result.blocked)}")
    if result.errors:
        parts.append(f"Errors: {len(result.errors)}")
    return " · ".join(parts) if parts else "No queueable items were selected."


class _ActionBar(QFrame):
    """Bottom action bar for the ready state workspace."""

    check_all_requested = Signal()
    uncheck_all_requested = Signal()
    queue_requested = Signal()

    def __init__(
        self,
        media_type: str = "tv",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self.setStyleSheet(
            "background-color: #151515; border-top: 1px solid #2a2a2a;"
        )
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)

        self._summary_label = QLabel("0 of 0 items checked")
        layout.addWidget(self._summary_label)

        layout.addStretch()

        self._check_all_btn = QPushButton("Check All")
        self._check_all_btn.setProperty("cssClass", "secondary")
        self._check_all_btn.clicked.connect(self.check_all_requested.emit)
        layout.addWidget(self._check_all_btn)

        self._uncheck_all_btn = QPushButton("Uncheck All")
        self._uncheck_all_btn.setProperty("cssClass", "secondary")
        self._uncheck_all_btn.clicked.connect(self.uncheck_all_requested.emit)
        layout.addWidget(self._uncheck_all_btn)

        self._queue_btn = QPushButton("Add to Queue")
        self._queue_btn.clicked.connect(self.queue_requested.emit)
        layout.addWidget(self._queue_btn)
        self._queue_btn.setEnabled(False)

    def update_summary(self, checked: int, total: int) -> None:
        noun = "items" if self._media_type == "movie" else "shows"
        self._summary_label.setText(f"{checked} of {total} {noun} checked")
        if checked:
            self._queue_btn.setText(f"Add {checked} to Queue")
        else:
            self._queue_btn.setText("Add to Queue")

    def set_queue_enabled(self, enabled: bool) -> None:
        self._queue_btn.setEnabled(enabled)
