# plex_renamer/gui_qt/widgets/_work_panel.py
"""MediaWorkPanel — header / season strip / toolbar / episode table / footer
assembly for the GUI V4 work panel (Plan 3, spec §3.2-§3.3).

Replaces the old three-panel roster/preview/detail split for the "middle"
work surface. The expansion card (Task 3) is wired to the table's persistent
editor in Task 5; this task only assembles the surrounding chrome.
"""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from .. import _scale
from ._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
from ._episode_table_model import EpisodeTableModel
from ._formatting import clamped_percent
from ._media_helpers import (
    is_state_queue_approvable as _is_state_queue_approvable,
    state_status,
    state_status_tone,
)
from ._workspace_widget_primitives import MasterCheckBox
from .segmented_control import SegmentedControl
from .status_chip import season_strip_specs

_MAX_OVERVIEW_CACHE_ENTRIES = 64


class _OverviewBridge(QObject):
    overview_ready = Signal(str, str)   # text, token


def _overview_token(state: ScanState, media_type: str) -> str:
    return f"{state.show_id}:{media_type}"


class MediaWorkPanel(QFrame):
    filter_changed = Signal(str)          # "all"|"problems"|"unmapped"
    search_changed = Signal(str)
    approve_all_clicked = Signal()
    unassign_all_clicked = Signal()
    season_chip_clicked = Signal(int)     # season number (0 = specials)
    master_check_changed = Signal(int)    # movie mode master
    overview_toggled = Signal(bool)

    def __init__(
        self,
        *,
        media_type: str,
        settings_service=None,
        tmdb_provider=None,
        guide_provider=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._tmdb_provider = tmdb_provider
        self._guide_provider = guide_provider
        self._state: ScanState | None = None
        self._current_token: str = ""
        self._overview_cache: "OrderedDict[str, str]" = OrderedDict()
        self._loading_tokens: set[str] = set()
        self._overview_expanded = False
        self._master_syncing = False
        self._bridge = _OverviewBridge()
        self._bridge.overview_ready.connect(self._on_overview_ready)
        self.setProperty("cssClass", "panel")
        self.setProperty("panelVariant", "square")
        self._build_ui()

    # -- Consumed-by-action-bar aliases ------------------------------------

    @property
    def fix_match_button(self) -> QPushButton:
        return self._fix_match_button

    @property
    def primary_action_button(self) -> QPushButton:
        return self._primary_action_button

    @property
    def queue_preflight_label(self) -> QLabel:
        return self._queue_preflight_label

    @property
    def master_check(self) -> MasterCheckBox:
        return self._master_check

    @property
    def check_summary(self) -> QLabel:
        return self._check_summary

    @property
    def table_view(self) -> EpisodeTableView:
        return self._table_view

    @property
    def model(self) -> EpisodeTableModel:
        return self._model

    @property
    def search_box(self) -> QLineEdit:
        return self._search_box

    @property
    def segmented_filter(self) -> SegmentedControl:
        return self._segmented_filter

    @property
    def approve_all_button(self) -> QPushButton:
        return self._approve_all_button

    @property
    def unassign_all_button(self) -> QPushButton:
        return self._unassign_all_button

    @property
    def summary_label(self) -> QLabel:
        return self._summary_label

    @property
    def master_syncing(self) -> bool:
        return self._master_syncing

    # -- UI scaffold ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        margin = _scale.px(12)
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(_scale.px(8))

        self._build_header(outer)
        self._build_strip(outer)
        self._build_toolbar(outer)
        self._build_table(outer)
        self._build_footer(outer)

    def _build_header(self, outer: QVBoxLayout) -> None:
        title_row = QHBoxLayout()
        self._title_label = QLabel("")
        self._title_label.setProperty("cssClass", "heading")
        title_row.addWidget(self._title_label)

        self._source_pill = QLabel("")
        self._source_pill.setProperty("cssClass", "status-pill")
        self._source_pill.setProperty("tone", "info")
        title_row.addWidget(self._source_pill)

        self._status_pill = QLabel("")
        self._status_pill.setProperty("cssClass", "status-pill")
        title_row.addWidget(self._status_pill)
        title_row.addStretch()
        outer.addLayout(title_row)

        overview_row = QHBoxLayout()
        self._overview_label = QLabel("")
        self._overview_label.setWordWrap(True)
        overview_row.addWidget(self._overview_label, stretch=1)
        self._overview_toggle = QPushButton("more")
        self._overview_toggle.setProperty("cssClass", "secondary")
        self._overview_toggle.setProperty("sizeVariant", "inline")
        self._overview_toggle.hide()
        self._overview_toggle.clicked.connect(self._on_overview_toggle_clicked)
        overview_row.addWidget(self._overview_toggle)
        outer.addLayout(overview_row)
        self._apply_overview_clamp()

        self._discovery_label = QLabel("")
        self._discovery_label.setProperty("cssClass", "caption")
        self._discovery_label.hide()
        outer.addWidget(self._discovery_label)

    def _build_strip(self, outer: QVBoxLayout) -> None:
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(_scale.px(36))

        strip_host = QWidget()
        self._strip_layout = QHBoxLayout(strip_host)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(_scale.px(4))
        self._strip_layout.addStretch()
        self._strip_scroll.setWidget(strip_host)
        self._strip_buttons: list[QPushButton] = []
        outer.addWidget(self._strip_scroll)

    def _build_toolbar(self, outer: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()

        self._segmented_filter = SegmentedControl(["All", "Problems", "Unmapped"])
        self._segmented_filter.currentTextChanged.connect(self._on_filter_text_changed)
        toolbar.addWidget(self._segmented_filter)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter filenames…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self.search_changed.emit)
        toolbar.addWidget(self._search_box)

        self._master_check = MasterCheckBox("Select All")
        self._master_check.setTristate(True)
        self._master_check.hide()
        self._master_check.stateChanged.connect(self.master_check_changed.emit)
        toolbar.addWidget(self._master_check)

        self._check_summary = QLabel("")
        self._check_summary.setProperty("cssClass", "caption")
        self._check_summary.hide()
        toolbar.addWidget(self._check_summary)

        toolbar.addStretch()

        self._unassign_all_button = QPushButton("Unassign All")
        self._unassign_all_button.setProperty("cssClass", "secondary")
        self._unassign_all_button.setProperty("sizeVariant", "compact")
        self._unassign_all_button.hide()
        self._unassign_all_button.clicked.connect(self.unassign_all_clicked.emit)
        toolbar.addWidget(self._unassign_all_button)

        self._approve_all_button = QPushButton("Approve All")
        self._approve_all_button.setProperty("cssClass", "primary")
        self._approve_all_button.setProperty("sizeVariant", "compact")
        self._approve_all_button.hide()
        self._approve_all_button.clicked.connect(self.approve_all_clicked.emit)
        toolbar.addWidget(self._approve_all_button)

        outer.addLayout(toolbar)

    def _build_table(self, outer: QVBoxLayout) -> None:
        self._model = EpisodeTableModel(
            media_type=self._media_type,
            settings_service=self._settings,
            guide_provider=self._guide_provider,
        )
        self._table_view = EpisodeTableView()
        self._table_view.setModel(self._model)
        self._delegate = EpisodeTableDelegate(self._table_view, media_type=self._media_type)
        self._table_view.setItemDelegate(self._delegate)
        self._table_view.header_clicked.connect(self._on_header_clicked)
        outer.addWidget(self._table_view, stretch=1)

    def _build_footer(self, outer: QVBoxLayout) -> None:
        footer = QHBoxLayout()

        self._summary_label = QLabel("")
        self._summary_label.setProperty("cssClass", "caption")
        footer.addWidget(self._summary_label)

        self._queue_preflight_label = QLabel("")
        self._queue_preflight_label.setProperty("cssClass", "caption")
        self._queue_preflight_label.hide()
        footer.addWidget(self._queue_preflight_label)

        footer.addStretch()

        self._fix_match_button = QPushButton("Fix Match")
        self._fix_match_button.setProperty("cssClass", "secondary")
        self._fix_match_button.setEnabled(False)
        footer.addWidget(self._fix_match_button)

        self._primary_action_button = QPushButton("")
        self._primary_action_button.setEnabled(False)
        footer.addWidget(self._primary_action_button)

        outer.addLayout(footer)

    # -- Public API -------------------------------------------------------

    def show_state(
        self,
        state: ScanState | None,
        *,
        collapsed_sections: set[str],
        folder_preview: tuple[str, str] | None = None,
    ) -> None:
        self._state = state
        self._model.show_state(state, collapsed_sections=collapsed_sections, folder_preview=folder_preview)
        self.refresh_header(state)
        self.update_toolbar(state)
        self.update_footer()
        self._sync_movie_mode_visibility()

    def clear(self, message: str = "Select a roster item to begin.") -> None:
        self._state = None
        self._current_token = ""
        self._overview_cache.clear()
        self._loading_tokens.clear()
        self._title_label.setText("")
        self._source_pill.setText("")
        self._status_pill.setText("")
        self._overview_label.setText(message)
        self._overview_toggle.hide()
        self._discovery_label.hide()
        self._clear_strip()
        self._model.show_state(None, collapsed_sections=set())
        self._summary_label.setText("")
        self._queue_preflight_label.hide()
        self._approve_all_button.hide()
        self._unassign_all_button.hide()
        self._master_check.hide()
        self._check_summary.hide()

    def update_master_state(self, state: ScanState | None) -> None:
        """Movie-mode master checkbox tri-state. TV mode hides the control.

        Ported from ``MediaWorkspacePreviewPanel.update_master_state`` (the TV
        branch just hides; the movie branch is verbatim)."""
        if self._media_type != "movie":
            self._master_check.setEnabled(False)
            self._master_check.hide()
            self._check_summary.hide()
            return
        if state is None:
            self._master_check.setEnabled(False)
            self._check_summary.setText("")
            return
        actionable = [
            (index, preview)
            for index, preview in enumerate(state.preview_items)
            if preview.is_actionable
        ]
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

    def refresh_header(self, state: ScanState | None) -> None:
        if state is None:
            self.clear()
            return
        self._title_label.setText(state.display_name)
        source = (state.active_episode_source or "tmdb").upper()
        self._source_pill.setText(f"{source} · {clamped_percent(state.confidence)}%")
        status_text, _color = state_status(state, media_type=self._media_type)
        tone = state_status_tone(state, media_type=self._media_type)
        tone = "warning" if tone == "accent" else tone
        self._status_pill.setText(status_text.upper())
        self._status_pill.setProperty("tone", tone)
        self._repolish(self._status_pill)

        show_discovery = self._settings is not None and self._settings.show_discovery_info
        if show_discovery and state.discovery_reason:
            self._discovery_label.setText(f"Discovery: {state.discovery_reason}")
            self._discovery_label.show()
        else:
            self._discovery_label.hide()

        self._refresh_strip(state)
        self._request_overview(state)

    def update_footer(self) -> None:
        self._summary_label.setText(self._model.summary_text())

    def update_toolbar(self, state: ScanState | None) -> None:
        is_movie = self._media_type == "movie"
        self._segmented_filter.setVisible(not is_movie)
        self._search_box.setVisible(not is_movie)
        if is_movie or state is None:
            self._approve_all_button.hide()
            self._unassign_all_button.hide()
            return
        guide = self._model.guide()
        has_review = guide is not None and any(row.status == "Review" for row in guide.rows)
        self._approve_all_button.setVisible(has_review)
        self._sync_unassign_all_button(state)

    def scroll_to_season(self, season: int) -> None:
        section_key = self._model.season_section_key(season)
        header_row = self._model.section_header_row(section_key)
        if header_row < 0:
            return
        target_row = header_row
        if self._is_season_fully_missing(season):
            problem_row = self._model.first_problem_row_in_season(season)
            if problem_row >= 0:
                target_row = problem_row
        index = self._model.index(target_row, 0)
        self._table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
        self._delegate.flash_row(target_row)

    # -- Toolbar signal handlers -------------------------------------------

    def _on_filter_text_changed(self, text: str) -> None:
        mode = text.casefold()
        self._model.set_filter_mode(mode)
        self.filter_changed.emit(mode)

    def _on_header_clicked(self, section_key: str) -> None:
        self._model.toggle_section(section_key)

    # -- Toolbar rule helpers (copied from _sync_unassign_all_button) -------

    def _sync_unassign_all_button(self, state: ScanState) -> None:
        table = state.assignments
        has_assignments = table is not None and any(
            preview.file_id is not None
            and table.assignment_for(preview.file_id) is not None
            for preview in state.preview_items
        )
        self._unassign_all_button.setVisible(has_assignments)
        self._unassign_all_button.setEnabled(
            has_assignments and not state.queued and not state.scanning
        )

    def _is_season_fully_missing(self, season: int) -> bool:
        guide = self._model.guide()
        if guide is None:
            return False
        season_rows = [row for row in guide.rows if row.season == season]
        return bool(season_rows) and all(row.status == "Missing File" for row in season_rows)

    def _sync_movie_mode_visibility(self) -> None:
        if self._media_type != "movie":
            return
        self._strip_scroll.hide()

    # -- Season strip --------------------------------------------------------

    def _clear_strip(self) -> None:
        for button in self._strip_buttons:
            button.setParent(None)
            button.deleteLater()
        self._strip_buttons = []

    def _refresh_strip(self, state: ScanState) -> None:
        self._clear_strip()
        if self._media_type == "movie":
            self._strip_scroll.hide()
            return
        specs = season_strip_specs(state.completeness)
        if not specs:
            self._strip_scroll.hide()
            return
        self._strip_scroll.show()
        # Insert before the trailing stretch (index len-1).
        insert_at = self._strip_layout.count() - 1
        for season_num, chip in specs:
            button = QPushButton(chip.text)
            button.setProperty("cssClass", "season-strip-chip")
            button.setProperty("tone", chip.tone)
            button.setToolTip(chip.tooltip)
            button.setFlat(True)
            button.clicked.connect(lambda _checked=False, s=season_num: self._on_season_chip_clicked(s))
            self._strip_layout.insertWidget(insert_at, button)
            insert_at += 1
            self._strip_buttons.append(button)

    def _on_season_chip_clicked(self, season: int) -> None:
        # Scrolling is owned by the workspace connection
        # (panel.season_chip_clicked.connect(panel.scroll_to_season)); a
        # standalone panel still emits the signal for callers that want it.
        self.season_chip_clicked.emit(season)

    # -- Overview (async, minimal reimplementation of _media_detail_workflow) -

    def _apply_overview_clamp(self) -> None:
        clamped_height = 2 * self._overview_label.fontMetrics().lineSpacing() + _scale.px(4)
        if self._overview_expanded:
            self._overview_label.setMaximumHeight(16777215)
        else:
            self._overview_label.setMaximumHeight(clamped_height)

    def _on_overview_toggle_clicked(self) -> None:
        self._overview_expanded = not self._overview_expanded
        self._apply_overview_clamp()
        self._overview_toggle.setText("less" if self._overview_expanded else "more")
        self.overview_toggled.emit(self._overview_expanded)

    def _request_overview(self, state: ScanState) -> None:
        token = _overview_token(state, self._media_type)
        self._current_token = token
        tmdb = self._tmdb_provider() if self._tmdb_provider is not None else None
        if tmdb is None or state.show_id is None:
            self._overview_label.setText("")
            self._overview_label.hide()
            self._overview_toggle.hide()
            return

        cached = self._overview_cache.get(token)
        if cached is not None:
            self._overview_cache.move_to_end(token)
            self._apply_overview_text(cached, token)
            return

        if token in self._loading_tokens:
            return
        self._loading_tokens.add(token)
        media_type = self._media_type
        show_id = state.show_id

        def _worker() -> None:
            try:
                details = (
                    tmdb.get_movie_details(show_id)
                    if media_type == "movie"
                    else tmdb.get_tv_details(show_id)
                ) or {}
                text = details.get("overview", "") or ""
            except Exception:
                text = ""
            try:
                self._bridge.overview_ready.emit(text, token)
            except RuntimeError:
                pass

        _submit_bg(_worker)

    def _on_overview_ready(self, text: str, token: str) -> None:
        self._loading_tokens.discard(token)
        self._overview_cache[token] = text
        self._overview_cache.move_to_end(token)
        while len(self._overview_cache) > _MAX_OVERVIEW_CACHE_ENTRIES:
            self._overview_cache.popitem(last=False)
        if token != self._current_token:
            return
        self._apply_overview_text(text, token)

    def _apply_overview_text(self, text: str, token: str) -> None:
        del token
        self._overview_label.setText(text)
        self._overview_label.setVisible(bool(text))
        self._overview_toggle.setVisible(bool(text))

    # -- Shared helpers --------------------------------------------------

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
