# plex_renamer/gui_qt/widgets/_work_panel.py
"""MediaWorkPanel — header / season strip / toolbar / episode table / footer
assembly for the GUI V4 work panel (Plan 3, spec §3.2-§3.3).

Replaces the old three-panel roster/preview/detail split for the "middle"
work surface. The expansion card (Task 3) is wired to the table's persistent
editor in Task 5; this task only assembles the surrounding chrome.
"""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QModelIndex, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from .. import _scale
from ._bulk_assign_panel import BulkAssignPanel
from ._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
from ._episode_table_model import EpisodeTableModel
from ._formatting import clamped_percent
from ._media_helpers import (
    state_status,
    state_status_tone,
)
from ._workspace_widget_primitives import MasterCheckBox
from .segmented_control import SegmentedControl
from .status_chip import season_strip_specs

_MAX_OVERVIEW_CACHE_ENTRIES = 64
_OVERVIEW_CLAMP_PAD_U = 6


class _OverviewBridge(QObject):
    overview_ready = Signal(str, str)   # text, token


def _overview_token(state: ScanState, media_type: str) -> str:
    return f"{state.show_id}:{media_type}"


class MediaWorkPanel(QFrame):
    filter_changed = Signal(str)          # "all"|"problems"
    search_changed = Signal(str)
    approve_all_clicked = Signal()
    unassign_all_clicked = Signal()
    season_chip_clicked = Signal(int)     # season number (0 = specials)
    overview_toggled = Signal(bool)
    bulk_assign_requested = Signal()      # overflow menu action (and Task 5 hint forward)
    inline_row_action = Signal(QModelIndex, str)  # inline row action (e.g. missing-file "assign_file")

    def __init__(
        self,
        *,
        media_type: str,
        settings_service=None,
        tmdb_provider=None,
        guide_provider=None,
        cached_guide_provider=None,
        guide_builder=None,
        guide_store=None,
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
        self._overview_token_applied: str | None = None
        self._series_overview_text = ""
        self._episode_overview_active = False
        self._bridge = _OverviewBridge()
        self._bridge.overview_ready.connect(self._on_overview_ready)
        self.setProperty("cssClass", "panel")
        self.setProperty("panelVariant", "square")
        self._build_ui(
            cached_guide_provider=cached_guide_provider,
            guide_builder=guide_builder,
            guide_store=guide_store,
        )

    # -- Consumed-by-action-bar aliases ------------------------------------

    @property
    def fix_match_button(self) -> QPushButton:
        return self._fix_match_button

    @property
    def primary_action_button(self) -> QPushButton:
        return self._primary_action_button

    @property
    def automux_button(self) -> QPushButton:
        return self._automux_button

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
    def summary_label(self) -> QLabel:
        return self._summary_label

    @property
    def bulk_panel(self) -> BulkAssignPanel:
        return self._bulk_panel

    @property
    def overflow_button(self) -> QToolButton:
        return self._overflow_button

    def bulk_assign_active(self) -> bool:
        return self._table_stack.currentWidget() is self._bulk_panel

    def enter_bulk_assign(self) -> None:
        self._table_stack.setCurrentWidget(self._bulk_panel)
        self._segmented_filter.setEnabled(False)
        self._search_box.setEnabled(False)
        self._approve_all_button.hide()
        self._primary_action_button.hide()
        self._strip_scroll.hide()

    def exit_bulk_assign(self) -> None:
        self._table_stack.setCurrentWidget(self._table_view)
        self._segmented_filter.setEnabled(True)
        self._search_box.setEnabled(True)
        if self._state is not None:
            self.update_toolbar(self._state)
            self._strip_key = None
            self._refresh_strip(self._state)

    # -- UI scaffold ---------------------------------------------------------

    def _build_ui(self, *, cached_guide_provider=None, guide_builder=None, guide_store=None) -> None:
        outer = QVBoxLayout(self)
        margin = _scale.px(12)
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(_scale.px(8))

        self._build_header(outer)
        # Movie-mode inline AutoMux tracks section (spec §8.2). Managed by
        # MediaWorkspaceAutoMuxCoordinator.on_state_shown via
        # set_automux_tracks(); stays empty in TV mode.
        self._automux_tracks_host = QVBoxLayout()
        outer.addLayout(self._automux_tracks_host)
        self._build_strip(outer)
        self._build_toolbar(outer)
        self._build_table(
            outer,
            cached_guide_provider=cached_guide_provider,
            guide_builder=guide_builder,
            guide_store=guide_store,
        )
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

        self._fix_match_button = QPushButton("Fix Match")
        self._fix_match_button.setProperty("cssClass", "secondary")
        self._fix_match_button.setEnabled(False)
        title_row.addWidget(self._fix_match_button)

        self._automux_button = QPushButton("Disable AutoMux")
        self._automux_button.setProperty("cssClass", "danger")
        self._automux_button.hide()
        title_row.addWidget(self._automux_button)

        self._primary_action_button = QPushButton("")
        self._primary_action_button.setProperty("cssClass", "primary")
        self._primary_action_button.setEnabled(False)
        title_row.addWidget(self._primary_action_button)

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
        toggle_policy = self._overview_toggle.sizePolicy()
        toggle_policy.setRetainSizeWhenHidden(True)   # R2 M8: no width shift between series
        self._overview_toggle.setSizePolicy(toggle_policy)
        # Task 7: pin the width so it doesn't jump when the label flips
        # between "more" and "less" (their sizeHints differ once real font
        # metrics are in play -- setRetainSizeWhenHidden only pins width
        # while hidden, not across a text change while visible).
        toggle_fm = self._overview_toggle.fontMetrics()
        widest = max(toggle_fm.horizontalAdvance("more"), toggle_fm.horizontalAdvance("less"))
        self._overview_toggle.setFixedWidth(widest + _scale.px(20))
        overview_row.addWidget(self._overview_toggle, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addLayout(overview_row)
        self._apply_overview_clamp()

        self._discovery_label = QLabel("")
        self._discovery_label.setProperty("cssClass", "caption")
        self._discovery_label.hide()
        outer.addWidget(self._discovery_label)

    def _build_strip(self, outer: QVBoxLayout) -> None:
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setProperty("cssClass", "season-strip-scroll")
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(_scale.px(36))

        strip_host = QWidget()
        strip_host.setProperty("cssClass", "season-strip-scroll")
        self._strip_layout = QHBoxLayout(strip_host)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(_scale.px(4))
        self._strip_layout.addStretch()
        self._strip_scroll.setWidget(strip_host)
        self._strip_buttons: list[QPushButton] = []
        self._strip_key: tuple | None = None
        outer.addWidget(self._strip_scroll)

    def _build_toolbar(self, outer: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()

        self._segmented_filter = SegmentedControl(["All", "Problems"])
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
        toolbar.addWidget(self._master_check)

        self._check_summary = QLabel("")
        self._check_summary.setProperty("cssClass", "caption")
        self._check_summary.hide()
        toolbar.addWidget(self._check_summary)

        toolbar.addStretch()

        self._approve_all_button = QPushButton("Approve All")
        self._approve_all_button.setProperty("cssClass", "primary")
        self._approve_all_button.setProperty("sizeVariant", "compact")
        self._approve_all_button.hide()
        self._approve_all_button.clicked.connect(self.approve_all_clicked.emit)
        toolbar.addWidget(self._approve_all_button)

        self._overflow_button = QToolButton()
        self._overflow_button.setText("⋯")
        self._overflow_button.setProperty("cssClass", "toolbar-overflow")
        self._overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        overflow_menu = QMenu(self._overflow_button)
        overflow_menu.addAction("Bulk Assign…", self.bulk_assign_requested.emit)
        self._unassign_all_action = overflow_menu.addAction("Unassign All", self.unassign_all_clicked.emit)
        self._overflow_button.setMenu(overflow_menu)
        if self._media_type == "movie":
            self._overflow_button.hide()
        toolbar.addWidget(self._overflow_button)

        outer.addLayout(toolbar)

    def _build_table(
        self,
        outer: QVBoxLayout,
        *,
        cached_guide_provider=None,
        guide_builder=None,
        guide_store=None,
    ) -> None:
        self._model = EpisodeTableModel(
            media_type=self._media_type,
            settings_service=self._settings,
            guide_provider=self._guide_provider,
            cached_guide_provider=cached_guide_provider,
            guide_builder=guide_builder,
            guide_store=guide_store,
        )
        self._model.guide_loaded.connect(self._on_guide_loaded)
        self._table_view = EpisodeTableView()
        self._table_view.setModel(self._model)
        self._delegate = EpisodeTableDelegate(self._table_view, media_type=self._media_type)
        self._table_view.setItemDelegate(self._delegate)
        self._table_view.header_clicked.connect(self._on_header_clicked)
        self._table_view.bulk_hint_clicked.connect(self.bulk_assign_requested.emit)
        self._table_view.inline_action_clicked.connect(self.inline_row_action.emit)
        self._bulk_panel = BulkAssignPanel()
        stack_host = QWidget()
        self._table_stack = QStackedLayout(stack_host)
        self._table_stack.addWidget(self._table_view)
        self._table_stack.addWidget(self._bulk_panel)
        outer.addWidget(stack_host, stretch=1)

    def _build_footer(self, outer: QVBoxLayout) -> None:
        footer = QHBoxLayout()
        self._summary_label = QLabel("")
        self._summary_label.setProperty("cssClass", "caption")
        footer.addWidget(self._summary_label)
        footer.addStretch()
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
        # Re-populating the table always collapses any expanded episode row
        # (EpisodeTableModel.show_state() unconditionally resets
        # _expanded_row), so the header must return to series mode too --
        # otherwise the flag desyncs from the actual expansion state.
        self._episode_overview_active = False
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
        self._episode_overview_active = False
        self._series_overview_text = ""
        self._overview_label.setText(message)
        self._overview_toggle.hide()
        self._discovery_label.hide()
        self._clear_strip()
        self._model.show_state(None, collapsed_sections=set())
        self._summary_label.setText("")
        self._approve_all_button.hide()
        self._master_check.hide()
        self._check_summary.hide()

    def update_master_state(self, state: ScanState | None) -> None:
        """The middle-panel select-all is removed (GUI-V4 R2, V6). Selection is
        driven by the roster (left panel); keep the controls permanently
        hidden regardless of media type or state."""
        del state
        self._master_check.setEnabled(False)
        self._master_check.hide()
        self._check_summary.hide()

    def set_automux_tracks(self, widget: QWidget | None) -> None:
        """Show the movie AutoMux tracks section, or clear it with None."""
        while self._automux_tracks_host.count():
            item = self._automux_tracks_host.takeAt(0)
            old = item.widget()
            if old is not None:
                # Keep the C++ parent while the DeferredDelete is pending
                # (see AutoMuxTracksWidget._clear_rows).
                old.hide()
                old.deleteLater()
        if widget is not None:
            self._automux_tracks_host.addWidget(widget)

    def refresh_header(self, state: ScanState | None) -> None:
        if state is None:
            self.clear()
            return
        self._title_label.setText(state.display_name)
        source = (state.active_episode_source or "tmdb").upper()
        self._source_pill.setText(source)
        status_text, _color = state_status(state, media_type=self._media_type)
        tone = state_status_tone(state, media_type=self._media_type)
        tone = "warning" if tone == "accent" else tone
        if status_text == "Matched":
            # R2 M12: matched shows are a green pill carrying the series
            # match confidence.
            tone = "success"
            self._status_pill.setText(f"MATCHED · {clamped_percent(state.confidence)}%")
        else:
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

    def _on_guide_loaded(self) -> None:
        """Async guide arrived: summary + toolbar + strip depend on
        model.guide() -- the strip's Unmapped chip count in particular is
        keyed off guide.unmapped_primary_files, which is unavailable on the
        first (skeleton) paint. The _strip_key cache means this is a no-op
        when the chips haven't actually changed."""
        self.update_footer()
        self.update_toolbar(self._state)
        if self._state is not None and not self.bulk_assign_active():
            self._refresh_strip(self._state)

    def update_toolbar(self, state: ScanState | None) -> None:
        bulk_active = self.bulk_assign_active()
        self._primary_action_button.setVisible(not bulk_active)
        if self._media_type != "movie":
            self._overflow_button.setVisible(not bulk_active)
        is_movie = self._media_type == "movie"
        self._segmented_filter.setVisible(not is_movie)
        self._search_box.setVisible(not is_movie)
        if is_movie or state is None or bulk_active:
            self._approve_all_button.hide()
            return
        guide = self._model.guide()
        has_review = guide is not None and any(row.status == "Review" for row in guide.rows)
        self._approve_all_button.setVisible(has_review)
        self._sync_unassign_all_action(state)

    def scroll_to_folder_section(self) -> None:
        key = self._model.folder_section_key()
        header_row = self._model.section_header_row(key)
        if header_row < 0:
            return
        index = self._model.index(header_row, 0)
        self._table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
        self._delegate.flash_row(header_row)

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

    def scroll_to_unmapped_section(self) -> None:
        row = self._model.unmapped_section_row()
        if row < 0:
            return
        index = self._model.index(row, 0)
        self._table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
        self._delegate.flash_row(row)

    # -- Toolbar signal handlers -------------------------------------------

    def _on_filter_text_changed(self, text: str) -> None:
        mode = text.casefold()
        self._model.set_filter_mode(mode)
        self.filter_changed.emit(mode)

    def _on_header_clicked(self, section_key: str) -> None:
        self._model.toggle_section(section_key)

    # -- Toolbar rule helpers ------------------------------------------------

    def _sync_unassign_all_action(self, state: ScanState) -> None:
        table = state.assignments
        has_assignments = table is not None and any(
            preview.file_id is not None
            and table.assignment_for(preview.file_id) is not None
            for preview in state.preview_items
        )
        self._unassign_all_action.setVisible(has_assignments)
        self._unassign_all_action.setEnabled(
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
        self._strip_key = None
        for button in self._strip_buttons:
            button.setParent(None)
            button.deleteLater()
        self._strip_buttons = []

    def _refresh_strip(self, state: ScanState) -> None:
        if self._media_type == "movie":
            self._clear_strip()
            self._strip_scroll.hide()
            return
        specs = season_strip_specs(state.completeness)
        guide = self._model.guide()
        unmapped_count = len(guide.unmapped_primary_files) if guide is not None else 0
        key = (unmapped_count,) + tuple(
            (season_num, chip.text, chip.tone, chip.tooltip) for season_num, chip in specs
        )
        if key == self._strip_key:
            return                                   # same chips: no widget churn
        self._clear_strip()
        self._strip_key = key
        if not specs and not unmapped_count:
            self._strip_scroll.hide()
            return
        self._strip_scroll.show()
        # Insert before the trailing stretch (index len-1).
        insert_at = self._strip_layout.count() - 1
        series_button = QPushButton("Series")
        series_button.setProperty("cssClass", "season-strip-chip")
        series_button.setProperty("tone", "info")
        series_button.setToolTip("Jump to the folder rename at the top of the list")
        series_button.setFlat(True)
        series_button.clicked.connect(self.scroll_to_folder_section)
        self._strip_layout.insertWidget(insert_at, series_button)
        insert_at += 1
        self._strip_buttons.append(series_button)
        if unmapped_count:
            unmapped_button = QPushButton(f"Unmapped ({unmapped_count})")
            unmapped_button.setProperty("cssClass", "season-strip-chip")
            unmapped_button.setProperty("tone", "warning")
            unmapped_button.setToolTip("Jump to the unmapped primary files")
            unmapped_button.setFlat(True)
            unmapped_button.clicked.connect(self.scroll_to_unmapped_section)
            self._strip_layout.insertWidget(insert_at, unmapped_button)
            insert_at += 1
            self._strip_buttons.append(unmapped_button)
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
        fm = self._overview_label.fontMetrics()
        two_lines = 2 * fm.lineSpacing() + _scale.px(_OVERVIEW_CLAMP_PAD_U)
        if self._overview_expanded:
            self._overview_label.setMaximumHeight(16777215)
        else:
            self._overview_label.setMaximumHeight(two_lines)
        self._overview_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def _overview_overflows(self) -> bool:
        text = self._overview_label.text()
        if not text:
            return False
        fm = self._overview_label.fontMetrics()
        width = self._overview_label.width() or self._overview_label.sizeHint().width()
        if width <= 0:
            return False
        bounding = fm.boundingRect(
            0, 0, width, 0,
            int(Qt.TextFlag.TextWordWrap), text,
        )
        collapsed_max = 2 * fm.lineSpacing() + _scale.px(_OVERVIEW_CLAMP_PAD_U)
        return bounding.height() > collapsed_max

    def _refresh_overview_toggle(self) -> None:
        """Recompute the more/less toggle's visibility for the current
        overview text against the panel's *current* layout width.

        Called both by ``_apply_overview_text`` (the single choke point that
        sets text+clamp+toggle) and by ``showEvent``/``resizeEvent`` so the
        gate re-runs once real layout width is available -- a TMDB-cache HIT
        can call ``_apply_overview_text`` synchronously during
        ``show_state()``, before the panel has ever been shown/laid out,
        when ``self._overview_label.width()`` is still 0.
        """
        text = self._overview_label.text()
        self._overview_toggle.setVisible(bool(text) and self._overview_overflows())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_overview_toggle()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_overview_toggle()

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
            # Same single display path as the async/cached branches: remember
            # the (empty) series overview and drop any episode override so
            # collapse cannot restore stale text.
            self._episode_overview_active = False
            self._apply_overview_text("", token)
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

    def _set_overview_label(self, text: str) -> None:
        """Low-level display mechanics only -- no bookkeeping of *what* text
        means (series vs. episode). Single choke point used by
        ``set_episode_overview``, ``clear_episode_overview``, and the
        not-active branch of ``_apply_overview_text``."""
        self._overview_label.setText(text)
        self._overview_label.setVisible(bool(text))
        self._apply_overview_clamp()
        self._refresh_overview_toggle()

    def _apply_overview_text(self, text: str, token: str) -> None:
        """Series-overview entry point (cache hit / async TMDB response).

        Always remembers the text as the series overview -- even while an
        episode is expanded -- so a later ``clear_episode_overview`` restores
        the freshest series text rather than stale text captured before the
        async response landed. Only the *display* is gated on the episode
        flag: while an episode is expanded, the visible label must keep
        showing the episode text.

        A change in ``token`` means the panel switched to a different
        series/movie -- any overview expansion from the previous series must
        not leak into the new one, so the toggle is reset to collapsed.
        Same-token re-applies (an async response landing for the series
        already on screen) leave the user's expand/collapse choice alone."""
        if token != self._overview_token_applied:
            self._overview_token_applied = token
            self._overview_expanded = False
            self._overview_toggle.setText("more")
        self._series_overview_text = text
        if not self._episode_overview_active:
            self._set_overview_label(text)

    def set_episode_overview(self, overview: str, air_date: str) -> None:
        """Swap the header overview to the expanded episode's text,
        remembering the series overview so ``clear_episode_overview`` can
        restore it (M10 — header follows the expanded episode)."""
        if not self._episode_overview_active:
            self._series_overview_text = self._overview_label.text()
        self._episode_overview_active = True
        text = overview or "No episode overview."
        if air_date:
            text = f"{text}\nAir date: {air_date}"
        self._set_overview_label(text)

    def clear_episode_overview(self) -> None:
        """Restore the remembered series overview (collapse, or nothing
        expanded)."""
        if not self._episode_overview_active:
            return
        self._episode_overview_active = False
        self._set_overview_label(self._series_overview_text)

    # -- Shared helpers --------------------------------------------------

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
