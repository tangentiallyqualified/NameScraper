"""
Main application window — layout, state management, and orchestration.

Delegates rendering to preview_canvas, detail_panel, and result_views.
Delegates dialogs to the dialogs module.
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from ..app.models import ScanLifecycle, ScanProgress
from ..app.services import (
    CommandGatingService,
    PersistentCacheService,
    RefreshPolicyService,
    ScanSnapshotService,
    TVLibraryDiscoveryService,
)
from ..constants import JobStatus, MediaType
from ..engine import (
    BatchTVOrchestrator,
    CompletenessReport,
    MovieScanner,
    PreviewItem,
    RenameResult,
    ScanState,
    SeasonCompleteness,
    TVScanner,
    CANCEL_SCAN,
    AUTO_ACCEPT_THRESHOLD,
    get_checked_indices_from_state,
    score_results,
    check_duplicates,
    execute_rename,
    build_rename_job_from_state,
    build_rename_job_from_items,
)
from ..job_store import JobStore, RenameJob, DuplicateJobError
from ..job_executor import QueueExecutor, revert_job
from ..keys import get_api_key, save_api_key
from ..parsing import (
    build_movie_name, build_show_folder_name, clean_folder_name,
    extract_year, is_already_complete,
)
from ..styles import COLORS, get_dpi_scale, setup_styles
from ..tmdb import TMDBClient

from . import detail_panel, dialogs, library_panel, preview_canvas, result_views
from .helpers import (
    bind_mousewheel,
    init_platform,
    setup_detail_mousewheel,
    show_progress,
)


TMDB_CACHE_NAMESPACE = "tmdb"
TMDB_CACHE_SNAPSHOT_KEY = "client_snapshot"
SNAPSHOT_TV_SINGLE = "tv_single"
SNAPSHOT_TV_BATCH = "tv_batch"
SNAPSHOT_MOVIE_BATCH = "movie_batch"


class PlexRenamerApp:
    """
    Main application window.

    State:
        folder          – selected root folder
        media_type      – "tv" or "movie"
        media_info      – TMDB show/movie dict for the selected media
        preview_items   – list of PreviewItem from the engine
        tv_scanner      – active TVScanner (or None)
        movie_scanner   – active MovieScanner (or None)
        tmdb            – shared TMDBClient instance
    """

    def __init__(self):
        init_platform()

        self.root = tk.Tk()
        self.root.title("Plex Renamer")

        # Window sizing
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = int(screen_w * 0.92)
        win_h = int(screen_h * 0.85)
        x = (screen_w - win_w) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+10")
        self.root.minsize(760, 500)

        self.dpi_scale = get_dpi_scale(self.root)
        self.c = COLORS

        # ── State ─────────────────────────────────────────────────────
        self.folder: Path | None = None
        self.media_type: str = MediaType.TV
        self.media_info: dict | None = None
        self.tmdb: TMDBClient | None = None
        self.movie_scanner: MovieScanner | None = None
        self._active_content_mode: str = MediaType.TV
        self._tv_root_folder: Path | None = None
        self._movie_folder_state: Path | None = None
        self._movie_media_info_state: dict | None = None
        self._movie_label_text: str = "No media selected"
        self._movie_preview_items_state: list[PreviewItem] = []
        self._movie_check_vars_state: dict[str, tk.BooleanVar] = {}
        self._movie_selected_index_state: int | None = None
        self._movie_scanner_state: MovieScanner | None = None

        # ScanState-backed attributes — TV flows delegate through
        # active_scan transparently. preview_canvas, detail_panel,
        # and result_views read/write via these properties without
        # needing to know whether the current session is TV or movie.
        # Movie flows keep their working state in these fallback fields.
        self._preview_items: list[PreviewItem] = []
        self._tv_scanner: TVScanner | None = None
        self._check_vars: dict[str, tk.BooleanVar] = {}
        self.__selected_index: int | None = None
        self.__card_positions: list[tuple[int, int, int]] = []
        self.__season_header_positions: list[tuple[int, int, int]] = []
        self.__display_order: list[int] = []
        self.__completeness: CompletenessReport | None = None
        self.__collapsed_seasons: set[int] = set()

        # GUI-only state (not part of ScanState)
        self._poster_ref = None
        self._detail_img_ref = None
        self._resize_after_id = None
        self._last_canvas_width: int = 0
        self._last_library_width: int = 0
        self._completeness_after_id = None
        self._result_collapsed_seasons: set[int] = set()
        self._last_rename_result: RenameResult | None = None
        self._last_renamed_items: list[PreviewItem] | None = None
        self._preview_state_signature = None
        self._preview_thumb_signature = None
        self._preview_thumb_images: dict[int, object] = {}
        self._preview_thumb_refs: list[object] = []
        self._suspend_check_change_callbacks = 0
        self._library_thumb_cache: dict[tuple, object] = {}
        self._library_thumb_signature = None
        self._library_placeholder = None
        self._content_owner: str | None = None
        self._active_library_mode: str | None = None
        self._movie_library_states: list[ScanState] = []
        self._tv_batch_mode_state: bool = False

        # ── Batch TV state ─────────────────────────────────────────
        self.batch_mode: bool = False
        self.batch_states: list[ScanState] = []
        self.active_scan: ScanState | None = None
        self.batch_orchestrator: BatchTVOrchestrator | None = None
        self._library_selected_index: int | None = None
        self._library_card_positions: list[tuple[int, int, int]] = []
        self._library_alt_positions: list[tuple[int, int, int, int]] = []

        # ── Job queue ─────────────────────────────────────────────
        self.job_store: JobStore = JobStore()
        self.queue_executor: QueueExecutor = QueueExecutor(self.job_store)
        self.command_gating = CommandGatingService()
        self.cache_service = PersistentCacheService()
        self.refresh_policy = RefreshPolicyService()
        self.snapshot_service = ScanSnapshotService()
        self.tv_library_discovery = TVLibraryDiscoveryService()
        self.scan_progress = ScanProgress()
        self._persist_after_id = None
        self._pending_persist_kinds: set[str] = set()

        # Register an app-level listener for badge updates.
        # NOTE: The queue_panel's _start_executor() calls
        # clear_listeners() then re-registers both this listener
        # and its own, so this initial registration covers the case
        # where the executor is started before the queue tab is
        # ever opened (future auto-start feature).
        def _exec_badge_update(*_args):
            self.root.after(0, self._update_queue_badge)
            self.root.after(0, self._refresh_queue_tab)

        self.queue_executor.add_listener(
            on_started=lambda j: _exec_badge_update(),
            on_completed=lambda j, r: _exec_badge_update(),
            on_failed=lambda j, e: _exec_badge_update(),
            on_finished=lambda: _exec_badge_update(),
        )

        # ── Theme + layout ────────────────────────────────────────────
        self._check_imgs = setup_styles(self.root, self.dpi_scale)
        self._build_layout()

        # ── Cached font objects ───────────────────────────────────────
        self._font_orig = tkfont.Font(family="Helvetica", size=11)
        self._font_new = tkfont.Font(family="Helvetica", size=10)
        self._font_badge = tkfont.Font(family="Helvetica", size=8, weight="bold")
        self._font_check = tkfont.Font(family="Helvetica", size=14)

        # Initialize tab badges from database (persisted queue/history)
        self._update_queue_badge()
        self._restore_last_session_snapshot()

    # ══════════════════════════════════════════════════════════════════
    #  ScanState-backed properties
    # ══════════════════════════════════════════════════════════════════
    # These delegate to active_scan for TV sessions and otherwise fall
    # back to the instance-level movie state. All external code reads
    # and writes through these without knowing about the session model.

    def _get_scan_state_attr(self, scan_attr: str, fallback_attr: str):
        """Read state from the active ScanState or the app fallback storage."""
        scan = self.active_scan if self._active_content_mode == MediaType.TV else None
        if scan is not None:
            return getattr(scan, scan_attr)
        return getattr(self, fallback_attr)

    def _set_scan_state_attr(self, scan_attr: str, fallback_attr: str, value) -> None:
        """Write state to the active ScanState or the app fallback storage."""
        scan = self.active_scan if self._active_content_mode == MediaType.TV else None
        if scan is not None:
            setattr(scan, scan_attr, value)
        else:
            setattr(self, fallback_attr, value)

    @property
    def preview_items(self):
        return self._get_scan_state_attr("preview_items", "_preview_items")

    @preview_items.setter
    def preview_items(self, value):
        self._set_scan_state_attr("preview_items", "_preview_items", value)

    @property
    def library_states(self) -> list[ScanState]:
        if self._active_library_mode == MediaType.MOVIE:
            return self._movie_library_states
        return self.batch_states

    @property
    def tv_scanner(self):
        return self._get_scan_state_attr("scanner", "_tv_scanner")

    @tv_scanner.setter
    def tv_scanner(self, value):
        self._set_scan_state_attr("scanner", "_tv_scanner", value)

    @property
    def check_vars(self):
        return self._get_scan_state_attr("check_vars", "_check_vars")

    @check_vars.setter
    def check_vars(self, value):
        self._set_scan_state_attr("check_vars", "_check_vars", value)

    @property
    def _selected_index(self):
        return self._get_scan_state_attr("selected_index", "_PlexRenamerApp__selected_index")

    @_selected_index.setter
    def _selected_index(self, value):
        self._set_scan_state_attr("selected_index", "_PlexRenamerApp__selected_index", value)

    @property
    def _card_positions(self):
        return self._get_scan_state_attr("card_positions", "_PlexRenamerApp__card_positions")

    @_card_positions.setter
    def _card_positions(self, value):
        self._set_scan_state_attr("card_positions", "_PlexRenamerApp__card_positions", value)

    @property
    def _season_header_positions(self):
        return self._get_scan_state_attr(
            "season_header_positions", "_PlexRenamerApp__season_header_positions")

    @_season_header_positions.setter
    def _season_header_positions(self, value):
        self._set_scan_state_attr(
            "season_header_positions", "_PlexRenamerApp__season_header_positions", value)

    @property
    def _display_order(self):
        return self._get_scan_state_attr("display_order", "_PlexRenamerApp__display_order")

    @_display_order.setter
    def _display_order(self, value):
        self._set_scan_state_attr("display_order", "_PlexRenamerApp__display_order", value)

    @property
    def _completeness(self):
        return self._get_scan_state_attr("completeness", "_PlexRenamerApp__completeness")

    @_completeness.setter
    def _completeness(self, value):
        self._set_scan_state_attr("completeness", "_PlexRenamerApp__completeness", value)

    @property
    def _collapsed_seasons(self):
        return self._get_scan_state_attr("collapsed_seasons", "_PlexRenamerApp__collapsed_seasons")

    @_collapsed_seasons.setter
    def _collapsed_seasons(self, value):
        self._set_scan_state_attr("collapsed_seasons", "_PlexRenamerApp__collapsed_seasons", value)

    # ══════════════════════════════════════════════════════════════════
    #  Layout
    # ══════════════════════════════════════════════════════════════════

    def _build_layout(self):
        c = self.c

        # ── Header ────────────────────────────────────────────────────
        header = ttk.Frame(self.root, style="Mid.TFrame")
        header.pack(fill="x")

        header_inner = ttk.Frame(header, style="Mid.TFrame")
        header_inner.pack(fill="x", padx=20, pady=(14, 10))

        title_area = ttk.Frame(header_inner, style="Mid.TFrame")
        title_area.pack(side="left")

        ttk.Label(
            title_area, text="PLEX RENAMER", style="Title.TLabel",
            background=c["bg_mid"],
        ).pack(anchor="w")

        self.media_label_var = tk.StringVar(value="No media selected")
        ttk.Label(
            title_area, textvariable=self.media_label_var,
            style="Subtitle.TLabel", background=c["bg_mid"],
        ).pack(anchor="w", pady=(2, 0))

        btn_area = ttk.Frame(header_inner, style="Mid.TFrame")
        btn_area.pack(side="right")
        # (API Keys moved to Settings tab; Undo Last removed — use Queue revert)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

        # ── Main view notebook (TV / Movies / Queue / Settings) ─────
        self._main_notebook = ttk.Notebook(self.root)
        self._main_notebook.pack(fill="both", expand=True)

        # — TV Series tab —
        self._tv_tab = ttk.Frame(self._main_notebook)
        self._main_notebook.add(self._tv_tab, text="  TV Series  ")

        # — Movies tab —
        self._movie_tab = ttk.Frame(self._main_notebook)
        self._main_notebook.add(self._movie_tab, text="  Movies  ")

        # — Queue tab —
        self._queue_frame = ttk.Frame(self._main_notebook)
        self._main_notebook.add(self._queue_frame, text="  Queue  ")

        # — History tab —
        self._history_frame = ttk.Frame(self._main_notebook)
        self._main_notebook.add(self._history_frame, text="  History  ")

        # — Settings tab —
        self._settings_frame = ttk.Frame(self._main_notebook)
        self._main_notebook.add(self._settings_frame, text="  Settings  ")

        # Track active tab for type routing
        # Tab indices: 0=TV, 1=Movies, 2=Queue, 3=History, 4=Settings
        self._queue_visible = False
        def _on_main_tab_change(event):
            tab_id = self._main_notebook.select()
            idx = self._main_notebook.index(tab_id)
            if idx == 0:  # TV Series
                self._restore_tv_tab_content()
                self._queue_visible = False
            elif idx == 1:  # Movies
                self._restore_movie_tab_content()
                self._queue_visible = False
            elif idx == 2:  # Queue
                self._queue_visible = True
                self._ensure_queue_tab()
                self._refresh_queue_tab()
            elif idx == 3:  # History
                self._ensure_history_tab()
                self._refresh_history_tab()
                self._queue_visible = False
            elif idx == 4:  # Settings
                self._ensure_settings_tab()
                self._queue_visible = False
        self._main_notebook.bind("<<NotebookTabChanged>>", _on_main_tab_change)

        # ── Settings state ────────────────────────────────────────────
        self.settings_hide_named = tk.BooleanVar(value=False)
        self.settings_hide_named.trace_add("write", lambda *_: self._on_settings_changed())

        # ── TV Series action bar ──────────────────────────────────────
        # (This replaces the old unified action bar in the Media tab)
        self._media_tab = self._tv_tab  # Alias for backward compat
        action_bar = ttk.Frame(self._tv_tab)
        action_bar.pack(fill="x", padx=20, pady=(10, 6))
        action_bar.columnconfigure(2, weight=1)

        self.select_btn_frame = ttk.Frame(action_bar)
        self.select_btn_frame.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.btn_select_folder = ttk.Button(
            self.select_btn_frame, text="Select Show Folder",
            command=self.pick_folder,
        )
        self.btn_select_folder.pack(side="left")

        # (Movie folder/file buttons are created in the Movie tab below)

        search_frame = ttk.Frame(action_bar)
        search_frame.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(search_frame, text="Filter:", foreground=c["text_dim"]).pack(
            side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: preview_canvas.update_search(self))

        sel_frame = ttk.Frame(action_bar)
        sel_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        self.tally_var = tk.StringVar(value="0 / 0")
        ttk.Label(
            sel_frame, textvariable=self.tally_var,
            foreground=c["accent"], font=("Helvetica", 11, "bold"),
        ).pack(side="left", padx=(0, 4))
        ttk.Label(
            sel_frame, text="selected", foreground=c["text_dim"],
            font=("Helvetica", 10),
        ).pack(side="left", padx=(0, 10))

        # Smart selection dropdown (replaces broken "Select All" button)
        self._sel_menu_btn = ttk.Menubutton(
            sel_frame, text="Select ▾", style="Small.TButton")
        self._sel_menu = tk.Menu(
            self._sel_menu_btn, tearoff=0,
            bg=c["bg_card"], fg=c["text"],
            activebackground=c["accent"], activeforeground=c["bg_dark"],
            font=("Helvetica", 10))
        self._sel_menu.add_command(
            label="All", command=lambda: preview_canvas.select_all(self))
        self._sel_menu.add_command(
            label="All Matched (OK)",
            command=lambda: preview_canvas.select_by_status(self, {"OK"}))
        self._sel_menu.add_command(
            label="Matched + Uncertain",
            command=lambda: preview_canvas.select_by_status(self, {"OK", "UNMATCHED"}))
        self._sel_menu.add_separator()
        self._sel_menu.add_command(
            label="None", command=lambda: preview_canvas.select_none(self))
        self._sel_menu_btn.configure(menu=self._sel_menu)
        self._sel_menu_btn.pack(side="left")

        # Batch-mode buttons (initially hidden)
        self.btn_scan_all = ttk.Button(
            sel_frame, text="Scan All Shows",
            command=self._scan_all_shows,
            style="Small.TButton",
        )

        btn_frame = ttk.Frame(sel_frame)
        btn_frame.pack(side="right")

        ttk.Button(
            btn_frame, text="Refresh", command=self.run_preview,
        ).pack(side="left", padx=(0, 8))
        self.btn_rename = ttk.Button(
            btn_frame, text="Add to Queue", command=self._add_to_queue,
            style="Accent.TButton",
        )
        self.btn_rename.pack(side="left")

        self._tv_content_host = ttk.Frame(self._tv_tab)
        self._tv_content_host.pack(fill="both", expand=True, padx=20)

        # ── TV content — three-panel grid ─────────────────────────────
        self._content_frame = ttk.Frame(self._main_notebook)
        # col 0: library panel (batch TV only), col 1: preview, col 2: detail
        self._content_frame.columnconfigure(0, weight=0, minsize=0)
        self._content_frame.columnconfigure(1, weight=3, minsize=350)
        self._content_frame.columnconfigure(2, weight=1, minsize=280)
        self._content_frame.rowconfigure(0, weight=1)

        # ── Col 0: Library panel (hidden initially) ──────────────────
        self._library_frame = ttk.Frame(self._content_frame)
        # NOT gridded yet — shown only in batch mode

        lib_inner = ttk.Frame(self._library_frame)
        lib_inner.pack(fill="both", expand=True)

        self.library_canvas = tk.Canvas(
            lib_inner, bg=c["bg_dark"], highlightthickness=0, bd=0,
        )
        lib_scrollbar = ttk.Scrollbar(
            lib_inner, orient="vertical",
            command=self.library_canvas.yview,
        )
        self.library_canvas.configure(yscrollcommand=lib_scrollbar.set)
        lib_scrollbar.pack(side="right", fill="y")
        self.library_canvas.pack(side="left", fill="both", expand=True)

        def _on_library_resize(event):
            if abs(event.width - self._last_library_width) < 10:
                return
            self._last_library_width = event.width
            if self.library_states:
                self.root.after(100, lambda: library_panel.display_library(self))
        self.library_canvas.bind("<Configure>", _on_library_resize)

        # Library totals bar
        lib_totals = ttk.Frame(self._library_frame, style="Mid.TFrame")
        lib_totals.pack(fill="x", side="bottom")
        self.library_totals_var = tk.StringVar(value="")
        ttk.Label(
            lib_totals, textvariable=self.library_totals_var,
            style="Status.TLabel",
        ).pack(fill="x")

        # ── Col 1: Preview panel ─────────────────────────────────────
        list_container = ttk.Frame(self._content_frame)
        list_container.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

        self.preview_canvas = tk.Canvas(
            list_container, bg=c["bg_dark"], highlightthickness=0, bd=0,
        )
        scrollbar = ttk.Scrollbar(
            list_container, orient="vertical",
            command=self.preview_canvas.yview,
        )
        self.preview_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.preview_canvas.pack(side="left", fill="both", expand=True)

        self._canvas_in_preview_mode = False
        def _on_canvas_resize(event):
            if abs(event.width - self._last_canvas_width) < 10:
                return
            self._last_canvas_width = event.width
            if self._resize_after_id:
                self.root.after_cancel(self._resize_after_id)
            if self._canvas_in_preview_mode and self._card_positions:
                self._resize_after_id = self.root.after(
                    100, lambda: preview_canvas.display_preview(self))
        self.preview_canvas.bind("<Configure>", _on_canvas_resize)

        bind_mousewheel(self, self.preview_canvas)

        # ── Col 2: Detail panel ──────────────────────────────────────
        detail_frame = ttk.Frame(self._content_frame, style="Mid.TFrame")
        detail_frame.grid(row=0, column=2, sticky="nsew")

        detail_cv = tk.Canvas(
            detail_frame, bg=c["bg_mid"], highlightthickness=0, bd=0,
        )
        detail_sb = ttk.Scrollbar(
            detail_frame, orient="vertical", command=detail_cv.yview,
        )
        self.detail_inner = ttk.Frame(detail_cv, style="Mid.TFrame")
        self.detail_inner.bind(
            "<Configure>",
            lambda e: detail_cv.configure(scrollregion=detail_cv.bbox("all")),
        )
        detail_cv.create_window((0, 0), window=self.detail_inner, anchor="nw")
        detail_cv.configure(yscrollcommand=detail_sb.set)
        detail_sb.pack(side="right", fill="y")
        detail_cv.pack(side="left", fill="both", expand=True)

        self._detail_canvas = detail_cv

        def _sync_detail_width(event):
            items = detail_cv.find_all()
            if items:
                detail_cv.itemconfig(items[0], width=event.width)
        detail_cv.bind("<Configure>", _sync_detail_width)

        setup_detail_mousewheel(self, detail_cv, self.preview_canvas)

        # Detail panel widgets
        self._detail_pad = ttk.Frame(self.detail_inner, style="Mid.TFrame")
        self._detail_pad.pack(fill="both", expand=True, padx=14, pady=14)
        pad = self._detail_pad

        self.poster_row = ttk.Frame(pad, style="Mid.TFrame")
        self.poster_row.pack(fill="x", pady=(0, 6))
        self.poster_label = ttk.Label(
            self.poster_row, style="Detail.TLabel", background=c["bg_mid"])
        self.poster_label.pack(side="left", anchor="nw", padx=(0, 10))

        self.show_info_frame = ttk.Frame(self.poster_row, style="Mid.TFrame")
        self.show_info_frame.pack(side="left", fill="both", expand=True, anchor="nw")
        self.show_info_label = ttk.Label(
            self.show_info_frame, text="", style="DetailDim.TLabel",
            wraplength=140, justify="left")
        self.show_info_label.pack(anchor="nw", fill="x")

        self.completeness_summary_label = ttk.Label(
            self.show_info_frame, text="", style="DetailDim.TLabel",
            justify="left", wraplength=140)
        self.completeness_summary_label.pack(anchor="nw", fill="x", pady=(4, 0))

        self.completeness_detail_frame = ttk.Frame(
            self.show_info_frame, style="Mid.TFrame")
        self.completeness_detail_frame.pack(anchor="nw", fill="x", pady=(2, 0))
        self._season_detail_widgets: dict[int, dict] = {}
        self._expanded_seasons: set[int] = set()

        self._separator_after_poster = ttk.Separator(pad, orient="horizontal")
        self._separator_after_poster.pack(fill="x", pady=6)

        self.detail_header = ttk.Label(
            pad, text="SELECT AN ITEM",
            style="DetailDim.TLabel", font=("Helvetica", 9, "bold"))
        self.detail_header.pack(anchor="w", fill="x", pady=(6, 4))

        self.detail_image = ttk.Label(
            pad, style="Detail.TLabel", background=c["bg_mid"])
        self.detail_image.pack(anchor="center", fill="x", pady=(0, 8))

        self.detail_ep_title = ttk.Label(
            pad, text="", style="DetailEpTitle.TLabel",
            wraplength=260, justify="left")
        self.detail_ep_title.pack(anchor="w", fill="x", pady=(0, 2))

        self.detail_meta_frame = ttk.Frame(pad, style="Mid.TFrame")
        self.detail_meta_frame.pack(fill="x", pady=(0, 8))
        self.detail_meta_label = ttk.Label(
            self.detail_meta_frame, text="", style="DetailDim.TLabel")
        self.detail_meta_label.pack(anchor="w")

        self.detail_rename_frame = ttk.Frame(pad, style="DetailCard.TFrame")
        self.detail_rename_frame.pack(fill="x", pady=(0, 8))
        rename_inner = ttk.Frame(self.detail_rename_frame, style="DetailCard.TFrame")
        rename_inner.pack(fill="x", padx=10, pady=8)
        ttk.Label(rename_inner, text="RENAME", style="DetailMeta.TLabel",
                  font=("Helvetica", 8, "bold")).pack(anchor="w", pady=(0, 4))
        self.detail_orig_label = ttk.Label(
            rename_inner, text="", style="DetailMeta.TLabel",
            wraplength=240, justify="left")
        self.detail_orig_label.pack(anchor="w", fill="x")
        self.detail_new_label = ttk.Label(
            rename_inner, text="", style="DetailMeta.TLabel",
            wraplength=240, justify="left", foreground=c["success"])
        self.detail_new_label.pack(anchor="w", fill="x", pady=(2, 0))
        self.detail_status_label = ttk.Label(
            rename_inner, text="", style="DetailMeta.TLabel")
        self.detail_status_label.pack(anchor="w", fill="x", pady=(4, 0))

        # Re-match button (movies only) — placed right after rename card
        # so it's always visible without scrolling
        self.rematch_btn = ttk.Button(
            pad, text="Re-match on TMDB", command=self._rematch_selected_movie)

        ttk.Separator(pad, orient="horizontal").pack(fill="x", pady=6)

        self.detail_overview = ttk.Label(
            pad, text="", style="DetailOverview.TLabel",
            wraplength=260, justify="left")
        self.detail_overview.pack(anchor="w", fill="x", pady=(0, 8))

        self.detail_crew_frame = ttk.Frame(pad, style="Mid.TFrame")
        self.detail_crew_frame.pack(fill="x", pady=(0, 8))
        self.detail_crew_label = ttk.Label(
            self.detail_crew_frame, text="", style="DetailDim.TLabel",
            wraplength=260, justify="left")
        self.detail_crew_label.pack(anchor="w", fill="x")

        detail_panel.reset_detail(self)

        def _on_detail_resize(event):
            available = event.width - 32
            if available > 100:
                self.detail_overview.configure(wraplength=available)
                self.detail_ep_title.configure(wraplength=available)
                info_wrap = max(80, int(available * 0.5))
                self.show_info_label.configure(wraplength=info_wrap)
                self.detail_orig_label.configure(wraplength=available - 20)
                self.detail_new_label.configure(wraplength=available - 20)
                self.detail_crew_label.configure(wraplength=available)
                self.completeness_summary_label.configure(wraplength=info_wrap)
        pad.bind("<Configure>", _on_detail_resize)

        # ── Movies tab action bar ─────────────────────────────────────
        movie_action_bar = ttk.Frame(self._movie_tab)
        movie_action_bar.pack(fill="x", padx=20, pady=(10, 6))

        movie_btn_frame = ttk.Frame(movie_action_bar)
        movie_btn_frame.pack(side="right")

        self.btn_select_movie_folder = ttk.Button(
            movie_action_bar, text="Select Folder",
            command=self.pick_folder,
        )
        self.btn_select_movie_folder.pack(side="left")

        self.btn_movie_rename = ttk.Button(
            movie_btn_frame, text="Add to Queue", command=self._add_to_queue,
            style="Accent.TButton",
        )
        self.btn_movie_rename.pack(side="left")

        movie_info_label = ttk.Label(
            movie_action_bar, text="Select a folder to scan for movies",
            foreground=c["text_dim"])
        movie_info_label.pack(side="left", fill="x", expand=True, padx=16)

        self._movie_content_host = ttk.Frame(self._movie_tab)
        self._movie_content_host.pack(fill="both", expand=True, padx=20)

        self._mount_media_content(self._tv_content_host)

        # ── Status bar ────────────────────────────────────────────────
        self._status_bar = ttk.Frame(self.root, style="Mid.TFrame")
        self._status_bar.pack(fill="x", side="bottom")

        self.status_var = tk.StringVar(value="Ready — select a folder to begin")
        ttk.Label(
            self._status_bar, textvariable=self.status_var, style="Status.TLabel",
        ).pack(side="left", fill="x", expand=True)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self._status_bar, variable=self.progress_var, maximum=100,
            style="Accent.Horizontal.TProgressbar", length=200,
        )

    # ══════════════════════════════════════════════════════════════════
    #  Panel visibility
    # ══════════════════════════════════════════════════════════════════

    def _show_library_panel(self, *, show_scan_all: bool = False):
        """Show the library roster panel and adjust grid weights."""
        self._content_frame.columnconfigure(0, weight=1, minsize=220)
        self._content_frame.columnconfigure(1, weight=3, minsize=350)
        self._library_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._last_library_width = 0

        # Set up mousewheel routing for library canvas
        self.library_canvas.bind(
            "<Enter>", lambda e: setattr(self, '_scroll_target', self.library_canvas))
        self.library_canvas.bind(
            "<Leave>", lambda e: setattr(self, '_scroll_target', self.preview_canvas))

        if show_scan_all:
            self.btn_scan_all.pack(side="left", padx=(8, 0))
            self.btn_rename.configure(text="Add All to Queue")
        else:
            self.btn_scan_all.pack_forget()
            self.btn_rename.configure(text="Add to Queue")

    def _hide_library_panel(self):
        """Hide the library panel."""
        self._library_frame.grid_forget()
        self._content_frame.columnconfigure(0, weight=0, minsize=0)
        self._content_frame.columnconfigure(1, weight=3, minsize=350)
        self.btn_scan_all.pack_forget()
        self.btn_rename.configure(text="Add to Queue")

    def _reset_library_roster(self) -> None:
        """Clear the shared library roster state before loading new media."""
        self.active_scan = None
        self._library_selected_index = None
        self._library_card_positions = []
        self._library_alt_positions = []
        self._active_library_mode = None
        self._movie_library_states = []

    def _build_movie_library_info(self, item: PreviewItem | None = None) -> dict:
        """Build roster metadata for a movie entry or the overall movie batch."""
        info = {
            "id": 0,
            "title": self._movie_label_text or "Movies",
            "_media_type": MediaType.MOVIE,
        }
        if item is not None:
            info["title"] = item.new_name or item.original.stem
            if self.movie_scanner:
                movie_data = self.movie_scanner.movie_info.get(item.original)
                if movie_data:
                    info.update(movie_data)
            info.setdefault("folder_name", item.original.parent.name)
            return info

        if self.movie_scanner and self._movie_preview_items_state:
            for movie_item in self._movie_preview_items_state:
                movie_data = self.movie_scanner.movie_info.get(movie_item.original)
                if movie_data and movie_data.get("poster_path"):
                    info.update(movie_data)
                    return info
        if self._movie_folder_state:
            info.setdefault("folder_name", self._movie_folder_state.name)
        elif self.folder:
            info.setdefault("folder_name", self.folder.name)
        return info

    @staticmethod
    def _movie_item_is_actionable(item: PreviewItem) -> bool:
        return item.is_actionable

    def _movie_item_default_checked(self, item: PreviewItem) -> bool:
        if not self._movie_item_is_actionable(item):
            return False
        return not (
            item.new_name == item.original.name
            and (item.target_dir is None or item.target_dir == item.original.parent)
        )

    def _collect_movie_batch_state(self) -> tuple[list[PreviewItem], dict[str, tk.BooleanVar]]:
        """Flatten per-movie roster state back into the movie batch session state."""
        items: list[PreviewItem] = []
        check_vars: dict[str, tk.BooleanVar] = {}
        for idx, state in enumerate(self._movie_library_states):
            if not state.preview_items:
                continue
            items.append(state.preview_items[0])
            var = state.check_vars.get("0")
            if var is not None:
                check_vars[str(idx)] = var
        return items, check_vars

    def _sync_movie_library_state(
        self,
        *,
        scanned: bool | None = None,
        scanning: bool | None = None,
    ) -> None:
        """Mirror the movie batch session into per-movie roster entries."""
        if self._active_library_mode != MediaType.MOVIE:
            return

        root_folder = self._movie_folder_state or self.folder
        previous_states = {
            state.preview_items[0].original: state
            for state in self._movie_library_states
            if state.preview_items
        }

        valid_keys = {str(i) for i in range(len(self._movie_preview_items_state))}
        self._movie_check_vars_state = {
            key: var for key, var in self._movie_check_vars_state.items()
            if key in valid_keys
        }

        movie_states: list[ScanState] = []
        for idx, item in enumerate(self._movie_preview_items_state):
            key = str(idx)
            var = self._movie_check_vars_state.get(key)
            if var is None:
                var = tk.BooleanVar(value=self._movie_item_default_checked(item))
                var.trace_add("write", lambda *_: preview_canvas._on_check_changed(self))
                self._movie_check_vars_state[key] = var

            previous_state = previous_states.get(item.original)
            state = ScanState(
                folder=root_folder or item.original.parent,
                media_info=self._build_movie_library_info(item),
            )
            state.preview_items = [item]
            state.check_vars = {"0": var}
            state.selected_index = 0 if self._library_selected_index == idx else None
            state.confidence = 0.0 if "REVIEW" in item.status else 1.0
            state.scanned = scanned if scanned is not None else bool(self._movie_preview_items_state)
            state.scanning = scanning if scanning is not None else False
            state.checked = bool(var.get()) if self._movie_item_is_actionable(item) else False
            state.search_results = (
                self.movie_scanner.get_search_results(item.original)
                if self.movie_scanner else []
            )
            if item.status.startswith("CONFLICT:"):
                state.duplicate_of = item.status.removeprefix("CONFLICT:").strip()
                state.checked = False
            else:
                state.duplicate_of = None
            if previous_state is not None:
                state.queued = previous_state.queued
            if self.command_gating.is_plex_ready_state(state):
                state.checked = False
            movie_states.append(state)

        if not movie_states and scanning:
            placeholder = ScanState(
                folder=root_folder or Path("."),
                media_info=self._build_movie_library_info(),
            )
            placeholder.scanned = False
            placeholder.scanning = True
            placeholder.checked = False
            movie_states.append(placeholder)

        self._movie_library_states = movie_states
        if self._library_selected_index is not None and self._library_selected_index >= len(movie_states):
            self._library_selected_index = 0 if movie_states else None

    def _show_movie_library_state(self, state: ScanState) -> None:
        """Render the current movie roster entry in the shared preview/detail pane."""
        self.media_type = MediaType.MOVIE
        self._active_content_mode = MediaType.MOVIE
        self.folder = self._movie_folder_state or state.folder
        self.media_info = state.media_info
        self.media_label_var.set(self._movie_label_text)
        self.poster_label.configure(image="", text="")
        self._poster_ref = None
        self.show_info_label.configure(text="")
        self.poster_row.pack_forget()
        preview_canvas.clear_completeness(self)

        if state.scanning:
            cv, _, _ = self._clear_canvas()
            c = COLORS
            s = self.dpi_scale
            cv.create_text(
                int(20 * s), int(44 * s), text=f"Scanning {state.display_name}...",
                fill=c["text_muted"], font=("Helvetica", 13), anchor="nw")
            cv.create_text(
                int(20 * s), int(78 * s),
                text="Movie matches will appear when the scan completes",
                fill=c["text_muted"], font=("Helvetica", 10), anchor="nw")
            cv.configure(scrollregion=(0, 0, 600, 120))
            detail_panel.reset_detail(self)
            return

        self._preview_items = list(state.preview_items)
        self._check_vars = dict(state.check_vars)
        self.__selected_index = state.selected_index
        state.selected_index = 0 if state.preview_items else None
        self._movie_selected_index_state = state.selected_index

        if not self.preview_items:
            self._clear_canvas()
            detail_panel.reset_detail(self)
            return

        preview_canvas.display_preview(self)
        if self._selected_index is not None and self._selected_index < len(self.preview_items):
            preview_canvas.select_card(self, self._selected_index)
            return

        for idx, item in enumerate(self.preview_items):
            if item.status == "OK" or "UNMATCHED" in item.status:
                preview_canvas.select_card(self, idx)
                return
        detail_panel.reset_detail(self)

    def _mount_media_content(self, target_host):
        """Place the shared preview/detail content under the active media tab."""
        if getattr(self, "_content_mount_host", None) is target_host:
            return
        self._content_frame.pack_forget()
        self._content_frame.pack(in_=target_host, fill="both", expand=True)
        self._content_mount_host = target_host

    def _unmount_media_content(self):
        """Hide the shared preview/detail content when the active tab does not own it."""
        self._content_frame.pack_forget()
        self._content_mount_host = None

    def _save_movie_session_state(self):
        """Persist the current movie-mode fallback state before TV mode mutates it."""
        if self._active_content_mode == MediaType.MOVIE:
            self._movie_folder_state = self._movie_folder_state or self.folder
            if not self._movie_label_text:
                self._movie_label_text = self.media_label_var.get()
        if self._movie_library_states:
            self._movie_preview_items_state, self._movie_check_vars_state = self._collect_movie_batch_state()
            if (self._library_selected_index is not None
                    and self._library_selected_index < len(self._movie_library_states)):
                self._movie_selected_index_state = self._movie_library_states[
                    self._library_selected_index].selected_index
            else:
                self._movie_selected_index_state = None
        else:
            self._movie_preview_items_state = list(self._preview_items)
            self._movie_check_vars_state = dict(self._check_vars)
            self._movie_selected_index_state = self.__selected_index
        self._movie_scanner_state = self.movie_scanner

    def _restore_tv_tab_content(self):
        """Rebind the shared pane to the stored TV session."""
        self.media_type = MediaType.TV
        self._active_content_mode = MediaType.TV
        self._active_library_mode = MediaType.TV
        self.batch_mode = self._tv_batch_mode_state
        if not self.batch_states:
            self.active_scan = None
        self._sync_queued_library_states()
        self._mount_media_content(self._tv_content_host)

        if self.batch_mode:
            self._show_library_panel(show_scan_all=True)
            self.root.update_idletasks()
            library_panel.load_library_thumbnails(self)
            library_panel.display_library(self)
            if (self._library_selected_index is not None
                    and self._library_selected_index < len(self.library_states)):
                index = self._library_selected_index
                self.root.after_idle(lambda: library_panel.select_show(self, index))
            else:
                self._clear_canvas()
                detail_panel.reset_detail(self)
                if self._tv_root_folder:
                    self.folder = self._tv_root_folder
                    self.media_label_var.set(f"TV Library — {self._tv_root_folder.name}")
            return

        if self.library_states:
            self._show_library_panel(show_scan_all=False)
            self.root.update_idletasks()
            library_panel.load_library_thumbnails(self)
            library_panel.display_library(self)
            index = self._library_selected_index or 0
            if index < len(self.library_states):
                library_panel.select_show(self, index)
                return
        else:
            self._hide_library_panel()

        if not self.active_scan:
            self._clear_canvas()
            detail_panel.reset_detail(self)
            if self._tv_root_folder:
                self.folder = self._tv_root_folder
            return

        self.folder = self.active_scan.folder
        self.media_info = self.active_scan.media_info
        self.media_label_var.set(self.active_scan.display_name)

        def _render_restored_tv_content() -> None:
            if self._active_content_mode != MediaType.TV or self.active_scan is None:
                return

            tmdb = self.tmdb
            if tmdb and self.active_scan.show_id:
                detail_panel.display_poster(self, tmdb, self.active_scan.show_id, "tv")
                detail_panel.populate_show_info(self, tmdb, self.active_scan.show_id)
            else:
                detail_panel.reset_detail(self)

            preview_canvas.display_preview(self)
            if self._completeness:
                preview_canvas.display_completeness(self)
            if self._selected_index is not None and self._selected_index < len(self.preview_items):
                preview_canvas.select_card(self, self._selected_index)

        self.root.after_idle(_render_restored_tv_content)

    def _restore_movie_tab_content(self):
        """Rebind the shared pane to the stored movie session."""
        self.media_type = MediaType.MOVIE
        self._active_content_mode = MediaType.MOVIE
        self._active_library_mode = MediaType.MOVIE
        self.batch_mode = False
        self._mount_media_content(self._movie_content_host)
        if self._resize_after_id:
            self.root.after_cancel(self._resize_after_id)
            self._resize_after_id = None
        self._last_canvas_width = 0
        self.root.update_idletasks()

        self._preview_items = list(self._movie_preview_items_state)
        self._check_vars = dict(self._movie_check_vars_state)
        self.__selected_index = self._movie_selected_index_state
        self.movie_scanner = self._movie_scanner_state
        self.folder = self._movie_folder_state
        self.media_info = self._movie_media_info_state
        self.media_label_var.set(self._movie_label_text)
        self.poster_label.configure(image="", text="")
        self._poster_ref = None
        self.show_info_label.configure(text="")
        self.poster_row.pack_forget()
        preview_canvas.clear_completeness(self)

        self._sync_movie_library_state()
        self._sync_queued_library_states()

        if self.library_states:
            self._show_library_panel(show_scan_all=False)
            self.root.update_idletasks()
            library_panel.load_library_thumbnails(self)
            library_panel.display_library(self)
        else:
            self._hide_library_panel()

        if self.library_states:
            index = self._library_selected_index or 0
            if index < len(self.library_states):
                self.root.after_idle(lambda: library_panel.select_show(self, index))
                return

        if not self.preview_items:
            self._clear_canvas()
            detail_panel.reset_detail(self)
            return

        def _render_movie_preview():
            if self._active_content_mode != MediaType.MOVIE:
                return
            preview_canvas.display_preview(self)
            if self._selected_index is not None and self._selected_index < len(self.preview_items):
                preview_canvas.select_card(self, self._selected_index)
            else:
                detail_panel.reset_detail(self)

        self.root.after_idle(_render_movie_preview)

    # ══════════════════════════════════════════════════════════════════
    #  Phase 1 state services
    # ══════════════════════════════════════════════════════════════════

    def _set_scan_progress(
        self,
        lifecycle: ScanLifecycle,
        *,
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str | None = None,
        message: str | None = None,
        overlay_text: str | None = None,
    ) -> None:
        """Update the structured scan progress model and mirror it to tkinter state."""
        if message is None:
            if total:
                message = f"{phase} {done}/{total}"
                if current_item:
                    message += f" — {current_item}"
            else:
                message = phase or lifecycle.value.replace("_", " ").title()

        self.scan_progress = ScanProgress(
            lifecycle=lifecycle,
            phase=phase,
            done=done,
            total=total,
            current_item=current_item,
            message=message,
        )
        self.status_var.set(message)
        self.progress_var.set(self.scan_progress.percent)
        if overlay_text is not None:
            self._update_scan_overlay(overlay_text)

    def _reset_scan_progress(self, message: str = "Ready — select a folder to begin") -> None:
        """Reset the scan progress model to idle."""
        self.scan_progress = ScanProgress(
            lifecycle=ScanLifecycle.IDLE,
            message=message,
        )
        self.status_var.set(message)
        self.progress_var.set(0)

    def _persist_tmdb_cache_snapshot(self) -> None:
        """Persist the current TMDB in-memory cache snapshot to local storage."""
        if not self.tmdb:
            return
        snapshot = self.tmdb.export_cache_snapshot()
        self.cache_service.put(
            TMDB_CACHE_NAMESPACE,
            TMDB_CACHE_SNAPSHOT_KEY,
            snapshot,
            expires_at=self.refresh_policy.build_expiry(
                refreshed_at=None,
                media_type=MediaType.TV,
            ),
            metadata={"kind": "tmdb_cache_snapshot"},
        )

    def _active_snapshot_id_for_current_session(self) -> str | None:
        """Return the snapshot id representing the session active at shutdown."""
        if self._active_content_mode == MediaType.MOVIE and self._movie_library_states:
            return SNAPSHOT_MOVIE_BATCH
        if self.batch_mode and self.batch_states:
            return SNAPSHOT_TV_BATCH
        if self.active_scan is not None:
            return SNAPSHOT_TV_SINGLE
        return None

    def _cancel_pending_persistence(self) -> None:
        """Cancel any scheduled persistence flush."""
        if self._persist_after_id is not None:
            self.root.after_cancel(self._persist_after_id)
            self._persist_after_id = None

    def _request_persistence(self, *kinds: str) -> None:
        """Debounce persistence writes so repeated UI events do not thrash disk."""
        self._pending_persist_kinds.update(kinds)
        self._cancel_pending_persistence()
        self._persist_after_id = self.root.after(250, self._flush_pending_persistence)

    def _flush_pending_persistence(self, *, force_kinds: set[str] | None = None) -> None:
        """Flush queued persistence work immediately."""
        kinds = set(force_kinds or self._pending_persist_kinds)
        self._pending_persist_kinds.clear()
        self._persist_after_id = None
        if not kinds:
            return
        if "tv" in kinds:
            self._persist_tv_snapshot()
        if "movie" in kinds:
            self._persist_movie_snapshot()
        if "cache" in kinds:
            self._persist_tmdb_cache_snapshot()

    def _hydrate_movie_scanner_from_states(self, scanner: MovieScanner, states: list[ScanState]) -> None:
        """Restore cached movie metadata and search results into a fresh MovieScanner."""
        for state in states:
            if not state.preview_items:
                continue
            item = state.preview_items[0]
            scanner.set_movie_info(item.original, state.media_info)
            scanner.set_search_results(item.original, state.search_results)

    def _persist_snapshot(self, snapshot_id: str, media_type: str, library_root: Path, states: list[ScanState]) -> None:
        """Persist a serializable scan snapshot or delete it when empty."""
        if not states:
            self.snapshot_service.delete_snapshot(snapshot_id)
            return
        self.snapshot_service.save_snapshot(
            snapshot_id,
            media_type=media_type,
            library_root=library_root,
            states=states,
        )

    def _persist_tv_snapshot(self) -> None:
        """Persist the current TV session state."""
        if self.batch_mode and self.batch_states:
            root = self._tv_root_folder or self.folder or self.batch_states[0].folder
            self._persist_snapshot(SNAPSHOT_TV_BATCH, MediaType.TV, root, self.batch_states)
            self.snapshot_service.delete_snapshot(SNAPSHOT_TV_SINGLE)
            return

        if self.active_scan is not None:
            root = self.active_scan.folder.parent
            self._persist_snapshot(SNAPSHOT_TV_SINGLE, MediaType.TV, root, [self.active_scan])
            self.snapshot_service.delete_snapshot(SNAPSHOT_TV_BATCH)
            return

        self.snapshot_service.delete_snapshot(SNAPSHOT_TV_SINGLE)
        self.snapshot_service.delete_snapshot(SNAPSHOT_TV_BATCH)

    def _persist_movie_snapshot(self) -> None:
        """Persist the current movie session state."""
        if self._active_content_mode == MediaType.MOVIE:
            self._save_movie_session_state()
            self._sync_movie_library_state()

        states = list(self._movie_library_states)
        root = self._movie_folder_state or self.folder
        if root is None or not states:
            self.snapshot_service.delete_snapshot(SNAPSHOT_MOVIE_BATCH)
            return
        self._persist_snapshot(SNAPSHOT_MOVIE_BATCH, MediaType.MOVIE, root, states)

    def _restore_last_session_snapshot(self) -> None:
        """Restore the most recent persisted scan snapshot into the current UI shell."""
        snapshot_id = self.snapshot_service.get_active_snapshot_id()
        if snapshot_id is None:
            snapshots = self.snapshot_service.list_snapshots()
            if not snapshots:
                return
            snapshot_id = snapshots[0].snapshot_id

        latest = self.snapshot_service.load_snapshot(snapshot_id)
        if latest is None:
            snapshots = self.snapshot_service.list_snapshots()
            if not snapshots:
                return
            latest = snapshots[0]
            snapshot_id = latest.snapshot_id

        restored = self.snapshot_service.restore_states(snapshot_id)
        if restored is None:
            return

        _media_type, library_root, states = restored
        if latest.snapshot_id == SNAPSHOT_TV_BATCH and states:
            tmdb = self._ensure_tmdb(warn=False)
            self.folder = library_root
            self._tv_root_folder = library_root
            self._tv_batch_mode_state = True
            self.batch_mode = True
            self.batch_states = states
            self.batch_orchestrator = None
            if tmdb is not None:
                self.batch_orchestrator = BatchTVOrchestrator(
                    tmdb,
                    library_root,
                    discovery_service=self.tv_library_discovery,
                )
                self.batch_orchestrator.states = self.batch_states
            self.active_scan = None
            self._library_selected_index = 0
            self.media_label_var.set(f"TV Library — {library_root.name}")
            self.status_var.set(f"Restored TV library session — {len(states)} shows")
            self._main_notebook.select(self._tv_tab)
            self.root.after_idle(self._restore_tv_tab_content)
            return

        if latest.snapshot_id == SNAPSHOT_TV_SINGLE and states:
            tmdb = self._ensure_tmdb(warn=False)
            self._tv_batch_mode_state = False
            self.batch_mode = False
            self.active_scan = states[0]
            if tmdb is not None and self.active_scan.show_id and self.active_scan.scanner is None:
                self.active_scan.scanner = TVScanner(
                    tmdb,
                    self.active_scan.media_info,
                    self.active_scan.folder,
                )
            self.batch_states = [self.active_scan]
            self.folder = self.active_scan.folder
            self._tv_root_folder = self.active_scan.folder
            self.media_info = self.active_scan.media_info
            self._library_selected_index = 0
            self.media_label_var.set(self.active_scan.display_name)
            self.status_var.set(f"Restored show session — {self.active_scan.display_name}")
            self._main_notebook.select(self._tv_tab)
            self.root.after_idle(self._restore_tv_tab_content)
            return

        if latest.snapshot_id == SNAPSHOT_MOVIE_BATCH and states:
            tmdb = self._ensure_tmdb(warn=False)
            self._movie_folder_state = library_root
            self.folder = library_root
            self._movie_label_text = f"Movies — {library_root.name}"
            self._movie_preview_items_state = [
                state.preview_items[0]
                for state in states
                if state.preview_items
            ]
            self._movie_check_vars_state = {}
            self._movie_selected_index_state = 0 if self._movie_preview_items_state else None
            self._movie_library_states = states
            self.media_info = {"_type": "movie_batch", "_media_type": MediaType.MOVIE}
            self._movie_media_info_state = self.media_info
            self._movie_scanner_state = MovieScanner(tmdb, library_root) if tmdb is not None else None
            if self._movie_scanner_state is not None:
                self._hydrate_movie_scanner_from_states(self._movie_scanner_state, states)
            self._library_selected_index = 0 if self._movie_preview_items_state else None
            self.status_var.set(f"Restored movie session — {len(self._movie_preview_items_state)} items")
            self._main_notebook.select(self._movie_tab)
            self.root.after_idle(self._restore_movie_tab_content)

    def _ensure_batch_orchestrator(self) -> BatchTVOrchestrator | None:
        """Return the batch orchestrator for the current TV library session."""
        if self.batch_orchestrator is not None:
            return self.batch_orchestrator
        tmdb = self._ensure_tmdb()
        if not tmdb:
            return None
        root = self._tv_root_folder or self.folder
        if root is None:
            return None
        self.batch_orchestrator = BatchTVOrchestrator(
            tmdb,
            root,
            discovery_service=self.tv_library_discovery,
        )
        self.batch_orchestrator.states = self.batch_states
        return self.batch_orchestrator

    def _run_batch_scan(self, *, show_nothing_to_scan: bool) -> None:
        """Run the shared batch TV scan flow used by auto-scan and manual rescan."""
        orchestrator = self._ensure_batch_orchestrator()
        if orchestrator is None:
            return

        unscanned = [
            s for s in self.batch_states
            if not s.scanned and not s.queued and s.show_id is not None
        ]
        if not unscanned:
            if show_nothing_to_scan:
                messagebox.showinfo("Nothing to scan", "All shows are already scanned.")
            return

        self._set_scan_buttons_enabled(False)
        show_progress(self.progress_bar, self.progress_var, True)
        error_holder: list[Exception | None] = [None]

        def _progress(done, total):
            current_name = ""
            if done <= len(self.batch_states):
                to_scan = [
                    s for s in self.batch_states
                    if not s.scanned and not s.queued and s.show_id is not None
                ]
                if done > 0 and done <= len(to_scan):
                    current_name = to_scan[done - 1].display_name
            self.root.after(0, lambda d=done, t=total, n=current_name: (
                self._set_scan_progress(
                    ScanLifecycle.SCANNING,
                    phase="Scanning episodes...",
                    done=d,
                    total=t,
                    current_item=n or None,
                    message=f"Scanning episodes... {d}/{t}" + (f" — {n}" if n else ""),
                ),
            ))

        def _scan_worker():
            try:
                orchestrator.scan_all(progress_callback=_progress)
            except Exception as e:
                error_holder[0] = e
            self.root.after(0, _on_scan_complete)

        def _on_scan_complete():
            self._set_scan_buttons_enabled(True)
            show_progress(self.progress_bar, self.progress_var, False)

            if error_holder[0]:
                messagebox.showerror(
                    "Scan Error",
                    f"Error during batch scan:\n{error_holder[0]}")

            for state in self.batch_states:
                if self.command_gating.is_plex_ready_state(state):
                    state.checked = False

            scanned = sum(1 for s in self.batch_states if s.scanned)
            total_files = sum(s.file_count for s in self.batch_states if s.scanned)
            self._set_scan_progress(
                ScanLifecycle.READY,
                phase="Batch scan complete",
                message=f"Scanned {scanned} shows — {total_files} total files",
            )
            self._request_persistence("tv", "cache")
            library_panel.display_library(self)

            if (self._library_selected_index is not None
                    and self._library_selected_index < len(self.batch_states)):
                library_panel.select_show(self, self._library_selected_index)

        threading.Thread(target=_scan_worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════
    #  TMDB Client
    # ══════════════════════════════════════════════════════════════════

    def _ensure_tmdb(self, *, warn: bool = True) -> TMDBClient | None:
        """Get or create the shared TMDB client."""
        if self.tmdb is not None:
            return self.tmdb
        api_key = get_api_key("TMDB")
        if not api_key:
            if warn:
                messagebox.showwarning(
                    "No Key", "Set your TMDB API key first via 'API Keys'.")
            return None
        self.tmdb = TMDBClient(api_key)
        cached_snapshot = self.cache_service.get(
            TMDB_CACHE_NAMESPACE,
            TMDB_CACHE_SNAPSHOT_KEY,
        )
        if cached_snapshot.is_hit and cached_snapshot.value:
            try:
                self.tmdb.import_cache_snapshot(
                    cached_snapshot.value,
                    clear_existing=True,
                )
            except Exception:
                self.cache_service.invalidate(
                    TMDB_CACHE_NAMESPACE,
                    TMDB_CACHE_SNAPSHOT_KEY,
                )
        return self.tmdb

    # ══════════════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════════════

    def _clear_canvas(self):
        """Reset the preview canvas to a blank state."""
        cv = self.preview_canvas
        cv.delete("all")
        self._canvas_in_preview_mode = False
        self._card_positions = []
        self._season_header_positions = []
        self._display_order = []
        self.check_vars.clear()
        self._selected_index = None
        return cv, max(600, cv.winfo_width()), self.dpi_scale

    def _show_scan_overlay(self, message: str = "Scanning...",
                           sub: str = "") -> None:
        """Show a prominent scanning indicator on the preview canvas."""
        c = self.c
        cv = self.preview_canvas
        cv.delete("all")
        self._canvas_in_preview_mode = False
        w = max(600, cv.winfo_width())
        h = max(400, cv.winfo_height())

        # Centered message
        cv.create_text(
            w // 2, h // 2 - 30, text=message,
            fill=c["accent"], font=("Helvetica", 16, "bold"),
            anchor="center")
        if sub:
            cv.create_text(
                w // 2, h // 2 + 10, text=sub,
                fill=c["text_dim"], font=("Helvetica", 11),
                anchor="center")

        # Animated dots (simple text that gets updated)
        self._scan_overlay_id = cv.create_text(
            w // 2, h // 2 + 40, text="",
            fill=c["text_muted"], font=("Helvetica", 10),
            anchor="center", tags=("scan_progress",))
        cv.configure(scrollregion=(0, 0, w, h))

    def _update_scan_overlay(self, text: str) -> None:
        """Update the scanning overlay progress text."""
        cv = self.preview_canvas
        for cid in cv.find_withtag("scan_progress"):
            cv.itemconfigure(cid, text=text)

    def _set_scan_buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_select_folder, self.btn_select_movie_folder):
            try:
                btn.configure(state=state)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════
    #  Event handlers
    # ══════════════════════════════════════════════════════════════════

    def _on_type_change(self, event=None):
        """Legacy handler — media type is now determined by tab selection."""
        pass

    # ══════════════════════════════════════════════════════════════════
    #  Folder & media selection
    # ══════════════════════════════════════════════════════════════════

    def pick_folder(self):
        folder = filedialog.askdirectory(title="Select Media Folder")
        if not folder:
            return
        self.folder = Path(folder)
        self.status_var.set(f"Selected: {self.folder}")

        tmdb = self._ensure_tmdb()
        if not tmdb:
            return

        if self.media_type == MediaType.TV:
            # Auto-detect: is this a TV library root or a single show?
            if BatchTVOrchestrator.is_tv_library(self.folder):
                self._start_batch_tv(tmdb)
            else:
                self.batch_mode = False
                self.batch_orchestrator = None
                folder_name = self.folder.name
                cleaned = clean_folder_name(folder_name)
                search_query = re.sub(r"\s*\(\d{4}\)\s*$", "", cleaned).strip()
                self._search_tv(tmdb, search_query, folder_name)
        else:
            self.media_type = MediaType.MOVIE
            self._setup_movie_scan(tmdb)

    def _search_tv(self, tmdb: TMDBClient, query: str, raw_name: str):
        results = tmdb.search_with_fallback(query, tmdb.search_tv)
        if not results:
            manual = simpledialog.askstring(
                "Show Not Found",
                f"No TMDB results for '{query}'.\n"
                f"(From: {raw_name})\n\nEnter the show name:",
                parent=self.root,
            )
            if manual and manual.strip():
                results = tmdb.search_tv(manual.strip())
            if not results:
                return

        year_hint = extract_year(raw_name)
        scored = score_results(results, raw_name, year_hint, title_key="name")
        best, best_score = scored[0]
        runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
        clear_winner = (best_score - runner_up_score) > 0.1

        if best_score >= AUTO_ACCEPT_THRESHOLD and clear_winner:
            chosen = best
        else:
            chosen = dialogs.pick_media_dialog(
                self, results, title_key="name", dialog_title="Select Show",
                search_callback=tmdb.search_tv,
            )
            if not chosen:
                return

        self._accept_tv_show(tmdb, chosen)

    def _accept_tv_show(self, tmdb: TMDBClient, chosen: dict):
        # Create a ScanState for single-show mode so the property
        # accessors route through it — same code path as batch mode.
        self._save_movie_session_state()
        self._tv_batch_mode_state = False
        self.batch_mode = False
        self.batch_orchestrator = None
        self._reset_library_roster()
        scanner = TVScanner(tmdb, chosen, self.folder)
        self._content_owner = MediaType.TV
        self._active_content_mode = MediaType.TV
        self._active_library_mode = MediaType.TV
        self._tv_root_folder = self.folder
        self._mount_media_content(self._tv_content_host)
        self.active_scan = ScanState(
            folder=self.folder,
            media_info=chosen,
            scanner=scanner,
            confidence=1.0,
            scanned=False,
        )
        self.batch_states = [self.active_scan]
        self._library_selected_index = 0
        self.media_info = chosen
        self._selected_index = None
        preview_canvas.clear_completeness(self)
        self._show_library_panel(show_scan_all=False)
        self.root.update_idletasks()
        library_panel.load_library_thumbnails(self)
        library_panel.display_library(self)
        self._last_canvas_width = self.preview_canvas.winfo_width()

        # Clear any previous detail content (e.g. from movie mode)
        detail_panel.reset_detail(self)

        detail_panel.display_poster(self, tmdb, chosen["id"], "tv")
        detail_panel.populate_show_info(self, tmdb, chosen["id"])
        year = chosen.get("year", "")
        self.media_label_var.set(
            f"{chosen['name']}" + (f" ({year})" if year else ""))
        self._set_scan_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning TV files...",
            message="Scanning TV files...",
        )
        self.root.update_idletasks()
        self.run_preview()
        library_panel.load_library_thumbnails(self)
        library_panel.display_library(self)

    # ══════════════════════════════════════════════════════════════════
    #  Batch TV mode
    # ══════════════════════════════════════════════════════════════════

    def _start_batch_tv(self, tmdb: TMDBClient):
        """Enter batch TV mode: discover shows, match on TMDB, show library panel."""
        self._save_movie_session_state()
        self._tv_batch_mode_state = True
        self.batch_mode = True
        self._content_owner = MediaType.TV
        self._active_content_mode = MediaType.TV
        self._tv_root_folder = self.folder
        self._mount_media_content(self._tv_content_host)
        self._reset_library_roster()
        self._active_library_mode = MediaType.TV
        self.batch_orchestrator = BatchTVOrchestrator(
            tmdb,
            self.folder,
            discovery_service=self.tv_library_discovery,
        )
        self.batch_states = []

        self.media_info = None
        self.tv_scanner = None
        self.preview_items = []
        self.check_vars = {}
        self._selected_index = None

        self._show_library_panel(show_scan_all=True)
        self.media_label_var.set(f"TV Library — {self.folder.name}")
        self._set_scan_progress(
            ScanLifecycle.DISCOVERING,
            phase="Discovering shows...",
            message="Discovering shows...",
        )
        self.root.update_idletasks()

        # Clear preview + detail panels and show scanning overlay
        self._clear_canvas()
        self._show_scan_overlay(
            "Scanning TV Library",
            f"Discovering shows in {self.folder.name}...")
        detail_panel.reset_detail(self)
        preview_canvas.clear_completeness(self)

        # Run Phase 1 discovery in a thread
        self._set_scan_buttons_enabled(False)
        show_progress(self.progress_bar, self.progress_var, True)

        error_holder: list[Exception | None] = [None]
        result_holder: list[list[ScanState] | None] = [None]

        def _progress(done, total):
            self.root.after(0, lambda: (
                self._set_scan_progress(
                    ScanLifecycle.MATCHING,
                    phase="Matching shows...",
                    done=done,
                    total=total,
                    message=f"Matching shows... {done}/{total}",
                    overlay_text=f"Matching shows on TMDB... {done}/{total}",
                ),
            ))

        def _discover_worker():
            try:
                result_holder[0] = self.batch_orchestrator.discover_shows(
                    progress_callback=_progress)
            except Exception as e:
                error_holder[0] = e
            self.root.after(0, _on_discover_complete)

        def _on_discover_complete():
            show_progress(self.progress_bar, self.progress_var, False)

            if error_holder[0]:
                self._set_scan_buttons_enabled(True)
                messagebox.showerror(
                    "Discovery Error",
                    f"Error during show discovery:\n{error_holder[0]}")
                self._set_scan_progress(
                    ScanLifecycle.FAILED,
                    phase="Discovery failed.",
                    message="Discovery failed.",
                )
                return

            self.batch_states = result_holder[0] or []
            if not self.batch_states:
                self._set_scan_buttons_enabled(True)
                self._set_scan_progress(
                    ScanLifecycle.WARNING,
                    phase="No TV shows found in this folder.",
                    message="No TV shows found in this folder.",
                )
                library_panel.display_library(self)
                return

            needs_review = sum(1 for s in self.batch_states if s.needs_review)
            self._set_scan_progress(
                ScanLifecycle.READY,
                phase="Discovery complete",
                message=(
                    f"Found {len(self.batch_states)} shows"
                    + (f" — {needs_review} need review" if needs_review else "")
                    + " — scanning episodes..."
                ),
            )
            self._request_persistence("tv", "cache")

            # Restore queued state from database (persists across restarts)
            self._restore_queued_states()

            # Load poster thumbnails and display library via select_show
            library_panel.load_library_thumbnails(self)

            # Auto-select the first show (triggers display_library internally)
            if self.batch_states:
                library_panel.select_show(self, 0)

            # Immediately scan all checked shows in background
            self._auto_scan_all_shows()

        threading.Thread(target=_discover_worker, daemon=True).start()

    def _auto_scan_all_shows(self):
        """Automatically scan all checked shows after discovery. Runs in background."""
        self._run_batch_scan(show_nothing_to_scan=False)

    def _exit_batch_mode(self):
        """Exit batch mode and return to single-show layout."""
        if not self.batch_mode:
            return
        self._tv_batch_mode_state = False
        self.batch_mode = False
        self._content_owner = None
        self._reset_library_roster()
        self.batch_states = []
        self.batch_orchestrator = None
        self._hide_library_panel()

        # Clear stale preview/detail content from the batch session
        self._clear_canvas()
        detail_panel.reset_detail(self)
        preview_canvas.clear_completeness(self)
        self.preview_items = []
        self.tv_scanner = None
        self.media_info = None
        self.media_label_var.set("No media selected")
        self._reset_scan_progress()
        self.snapshot_service.delete_snapshot(SNAPSHOT_TV_BATCH)

    def _scan_all_shows(self):
        """Rescan all shows (Phase 2) in batch mode."""
        if not self.batch_mode:
            return
        self._run_batch_scan(show_nothing_to_scan=True)

    def _setup_movie_scan(self, tmdb: TMDBClient):
        self.media_type = MediaType.MOVIE
        self._active_content_mode = MediaType.MOVIE
        self._content_owner = MediaType.MOVIE
        self.batch_mode = False
        self.batch_orchestrator = None
        self._reset_library_roster()
        self._active_library_mode = MediaType.MOVIE
        self._movie_folder_state = self.folder
        self._movie_preview_items_state = []
        self._movie_check_vars_state = {}
        self._movie_selected_index_state = None
        self._movie_library_states = []
        if self._main_notebook.index(self._main_notebook.select()) != 1:
            self._main_notebook.select(self._movie_tab)
        self._mount_media_content(self._movie_content_host)
        self.media_info = {"_type": "movie_batch", "_media_type": MediaType.MOVIE}
        self._movie_media_info_state = self.media_info
        self.movie_scanner = MovieScanner(tmdb, self.folder)
        self._movie_scanner_state = self.movie_scanner
        self.tv_scanner = None
        self.preview_items = []
        self.check_vars = {}
        self._selected_index = None
        preview_canvas.clear_completeness(self)

        self.poster_label.configure(image="", text="")
        self._poster_ref = None
        self.show_info_label.configure(text="")
        self.poster_row.pack_forget()
        detail_panel.reset_detail(self)

        self.media_label_var.set(f"Movies — {self.folder.name}")
        self._movie_label_text = self.media_label_var.get()
        self.active_scan = None
        self._library_selected_index = None
        self._sync_movie_library_state(scanned=False, scanning=True)
        self._show_library_panel(show_scan_all=False)
        self.root.update_idletasks()
        library_panel.display_library(self)
        self._save_movie_session_state()
        self.run_preview()

    # ══════════════════════════════════════════════════════════════════
    #  Preview scanning
    # ══════════════════════════════════════════════════════════════════

    def run_preview(self):
        # In batch mode, refresh the currently selected show
        if self.batch_mode:
            if (self._library_selected_index is not None
                    and self._library_selected_index < len(self.batch_states)):
                state = self.batch_states[self._library_selected_index]
                state.reset_scan()
                library_panel.select_show(self, self._library_selected_index)
            return

        if not self.folder or not self.media_info:
            messagebox.showwarning("Not Ready", "Select a folder and media first.")
            return

        self.preview_items = []
        self.check_vars = {}
        self._selected_index = None

        if self.media_type == MediaType.TV and self.tv_scanner:
            if self.active_scan is not None:
                self.active_scan.scanning = True
            self._set_scan_progress(
                ScanLifecycle.SCANNING,
                phase="Scanning TV files...",
                message="Scanning TV files...",
            )
            self.root.update_idletasks()

            items, has_mismatch = self.tv_scanner.scan()

            if has_mismatch:
                info = self.tv_scanner.get_mismatch_info()
                if dialogs.prompt_season_fix(self.root, info):
                    items = self.tv_scanner.scan_consolidated()

            self.preview_items = items
            check_duplicates(self.preview_items)
            if self.active_scan is not None:
                self.active_scan.scanning = False
                self.active_scan.scanned = True

            initial_checked = {
                i for i, it in enumerate(self.preview_items)
                if it.status == "OK"
            }
            self._completeness = self.tv_scanner.get_completeness(
                self.preview_items, checked_indices=initial_checked)

            if self.library_states:
                library_panel.load_library_thumbnails(self)
                library_panel.display_library(self)
                self.root.update_idletasks()
                self._last_canvas_width = self.preview_canvas.winfo_width()

            preview_canvas.display_preview(self)
            preview_canvas.display_completeness(self)
            self._set_scan_progress(
                ScanLifecycle.READY,
                phase="TV scan complete",
                message=f"Preview ready — {len(self.preview_items)} file(s)",
            )
            self._request_persistence("tv", "cache")

            if is_already_complete(self.preview_items):
                result_views.show_already_renamed(self, self._completeness)
                return

        elif self.media_type == MediaType.MOVIE and self.movie_scanner:
            tmdb = self._ensure_tmdb()
            if tmdb:
                old_files = self.movie_scanner.explicit_files
                if old_files:
                    still_exist = [f for f in old_files if f.exists()]
                    if still_exist:
                        self.movie_scanner = MovieScanner(tmdb, self.folder, files=still_exist)
                    else:
                        self.movie_scanner = MovieScanner(tmdb, self.folder)
                else:
                    self.movie_scanner = MovieScanner(tmdb, self.folder)
            self._movie_scanner_state = self.movie_scanner
            self._sync_movie_library_state(scanned=False, scanning=True)
            library_panel.display_library(self)
            self._run_movie_scan_async()

    def _run_movie_scan_async(self):
        scanner = self.movie_scanner
        self._set_scan_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning files...",
            message="Scanning files...",
        )
        show_progress(self.progress_bar, self.progress_var, True)
        self._set_scan_buttons_enabled(False)
        self.root.update_idletasks()

        result_holder: list[list[PreviewItem] | None] = [None]
        error_holder: list[Exception | None] = [None]

        def _progress(done, total, phase):
            self.root.after(0, lambda: (
                self._set_scan_progress(
                    ScanLifecycle.SCANNING,
                    phase=phase,
                    done=done,
                    total=total,
                    message=f"{phase} {done}/{total}",
                ),
            ))

        def _scan_worker():
            try:
                result_holder[0] = scanner.scan(
                    pick_movie_callback=None,
                    progress_callback=_progress,
                )
            except Exception as e:
                error_holder[0] = e
            self.root.after(0, _on_complete)

        def _on_complete():
            self._set_scan_buttons_enabled(True)
            show_progress(self.progress_bar, self.progress_var, False)

            if error_holder[0]:
                messagebox.showerror(
                    "Scan Error", f"Error during scan:\n{error_holder[0]}")
                self._set_scan_progress(
                    ScanLifecycle.FAILED,
                    phase="Scan failed.",
                    message="Scan failed.",
                )
                return

            movie_items = result_holder[0] or []
            check_duplicates(movie_items)
            movie_preview_items = [
                item for item in movie_items if item.media_type == MediaType.MOVIE
            ]
            skipped_count = len(movie_items) - len(movie_preview_items)

            if not movie_preview_items:
                self._movie_preview_items_state = []
                self._movie_check_vars_state = {}
                self._library_selected_index = None
                self._movie_selected_index_state = None
                self._sync_movie_library_state(scanned=True, scanning=False)
                library_panel.display_library(self)
                self._clear_canvas()
                detail_panel.reset_detail(self)
                self._set_scan_progress(
                    ScanLifecycle.WARNING,
                    phase="Movie scan complete",
                    message=(
                        "No movie files found"
                        + (f"  ·  skipped {skipped_count} non-movie file(s)"
                           if skipped_count else "")
                    ),
                )
                self.snapshot_service.delete_snapshot(SNAPSHOT_MOVIE_BATCH)
                self._request_persistence("cache")
                return

            ok_items = [it for it in movie_preview_items if it.status == "OK"]
            already_done = [
                it for it in ok_items
                if it.new_name == it.original.name
                and (it.target_dir is None or it.target_dir == it.original.parent)
            ]
            needs_action = [
                it for it in movie_preview_items
                if it not in already_done
            ]

            if is_already_complete(movie_preview_items) and not needs_action:
                self._movie_preview_items_state = list(movie_preview_items)
                self._sync_movie_library_state(scanned=True, scanning=False)
                library_panel.load_library_thumbnails(self)
                library_panel.display_library(self)
                self._preview_items = list(movie_preview_items)
                self._check_vars = {}
                self.__selected_index = None
                preview_canvas.display_preview(self)
                self._set_scan_progress(
                    ScanLifecycle.READY,
                    phase="Movie scan complete",
                    message=f"All {len(already_done)} movie file(s) are already properly named",
                )
                self._request_persistence("movie", "cache")
                result_views.show_already_renamed_movies(self, already_done)
                return

            if already_done and needs_action:
                self._set_scan_progress(
                    ScanLifecycle.READY,
                    phase="Movie scan complete",
                    message=(
                        f"Preview: {len(needs_action)} file(s) to review  ·  "
                        f"{len(already_done)} already properly named"
                        + (f"  ·  skipped {skipped_count} non-movie file(s)"
                           if skipped_count else "")
                    ),
                )
            elif skipped_count:
                self._set_scan_progress(
                    ScanLifecycle.READY,
                    phase="Movie scan complete",
                    message=(
                        f"Preview: {len(movie_preview_items)} movie file(s)  ·  "
                        f"skipped {skipped_count} non-movie file(s)"
                    ),
                )
            else:
                self._set_scan_progress(
                    ScanLifecycle.READY,
                    phase="Movie scan complete",
                    message=f"Preview ready — {len(movie_preview_items)} movie file(s)",
                )

            self._movie_preview_items_state = list(movie_preview_items)
            self._movie_check_vars_state = {
                key: var for key, var in self._movie_check_vars_state.items()
                if key in {str(i) for i in range(len(movie_preview_items))}
            }
            self._library_selected_index = 0 if movie_preview_items else None
            self._movie_selected_index_state = 0 if movie_preview_items else None
            self._sync_movie_library_state(scanned=True, scanning=False)
            library_panel.load_library_thumbnails(self)
            library_panel.display_library(self)

            if self.library_states:
                preferred_index = next(
                    (
                        idx for idx, state in enumerate(self.library_states)
                        if state.preview_items
                        and self._movie_item_is_actionable(state.preview_items[0])
                    ),
                    0,
                )
                self._library_selected_index = preferred_index
                library_panel.select_show(self, preferred_index)
            else:
                self._clear_canvas()
                detail_panel.reset_detail(self)

            self._request_persistence("movie", "cache")

        threading.Thread(target=_scan_worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════
    #  Re-match (movies)
    # ══════════════════════════════════════════════════════════════════

    def _rematch_selected_movie(self):
        if self._selected_index is None or self._library_selected_index is None:
            return
        item = self.preview_items[self._selected_index]
        if item.media_type != MediaType.MOVIE or not self.movie_scanner:
            return

        tmdb = self._ensure_tmdb()
        if not tmdb:
            return

        cached = self.movie_scanner.get_search_results(item.original)
        chosen = dialogs.pick_media_dialog(
            self, cached, title_key="title",
            dialog_title=f"Re-match: {item.original.name}",
            allow_skip=True,
            search_callback=tmdb.search_movie,
        )

        if not chosen:
            return

        new_item = self.movie_scanner.rematch_file(item, chosen)
        self._movie_preview_items_state[self._library_selected_index] = new_item
        check_duplicates(self._movie_preview_items_state)

        key = str(self._library_selected_index)
        if key in self._movie_check_vars_state:
            self._movie_check_vars_state[key].set(True)

        self._sync_movie_library_state(scanned=True, scanning=False)
        library_panel.load_library_thumbnails(self)
        library_panel.display_library(self)
        library_panel.select_show(self, self._library_selected_index)
        self._request_persistence("movie", "cache")

    # ══════════════════════════════════════════════════════════════════
    #  Add to Queue / Legacy Rename / Undo
    # ══════════════════════════════════════════════════════════════════

    def _add_to_queue(self):
        """Add current preview selection(s) to the job queue."""
        if self.batch_mode:
            self._add_batch_to_queue()
            return
        self._add_single_to_queue()

    def _add_single_to_queue(self):
        """Add the current single-show or movie to the job queue."""
        if self.media_type == MediaType.MOVIE and self.library_states:
            self._add_movie_batch_to_queue()
            return

        checked = {
            i for i, item in enumerate(self.preview_items)
            if self.check_vars.get(str(i)) is not None
            and self.check_vars[str(i)].get()
            and item.is_actionable
        }

        eligibility = self.command_gating.evaluate_preview_items(
            self.preview_items,
            selected_indices=checked,
            is_scanning=bool(self.active_scan and self.active_scan.scanning),
            is_queued=bool(self.active_scan and self.active_scan.queued),
            needs_review=bool(self.active_scan and self.active_scan.needs_review),
        )

        if not eligibility.enabled:
            if eligibility.command_state.value == "disabled_no_selection":
                messagebox.showwarning("Preview First", eligibility.reason)
            else:
                messagebox.showinfo("Nothing to do", eligibility.reason)
            return

        checked = set(eligibility.selected_indices)

        media_name = (
            self.media_info.get("name")
            or self.media_info.get("title")
            or self.folder.name
        )
        tmdb_id = self.media_info.get("id", 0)

        show_folder = None
        if self.media_type == MediaType.TV and self.media_info:
            show_folder = build_show_folder_name(
                self.media_info.get("name", ""),
                self.media_info.get("year", ""),
            )

        # Determine library root — for single-show TV the library root
        # is the parent of the show folder; for movies it's the folder itself
        if self.media_type == MediaType.TV:
            library_root = self.folder.parent
        else:
            library_root = self.folder

        job = build_rename_job_from_items(
            items=self.preview_items,
            checked_indices=checked,
            media_type=self.media_type,
            tmdb_id=tmdb_id,
            media_name=media_name,
            library_root=library_root,
            source_folder=self.folder,
            show_folder_rename=show_folder,
        )

        try:
            self.job_store.add_job(job)
        except DuplicateJobError as e:
            messagebox.showinfo(
                "Already Queued",
                f"'{e.media_name}' already has a pending rename job.")
            return

        # Mark the active scan as queued (if applicable)
        if self.active_scan:
            self.active_scan.queued = True
            if self.library_states:
                library_panel.display_library(self)

        self.status_var.set(
            f"Added '{media_name}' to queue ({len(checked)} files)")
        self._update_queue_badge()

    def _add_movie_batch_to_queue(self):
        """Add selected movie rows as individual jobs in movie batch mode."""
        if not self.library_states:
            messagebox.showwarning(
                "Preview First", "Scan and review files before queueing.")
            return

        library_root = self._movie_folder_state or self.folder
        if library_root is None:
            messagebox.showwarning("Not Ready", "Select a movie folder first.")
            return

        added = 0
        skipped_dup = 0
        skipped_queued = 0

        for state in self.library_states:
            eligibility = self.command_gating.evaluate_scan_state(state)
            if not eligibility.enabled:
                if eligibility.command_state.value == "disabled_already_queued":
                    skipped_queued += 1
                continue

            if not state.preview_items:
                skipped_queued += 1
                continue

            item = state.preview_items[0]

            # Compute the expected Plex folder name from TMDB metadata
            # so the job executor renames the folder to match.
            movie_folder = build_movie_name(
                state.media_info.get("title", ""),
                state.media_info.get("year", ""),
                "",
            )

            job = build_rename_job_from_items(
                items=[item],
                checked_indices={0},
                media_type=MediaType.MOVIE,
                tmdb_id=state.show_id or 0,
                media_name=state.display_name,
                library_root=library_root,
                source_folder=item.original.parent,
                show_folder_rename=movie_folder,
            )

            try:
                self.job_store.add_job(job)
                state.queued = True
                added += 1
            except DuplicateJobError:
                skipped_dup += 1

        if added:
            library_panel.display_library(self)

        if not added and not skipped_dup and not skipped_queued:
            messagebox.showinfo("Nothing to do", "No movies selected.")
        else:
            self.status_var.set(
                f"Added {added} movie job(s) to queue"
                + (f" ({skipped_dup + skipped_queued} already queued)"
                   if (skipped_dup + skipped_queued) else "")
            )
        self._update_queue_badge()

    def _add_batch_to_queue(self):
        """Add all checked shows from batch mode to the job queue."""
        added = 0
        skipped_dup = 0
        skipped_queued = 0
        skipped_no_action = 0
        blocked_details: list[str] = []
        errors = []

        for state in self.batch_states:
            if not state.checked:
                continue

            eligibility = self.command_gating.evaluate_scan_state(
                state,
                allow_show_level_queue=True,
            )
            if not eligibility.enabled:
                if eligibility.command_state.value == "disabled_already_queued":
                    skipped_queued += 1
                else:
                    blocked_details.append(
                        f"{state.display_name}: {eligibility.reason}")
                continue

            checked = set(eligibility.selected_indices)

            show_folder = build_show_folder_name(
                state.media_info.get("name", ""),
                state.media_info.get("year", ""),
            )

            job = build_rename_job_from_state(
                state=state,
                library_root=self.folder,
                show_folder_rename=show_folder,
                checked_indices=checked,
            )

            try:
                self.job_store.add_job(job)
                state.queued = True
                added += 1
            except DuplicateJobError:
                skipped_dup += 1
            except Exception as e:
                errors.append(f"{state.display_name}: {e}")

        # Refresh library panel to show queued states
        if added:
            library_panel.display_library(self)

        if errors:
            messagebox.showwarning(
                "Queue Errors",
                f"Added {added} jobs, {skipped_dup} already queued.\n\n"
                f"Errors:\n" + "\n".join(errors[:5]))
        else:
            status_parts = []
            if skipped_dup or skipped_queued:
                status_parts.append(f"{skipped_dup + skipped_queued} already queued")
            if blocked_details:
                status_parts.append(f"{len(blocked_details)} blocked")

            message = f"Added {added} jobs to queue"
            if status_parts:
                message += f" ({', '.join(status_parts)})"
            self.status_var.set(message)

            if blocked_details:
                messagebox.showinfo(
                    "Some Shows Were Not Queued",
                    "\n".join(blocked_details[:8]),
                )

        self._update_queue_badge()

    def _execute_rename(self):
        """Legacy direct rename — kept for backward compatibility."""
        if self.batch_mode:
            self._execute_batch_rename()
            return

        if not self.preview_items or not self.check_vars:
            messagebox.showwarning(
                "Preview First", "Scan and review files before renaming.")
            return

        checked = {
            i for i, item in enumerate(self.preview_items)
            if self.check_vars.get(str(i)) is not None
            and self.check_vars[str(i)].get()
            and (item.status == "OK" or "UNMATCHED" in item.status)
            and item.new_name
        }

        if not checked:
            messagebox.showinfo("Nothing to do", "No files selected for rename.")
            return

        move_count = sum(1 for i in checked if self.preview_items[i].is_move())
        msg = f"Rename {len(checked)} file(s)?"
        if move_count:
            msg += f"\n\n{move_count} file(s) will be moved to a different folder."
            msg += "\nEmpty source folders will be removed."
        msg += "\n\nThis can be undone via 'Undo Last'."

        if not messagebox.askyesno("Confirm Rename", msg):
            return

        renamed_items = [
            self.preview_items[i] for i in sorted(checked)
        ]

        media_name = (
            self.media_info.get("name")
            or self.media_info.get("title")
            or self.folder.name
        )

        show_folder = None
        if self.media_type == MediaType.TV and self.media_info:
            show_folder = build_show_folder_name(
                self.media_info.get("name", ""),
                self.media_info.get("year", ""),
            )

        job = build_rename_job_from_items(
            self.preview_items,
            checked,
            self.media_type,
            self.media_info.get("id", 0) if self.media_info else 0,
            media_name,
            self.folder,
            self.folder,
            show_folder_rename=show_folder,
        )

        result = execute_rename(
            self.preview_items, checked, media_name, self.folder,
            show_folder_name=show_folder,
        )
        self._record_completed_rename_job(job, result)

        if result.new_root:
            self.folder = result.new_root
            if self.tv_scanner:
                self.tv_scanner.root = result.new_root

        if self.tv_scanner:
            self.tv_scanner.invalidate_cache()

        self._result_collapsed_seasons = set()
        by_season: dict[int | None, list[PreviewItem]] = defaultdict(list)
        for item in renamed_items:
            by_season[item.season].append(item)
        if self._completeness:
            for sn, sc in self._completeness.seasons.items():
                if sc.is_complete and sn in by_season:
                    self._result_collapsed_seasons.add(sn)
            sp = self._completeness.specials
            if sp and sp.is_complete and 0 in by_season:
                self._result_collapsed_seasons.add(0)
        result_views.show_rename_result(self, result, renamed_items)

    def _execute_batch_rename(self):
        """Legacy batch rename — kept for backward compatibility."""
        # Collect checked items across all scanned states
        total_files = 0
        show_count = 0
        for state in self.batch_states:
            if not state.checked or not state.scanned:
                continue
            checked = get_checked_indices_from_state(state)
            if checked:
                total_files += len(checked)
                show_count += 1

        if total_files == 0:
            messagebox.showinfo("Nothing to do", "No files selected for rename.")
            return

        msg = f"Rename {total_files} file(s) across {show_count} show(s)?"
        msg += "\n\nEach show creates a separate undo entry."
        msg += "\n\nThis can be undone via 'Undo Last' (one show at a time)."
        if not messagebox.askyesno("Confirm Batch Rename", msg):
            return

        # Execute per-show
        all_results: list[tuple[ScanState, RenameResult, list[PreviewItem]]] = []
        for state in self.batch_states:
            if not state.checked or not state.scanned:
                continue
            checked = get_checked_indices_from_state(state)
            if not checked:
                continue

            renamed_items = [state.preview_items[i] for i in sorted(checked)]

            show_folder = build_show_folder_name(
                state.media_info.get("name", ""),
                state.media_info.get("year", ""),
            )

            job = build_rename_job_from_state(
                state,
                self.folder,
                show_folder_rename=show_folder,
                checked_indices=checked,
            )

            result = execute_rename(
                state.preview_items, checked,
                state.display_name, state.folder,
                show_folder_name=show_folder,
            )
            self._record_completed_rename_job(job, result)

            if result.new_root:
                state.folder = result.new_root
                if state.scanner:
                    state.scanner.root = result.new_root

            if state.scanner:
                state.scanner.invalidate_cache()

            all_results.append((state, result, renamed_items))

        # Show batch result view
        if all_results:
            self._batch_result_collapsed = set()
            result_views.show_batch_rename_result(self, all_results)

    def _record_completed_rename_job(self, job: RenameJob, result: RenameResult) -> None:
        """Persist a direct rename as completed history for unified revert."""
        if result.renamed_count == 0:
            return

        job.status = JobStatus.COMPLETED
        job.undo_data = result.log_entry
        if result.errors:
            job.error_message = "; ".join(result.errors[:5])
        self.job_store.add_job(job)
        self._refresh_history_tab()
        self._update_queue_badge()

    def _latest_revertible_job(self) -> RenameJob | None:
        """Return the most recent completed job with stored undo data."""
        return self.job_store.get_latest_completed_with_undo()

    def _has_revertible_job(self) -> bool:
        """True when an undo action can be offered."""
        return self._latest_revertible_job() is not None

    def undo(self):
        job = self._latest_revertible_job()
        if job is None or not job.undo_data:
            messagebox.showinfo("Nothing to Undo", "No completed rename job found.")
            return

        undo = job.undo_data
        move_count = sum(
            1 for e in undo.get("renames", [])
            if Path(e["old"]).parent != Path(e["new"]).parent
        )

        desc = f"Undo {len(undo.get('renames', []))} renames for '{job.media_name}'?"
        if move_count:
            desc += f"\n\n{move_count} file(s) will be moved back."
        if undo.get("removed_dirs"):
            dirs = [Path(d).name for d in undo["removed_dirs"]]
            desc += f"\n\nThese folders will be recreated: {', '.join(dirs)}"

        if not messagebox.askyesno("Undo Rename", desc):
            return

        success, errors = revert_job(job)
        self.job_store.update_status(
            job.job_id,
            JobStatus.REVERTED,
            error_message="; ".join(errors[:3]) if errors else None,
        )

        for entry in undo.get("renamed_dirs", []):
            if Path(entry["new"]) == self.folder:
                old_root = Path(entry["old"])
                if old_root.exists():
                    self.folder = old_root
                    if self.tv_scanner:
                        self.tv_scanner.root = old_root
                break

        if errors:
            messagebox.showwarning("Partial Undo",
                                   f"Errors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Undone", "Rename successfully undone.")

        self.status_var.set("Undo complete.")
        self._refresh_history_tab()
        self._update_queue_badge()
        detail_panel.reset_detail(self)
        if self.tv_scanner:
            self.tv_scanner.invalidate_cache()
        if self.movie_scanner:
            tmdb = self._ensure_tmdb()
            if tmdb:
                files = self.movie_scanner.explicit_files
                self.movie_scanner = MovieScanner(tmdb, self.folder, files=files)
        if self.folder and self.media_info:
            self.run_preview()

    # ══════════════════════════════════════════════════════════════════
    #  Queue tab (notebook-based)
    # ══════════════════════════════════════════════════════════════════

    def _ensure_queue_tab(self):
        """Build the queue tab widgets lazily on first show."""
        if hasattr(self, '_queue_tab_built'):
            return
        self._queue_tab_built = True

        from .queue_panel import build_queue_tab
        build_queue_tab(self, self._queue_frame)

    def _refresh_queue_tab(self):
        """Refresh the queue tab contents."""
        if hasattr(self, '_queue_tab_refresh'):
            self._queue_tab_refresh()

    def _ensure_history_tab(self):
        """Build the history tab widgets lazily on first show."""
        if hasattr(self, '_history_tab_built'):
            return
        self._history_tab_built = True

        from .queue_panel import build_history_tab
        build_history_tab(self, self._history_frame)

    def _refresh_history_tab(self):
        """Refresh the history tab contents."""
        if hasattr(self, '_history_tab_refresh'):
            self._history_tab_refresh()

    def _ensure_settings_tab(self):
        """Build the settings tab widgets lazily on first show."""
        if hasattr(self, '_settings_tab_built'):
            return
        self._settings_tab_built = True

        c = self.c
        pad = ttk.Frame(self._settings_frame, style="Mid.TFrame")
        pad.pack(fill="both", expand=True, padx=40, pady=20)

        ttk.Label(
            pad, text="SETTINGS", style="Title.TLabel",
            background=c["bg_mid"],
        ).pack(anchor="w", pady=(0, 16))

        # ── Display preferences ───────────────────────────────────
        ttk.Label(
            pad, text="DISPLAY", style="DetailDim.TLabel",
            font=("Helvetica", 9, "bold"), background=c["bg_mid"],
        ).pack(anchor="w", pady=(0, 8))

        hide_named_check = ttk.Checkbutton(
            pad, text="Hide already properly named shows in library panel",
            variable=self.settings_hide_named,
            style="Card.TCheckbutton",
        )
        hide_named_check.pack(anchor="w", pady=(0, 16))

        ttk.Separator(pad, orient="horizontal").pack(fill="x", pady=(0, 16))

        # ── API Keys ──────────────────────────────────────────────
        ttk.Label(
            pad, text="API KEYS", style="DetailDim.TLabel",
            font=("Helvetica", 9, "bold"), background=c["bg_mid"],
        ).pack(anchor="w", pady=(0, 8))

        key_row = ttk.Frame(pad, style="Mid.TFrame")
        key_row.pack(fill="x", pady=4)

        ttk.Label(key_row, text="TMDB:", width=6, background=c["bg_mid"],
                  foreground=c["text_dim"]).pack(side="left")
        self._tmdb_key_var = tk.StringVar(
            value=get_api_key("TMDB") or "")
        key_entry = ttk.Entry(key_row, textvariable=self._tmdb_key_var,
                              width=40, show="*")
        key_entry.pack(side="left", padx=(8, 8), fill="x", expand=True)

        def _save_tmdb_key():
            key = self._tmdb_key_var.get().strip()
            if key:
                save_api_key("TMDB", key)
                self.tmdb = None  # Force client refresh
                from tkinter import messagebox
                messagebox.showinfo("Saved", "TMDB key saved.",
                                    parent=self.root)

        ttk.Button(key_row, text="Save", style="Small.TButton",
                   command=_save_tmdb_key).pack(side="left")

    def _on_settings_changed(self):
        """Refresh displays when settings change."""
        if self.library_states:
            library_panel.display_library(self)

    def _restore_queued_states(self):
        """
        After batch discovery, mark shows as queued if they have
        pending/running jobs in the database.  Fixes the issue where
        restarting the program loses the queued visual indicator.

        Skips duplicate entries — only the primary match for a given
        TMDB ID should be marked as queued.
        """
        if not self.batch_states:
            return
        queued_ids = self.job_store.get_queued_tmdb_ids()
        if not queued_ids:
            return
        for state in self.batch_states:
            if (state.show_id
                    and state.show_id in queued_ids
                    and state.duplicate_of is None):
                state.queued = True

    def _sync_queued_library_states(self) -> None:
        """Refresh queued flags for TV and movie rosters from the job store."""
        queued_keys = {
            (job.media_type, job.tmdb_id)
            for job in self.job_store.get_queue()
            if job.tmdb_id
        }

        for state in self.batch_states:
            if state.duplicate_of is not None:
                state.queued = False
                continue
            state.queued = (MediaType.TV, state.show_id or 0) in queued_keys

        for state in self._movie_library_states:
            state.queued = (MediaType.MOVIE, state.show_id or 0) in queued_keys

    def _update_queue_badge(self):
        """Update Queue and History tab titles with count badges."""
        counts = self.job_store.count_by_status()
        pending = counts.get('pending', 0)
        running = counts.get('running', 0)
        total = pending + running
        hist = sum(counts.get(s, 0) for s in
                   ('completed', 'failed', 'cancelled', 'reverted'))
        try:
            # Tab 2 = Queue
            if total > 0:
                self._main_notebook.tab(2, text=f"  Queue ({total})  ")
            else:
                self._main_notebook.tab(2, text="  Queue  ")
            # Tab 3 = History
            if hist > 0:
                self._main_notebook.tab(3, text=f"  History ({hist})  ")
            else:
                self._main_notebook.tab(3, text="  History  ")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════
    #  Run
    # ══════════════════════════════════════════════════════════════════

    def run(self):
        """Start the tkinter main loop."""
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        """Clean shutdown: stop executor, close DB, destroy window."""
        self._cancel_pending_persistence()
        self.snapshot_service.set_active_snapshot_id(
            self._active_snapshot_id_for_current_session()
        )
        self._flush_pending_persistence(force_kinds={"tv", "movie", "cache"})
        if self.queue_executor.is_running:
            self.queue_executor.stop()
        self.job_store.close()
        self.root.destroy()
