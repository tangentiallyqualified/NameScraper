"""Media workspace widget for TV Shows and Movies tabs.

Manages the EMPTY -> SCANNING -> READY state machine via a
QStackedWidget. The READY state shows a controller-backed 3-panel
workspace with roster, preview, and selection/detail summaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState, score_tv_results
from ...parsing import best_tv_match_title, clean_folder_name, extract_year
from ...parsing import build_movie_name, build_show_folder_name
from ._media_workspace_roster import (
    _CHECKED_ROLE,
    _ROSTER_ENTRY_KEY_ROLE,
    _ROSTER_ENTRY_KIND_ROLE,
    MediaWorkspaceRosterPanel,
)
from ._media_workspace_preview import (
    _PREVIEW_ENTRY_KIND_ROLE,
    _PREVIEW_SECTION_ROLE,
    MediaWorkspacePreviewPanel,
)
from ._media_helpers import (
    format_batch_result as _format_batch_result,
    is_plex_ready_state as _is_plex_ready_state,
    is_state_queue_approvable as _is_state_queue_approvable,
    roster_group as _roster_group,
    roster_selection_key as _roster_selection_key,
    state_key as _state_key,
)
from ._media_workspace_sync import MediaWorkspaceSyncCoordinator
from ._workspace_widgets import (
    _CheckBinding,
    PreviewRowWidget as _PreviewRowWidget,
    RosterRowWidget as _RosterRowWidget,
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
_FOLDER_SECTION_KEY = "folder"


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
        self._preview_group_state: dict[str, set[int | str]] = {}
        self._roster_collapsed: dict[str, bool] = {"plex-ready": True}
        self._roster_selection_is_auto = False
        self._pending_roster_selection_auto: bool | None = None
        self._build_ui()
        self._sync_coordinator = MediaWorkspaceSyncCoordinator(self)

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

        self._roster_panel = MediaWorkspaceRosterPanel(
            media_type=self._media_type,
            settings_service=self._settings,
            tmdb_provider=self._tmdb_provider,
            set_item_check_state_callback=lambda item, checked: self._set_item_check_state(
                item,
                checked,
                preview=False,
            ),
            prompt_assign_season_callback=self._prompt_assign_season,
        )
        self._roster_list = self._roster_panel.list_widget
        self._roster_master_check = self._roster_panel.master_check
        self._roster_selection_summary = self._roster_panel.selection_summary
        self._roster_queue_btn = self._roster_panel.queue_button
        self._roster_master_check.stateChanged.connect(self._on_roster_master_changed)
        self._roster_queue_btn.clicked.connect(self._queue_checked)
        self._roster_list.itemChanged.connect(self._on_roster_item_changed)
        self._roster_list.itemClicked.connect(self._on_roster_item_clicked)
        self._roster_list.currentItemChanged.connect(self._on_roster_current_item_changed)
        self._set_roster_queue_button_text("Queue Checked")

        self._preview_panel = MediaWorkspacePreviewPanel(
            media_type=self._media_type,
            settings_service=self._settings,
            set_item_check_state_callback=lambda item, checked: self._set_item_check_state(
                item,
                checked,
                preview=True,
            ),
        )
        self._preview_list = self._preview_panel.list_widget
        self._preview_master_check = self._preview_panel.master_check
        self._preview_check_summary = self._preview_panel.check_summary
        self._fix_match_btn = self._preview_panel.fix_match_button
        self._queue_inline_btn = self._preview_panel.primary_action_button
        self._folder_plan_label = self._preview_panel.folder_plan_label
        self._preview_summary = self._preview_panel.summary_label
        self._sticky_header = self._preview_panel.sticky_header
        self._preview_master_check.stateChanged.connect(self._on_preview_master_changed)
        self._fix_match_btn.clicked.connect(self._fix_match)
        self._queue_inline_btn.clicked.connect(self._activate_selected_primary_action)
        self._queue_inline_btn.setText(self._queue_selected_label())
        self._sync_action_button_metrics()
        self._preview_list.itemChanged.connect(self._on_preview_item_changed)
        self._preview_list.currentItemChanged.connect(self._on_preview_current_item_changed)
        self._preview_list.itemClicked.connect(self._on_preview_item_clicked)

        self._detail_panel = MediaDetailPanel(
            tmdb_provider=self._tmdb_provider,
            settings_service=self._settings,
        )
        self._detail_panel.setProperty("panelVariant", "square")
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
        self._activate_selected_primary_action()

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
        self._set_item_check_state(item, not state.checked, preview=False)

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
        if self._roster_panel.master_syncing:
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
            self._folder_plan_label.setText("")
            self._set_preview_summary("Preview items will appear here once a scan is ready.")
            self._detail_panel.clear()
            self._roster_selection_is_auto = False
            self._pending_roster_selection_auto = None
            self._roster_queue_btn.setEnabled(False)
            self._set_roster_queue_button_text("Queue Checked")
            self._roster_queue_btn.setToolTip("")
            self._update_roster_selection_header([])
            self._fix_match_btn.setEnabled(False)
            self._fix_match_btn.setText("Fix Match")
            self._queue_inline_btn.setEnabled(False)
            self._queue_inline_btn.setText(self._queue_selected_label())
            return

        selected_index = self._media_ctrl.library_selected_index
        selection_is_auto = self._roster_selection_is_auto
        if selected_state_key is not None:
            matched_index = next(
                (index for index, state in enumerate(states) if _roster_selection_key(state) == selected_state_key),
                None,
            )
            if matched_index is not None:
                selected_index = matched_index

        preferred_focus_index = self._preferred_batch_focus_index(states)
        if preferred_focus_index is not None:
            if selected_state_key is None:
                selected_index = preferred_focus_index
                selection_is_auto = True
            elif (
                selection_is_auto
                and selected_index is not None
                and 0 <= selected_index < len(states)
                and _roster_group(states[selected_index]) not in {"matched", "review"}
            ):
                selected_index = preferred_focus_index
                selection_is_auto = True

        if selected_index is None or not (0 <= selected_index < len(states)):
            selected_index = preferred_focus_index if preferred_focus_index is not None else 0
            selection_is_auto = True
        selected_state = self._media_ctrl.select_show(selected_index)

        selected_item = self._find_roster_item_by_index(selected_index)
        if selected_item is not None:
            self._set_roster_current_item(selected_item, auto_selected=selection_is_auto)

        if selected_state is not None:
            self._ensure_check_bindings(selected_state)
            self._populate_preview(selected_state)
            self._render_detail(selected_state, self._selected_preview())
        self._update_action_bar()
        self._sync_row_selection(self._roster_list)

    def _sync_roster_items(self, states: list[ScanState]) -> None:
        self._roster_panel.sync_items(states, collapsed_groups=self._roster_collapsed)

    def _find_roster_item_by_index(self, index: int) -> QListWidgetItem | None:
        return self._roster_panel.find_item_by_index(index)

    def _set_roster_current_item(self, item: QListWidgetItem, *, auto_selected: bool) -> None:
        if self._roster_list.currentItem() is item:
            self._roster_selection_is_auto = auto_selected
            self._pending_roster_selection_auto = None
            return
        self._pending_roster_selection_auto = auto_selected
        self._roster_list.setCurrentItem(item)
        if self._pending_roster_selection_auto is not None:
            self._roster_selection_is_auto = auto_selected
            self._pending_roster_selection_auto = None

    def _preferred_batch_focus_index(self, states: list[ScanState]) -> int | None:
        if len(states) <= 1:
            return None
        for group in ("matched", "review"):
            for index, state in enumerate(states):
                if _roster_group(state) == group:
                    return index
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
                    bool(
                        state.checked
                        and item.is_actionable
                        and _is_state_queue_approvable(state, media_type=self._media_type)
                    )
                )

    def _normalize_queue_selection(self, states: list[ScanState]) -> None:
        for state in states:
            if _is_state_queue_approvable(state, media_type=self._media_type):
                self._ensure_check_bindings(state)
                actionable_values: list[bool] = []
                for index, item in enumerate(state.preview_items):
                    if not item.is_actionable:
                        continue
                    key = str(index)
                    binding = state.check_vars.get(key)
                    if binding is not None:
                        actionable_values.append(binding.get())
                if actionable_values:
                    state.checked = any(actionable_values)
                elif state.preview_items:
                    state.checked = False
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
        self._sync_coordinator.on_roster_current_item_changed(current)

    def _on_roster_item_changed(self, item: QListWidgetItem) -> None:
        self._sync_coordinator.on_roster_item_changed(item)

    def _set_state_checked(self, state: ScanState, checked: bool) -> None:
        self._sync_coordinator.set_state_checked(state, checked)

    def _populate_preview(self, state: ScanState) -> None:
        self._preview_syncing = True
        self._preview_list.setUpdatesEnabled(False)
        self._preview_panel.populate_from_state(
            state,
            preview_group_state=self._preview_group_state,
            folder_section_key=_FOLDER_SECTION_KEY,
            ensure_check_bindings=self._ensure_check_bindings,
            folder_plan_text=self._folder_plan_text,
            folder_preview_data=self._folder_preview_data,
            season_ratio_text=self._season_ratio_text,
        )
        self._preview_syncing = False
        self._preview_list.setUpdatesEnabled(True)
        self._sync_row_selection(self._preview_list)
        self._update_preview_master_state(state)

    def _on_preview_item_clicked(self, item: QListWidgetItem) -> None:
        if self._preview_syncing:
            return
        state = self._selected_state()
        if state is None:
            return
        if item.data(_PREVIEW_ENTRY_KIND_ROLE) != "header":
            return
        section_key = item.data(_PREVIEW_SECTION_ROLE)
        if section_key is None:
            return
        collapsed = self._preview_group_state.setdefault(_state_key(state), set())
        if section_key in collapsed:
            collapsed.remove(section_key)
        else:
            collapsed.add(section_key)
        self._populate_preview(state)

    def _update_sticky_header(self) -> None:
        self._preview_panel.update_sticky_header()

    def _on_preview_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._sync_coordinator.on_preview_current_item_changed(current)

    def _on_preview_item_changed(self, item: QListWidgetItem) -> None:
        self._sync_coordinator.on_preview_item_changed(item)

    def _on_preview_master_changed(self, check_state: int) -> None:
        self._sync_coordinator.on_preview_master_changed(check_state)

    def _update_preview_master_state(self, state: ScanState | None) -> None:
        self._preview_panel.update_master_state(state)

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
            self.status_message.emit(f"Select a {self._media_noun()} before queueing.", 4000)
            return
        if not _is_state_queue_approvable(state, media_type=self._media_type):
            self.status_message.emit(f"This {self._media_noun()} is not approved for queueing.", 4000)
            return
        original_checked = state.checked
        state.checked = True
        try:
            self._queue_states([state], empty_message=f"Select a {self._media_noun()} before queueing.")
        finally:
            if not state.queued:
                state.checked = original_checked

    def _activate_selected_primary_action(self) -> None:
        state = self._selected_state()
        if state is None:
            self.status_message.emit(f"Select a {self._media_noun()} first.", 4000)
            return
        if self._can_inline_assign_season(state):
            self._prompt_assign_season(state)
            return
        if self._needs_inline_match_choice(state):
            self._fix_match()
            return
        if self._can_inline_approve(state):
            self._approve_match(state)
            return
        self._queue_selected_state()

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

        selected_key = _roster_selection_key(self._selected_state())

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
        self._restore_roster_selection_by_key(selected_key)
        self.queue_changed.emit()
        self.status_message.emit(_format_batch_result(result), 5000)

    def _fix_match(self) -> None:
        state = self._selected_state()
        if state is None or self._media_ctrl is None or self._tmdb_provider is None:
            return
        selected_key = _roster_selection_key(state)
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
            dialog_title = f"{self._fix_match_label(state)}: {query_source}"
            score_results_callback = None
        else:
            query_source = state.folder.name
            title_key = "name"
            search_callback = tmdb.search_tv
            dialog_title = f"{self._fix_match_label(state)}: {state.folder.name}"
            score_results_callback = None

        query = (
            best_tv_match_title(state.folder, include_year=False)
            if self._media_type == "tv"
            else clean_folder_name(query_source, include_year=False)
        )
        year_hint = extract_year(query_source)
        if self._media_type == "tv":
            score_results_callback = lambda results: score_tv_results(
                results,
                query,
                year_hint,
                tmdb,
                folder=state.folder,
            )
        chosen = MatchPickerDialog.pick(
            title=dialog_title,
            title_key=title_key,
            initial_query=query,
            initial_results=state.search_results,
            search_callback=search_callback,
            score_results_callback=score_results_callback,
            year_hint=year_hint,
            raw_name=query,
            parent=self,
        )
        if not chosen:
            return

        try:
            if self._media_type == "movie":
                self._media_ctrl.rematch_movie_state(state, chosen)
                self.refresh_from_controller()
                self._restore_roster_selection_by_key(selected_key)
                self.status_message.emit(f"Updated match to {state.display_name}.", 4000)
                return

            updated_state = self._media_ctrl.rematch_tv_state(state, chosen, tmdb)
            self.refresh_from_controller()
            self._restore_roster_selection_by_key(_roster_selection_key(updated_state))
            self._media_ctrl.scan_show(updated_state, tmdb)
            if updated_state.scanned or updated_state.preview_items:
                self.refresh_from_controller()
                self._restore_roster_selection_by_key(_roster_selection_key(updated_state))
            self.status_message.emit(f"Re-matching {updated_state.display_name}...", 4000)
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
        can_fix = bool(selected_state and self._can_fix_match(selected_state))
        self._fix_match_btn.setEnabled(can_fix)
        self._fix_match_btn.setText(self._fix_match_label(selected_state))
        self._fix_match_btn.setToolTip("")
        self._queue_inline_btn.setText(self._primary_action_label(selected_state))
        if selected_state is None:
            self._queue_inline_btn.setEnabled(False)
            self._queue_inline_btn.setToolTip("")
        else:
            if (
                self._can_inline_assign_season(selected_state)
                or self._needs_inline_match_choice(selected_state)
                or self._can_inline_approve(selected_state)
            ):
                self._queue_inline_btn.setEnabled(True)
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
            self._set_roster_queue_button_text(f"Queue {len(checked)} Checked")
            self._roster_queue_btn.setEnabled(eligibility.enabled)
            self._roster_queue_btn.setToolTip("" if eligibility.enabled else (eligibility.reason or ""))
        else:
            self._set_roster_queue_button_text("Queue Checked")
            self._roster_queue_btn.setEnabled(False)
            self._roster_queue_btn.setToolTip("Check at least one item to queue.")
        if selected_state is not None:
            self._render_detail(selected_state, self._selected_preview())

    def _set_roster_queue_button_text(self, text: str) -> None:
        self._roster_panel.set_queue_button_text(text)
        self._sync_action_button_metrics()

    def _sync_action_button_metrics(self) -> None:
        if not hasattr(self, "_queue_inline_btn"):
            return
        button_height = max(self._queue_inline_btn.sizeHint().height(), self._roster_queue_btn.sizeHint().height())
        self._queue_inline_btn.setMinimumHeight(button_height)
        self._roster_queue_btn.setMinimumHeight(button_height)

    def _set_preview_summary(self, text: str) -> None:
        self._preview_panel.set_summary(text)

    def _update_roster_selection_header(self, states: list[ScanState]) -> None:
        self._roster_panel.update_selection_header(states)

    def _attach_preview_widget(self, item: QListWidgetItem, state: ScanState, index: int, preview: PreviewItem) -> None:
        self._preview_panel.attach_preview_widget(item, state, index, preview)

    def _attach_folder_preview_widget(self, item: QListWidgetItem, source_name: str, target_name: str) -> None:
        self._preview_panel.attach_folder_preview_widget(item, source_name, target_name)

    def _set_item_check_state(self, item: QListWidgetItem, checked: bool, *, preview: bool) -> None:
        self._sync_coordinator.set_item_check_state(item, checked, preview=preview)

    def _sync_row_selection(self, list_widget: QListWidget) -> None:
        self._sync_coordinator.sync_row_selection(list_widget)

    def _approve_match(self, state: ScanState) -> None:
        if self._media_ctrl is None:
            return
        if state.duplicate_of is not None or state.queued or state.scanning:
            self.status_message.emit("This item cannot be approved in its current state.", 3000)
            return
        self._media_ctrl.approve_match(state)
        self.refresh_from_controller()
        self.status_message.emit("Match approved.", 3000)

    def _prompt_assign_season(self, state: ScanState) -> None:
        if self._media_ctrl is None:
            return
        selected_key = _roster_selection_key(state)
        current = state.season_assignment or 1
        season_num, ok = QInputDialog.getInt(
            self, "Assign Season",
            f"Season number for \"{state.display_name}\":",
            current, 0, 99,
        )
        if not ok:
            return
        effective_state = self._media_ctrl.assign_season(
            state, season_num if season_num > 0 else None,
        )
        self.refresh_from_controller()
        follow_up_state = effective_state if effective_state is not None else state
        self._restore_roster_selection_by_key(_roster_selection_key(follow_up_state))
        # In batch TV, assign_season either merged siblings (target was
        # reset_scan'd) or invalidated its own scan data; in both cases the
        # preview needs to be rebuilt with the new season hint.
        if (
            self._media_type == "tv"
            and season_num > 0
            and follow_up_state.show_id is not None
        ):
            tmdb = self._tmdb_provider() if self._tmdb_provider is not None else None
            if tmdb is not None:
                try:
                    self._media_ctrl.scan_show(follow_up_state, tmdb)
                except Exception as exc:
                    QMessageBox.warning(self, "Scan Failed", str(exc))
                if follow_up_state.scanned or follow_up_state.preview_items:
                    self.refresh_from_controller()
                    self._restore_roster_selection_by_key(
                        _roster_selection_key(follow_up_state)
                    )
        label = f"Season {season_num}" if season_num > 0 else "cleared"
        self.status_message.emit(f"Season assignment: {label}.", 3000)

    def _apply_alternate_match(self, state: ScanState, match: dict) -> None:
        if self._media_ctrl is None:
            return
        selected_key = _roster_selection_key(state)
        try:
            if self._media_type == "movie":
                self._media_ctrl.rematch_movie_state(state, match)
                self.refresh_from_controller()
                self._restore_roster_selection_by_key(selected_key)
                self.status_message.emit(f"Updated match to {state.display_name}.", 4000)
                return

            tmdb = self._tmdb_provider() if self._tmdb_provider is not None else None
            if tmdb is None:
                self.status_message.emit("TMDB is unavailable.", 4000)
                return
            updated_state = self._media_ctrl.rematch_tv_state(state, match, tmdb)
            self.refresh_from_controller()
            self._restore_roster_selection_by_key(_roster_selection_key(updated_state))
            self._media_ctrl.scan_show(updated_state, tmdb)
            if updated_state.scanned or updated_state.preview_items:
                self.refresh_from_controller()
                self._restore_roster_selection_by_key(_roster_selection_key(updated_state))
            self.status_message.emit(f"Re-matching {updated_state.display_name}...", 4000)
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
        folder_preview = self._folder_preview_data(state)
        if folder_preview is None:
            return ""
        source, target = folder_preview
        return f"Folder rename plan: {source} -> {target}"

    def _folder_preview_data(self, state: ScanState) -> tuple[str, str] | None:
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
        if not source or not target:
            return None
        return source, target

    def _media_noun(self) -> str:
        return "movie" if self._media_type == "movie" else "show"

    def _queue_selected_label(self) -> str:
        return f"Queue This {'Movie' if self._media_type == 'movie' else 'Show'}"

    def _primary_action_label(self, state: ScanState | None) -> str:
        if state is not None and self._can_inline_assign_season(state):
            return "Assign Season"
        if state is not None and self._needs_inline_match_choice(state):
            return "Choose Match"
        if state is not None and self._can_inline_approve(state):
            return "Approve Match"
        return self._queue_selected_label()

    def _fix_match_label(self, state: ScanState | None) -> str:
        if state is not None and self._needs_inline_match_choice(state):
            return "Choose Match"
        return "Fix Match"

    def _needs_inline_match_choice(self, state: ScanState) -> bool:
        return (
            state.show_id is not None
            and state.tie_detected
            and state.needs_review
            and not state.queued
            and not state.scanning
            and state.duplicate_of is None
        )

    def _can_inline_assign_season(self, state: ScanState) -> bool:
        return (
            self._media_type == "tv"
            and state.show_id is not None
            and state.duplicate_of is not None
            and state.season_assignment is None
            and not state.queued
            and not state.scanning
        )

    def _can_inline_approve(self, state: ScanState) -> bool:
        return (
            state.show_id is not None
            and state.needs_review
            and not state.tie_detected
            and not state.queued
            and not state.scanning
            and state.duplicate_of is None
        )

    def _can_fix_match(self, state: ScanState) -> bool:
        return not state.queued and not state.scanning

    def _restore_roster_selection_by_key(self, state_key: str | None) -> None:
        if state_key is None:
            return
        for index, state in enumerate(self._current_states()):
            if _roster_selection_key(state) != state_key:
                continue
            item = self._find_roster_item_by_index(index)
            if item is not None:
                self._set_roster_current_item(item, auto_selected=self._roster_selection_is_auto)
                self._scroll_roster_item_into_context(item)
            return

    def _scroll_roster_item_into_context(self, item: QListWidgetItem) -> None:
        row = self._roster_list.row(item)
        if row < 0:
            return
        anchor = item
        for index in range(row - 1, -1, -1):
            header = self._roster_list.item(index)
            if header is not None and header.data(_ROSTER_ENTRY_KIND_ROLE) == "header":
                anchor = header
                break
        self._roster_list.scrollToItem(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

    def _season_ratio_text(self, state: ScanState, season_num: int | None, item_count: int) -> str:
        expected = self._season_expected_count(state, season_num)
        if expected <= 0:
            expected = item_count
        return f" — {item_count}/{expected}"

    def _season_expected_count(self, state: ScanState, season_num: int | None) -> int:
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


