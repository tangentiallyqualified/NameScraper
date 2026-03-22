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

from ..constants import MediaType, VIDEO_EXTENSIONS
from ..engine import (
    CompletenessReport,
    MovieScanner,
    PreviewItem,
    RenameResult,
    SeasonCompleteness,
    TVScanner,
    CANCEL_SCAN,
    AUTO_ACCEPT_THRESHOLD,
    score_results,
    check_duplicates,
    execute_rename,
    execute_undo,
)
from ..keys import get_api_key, save_api_key
from ..parsing import build_show_folder_name, clean_folder_name, extract_year
from ..styles import COLORS, get_dpi_scale, setup_styles
from ..tmdb import TMDBClient
from ..undo_log import load_log

from . import detail_panel, dialogs, preview_canvas, result_views
from .helpers import (
    bind_mousewheel,
    init_platform,
    setup_detail_mousewheel,
    show_progress,
)


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
        self.preview_items: list[PreviewItem] = []
        self.tv_scanner: TVScanner | None = None
        self.movie_scanner: MovieScanner | None = None
        self.tmdb: TMDBClient | None = None

        self._poster_ref = None
        self._detail_img_ref = None
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self._selected_index: int | None = None
        self._card_positions: list[tuple[int, int, int]] = []
        self._season_header_positions: list[tuple[int, int, int]] = []
        self._display_order: list[int] = []
        self._resize_after_id = None
        self._last_canvas_width: int = 0
        self._completeness: CompletenessReport | None = None
        self._completeness_after_id = None
        self._collapsed_seasons: set[int] = set()
        self._result_collapsed_seasons: set[int] = set()
        self._last_rename_result: RenameResult | None = None
        self._last_renamed_items: list[PreviewItem] | None = None

        # ── Theme + layout ────────────────────────────────────────────
        self._check_imgs = setup_styles(self.root, self.dpi_scale)
        self._build_layout()

        # ── Cached font objects ───────────────────────────────────────
        self._font_orig = tkfont.Font(family="Helvetica", size=11)
        self._font_new = tkfont.Font(family="Helvetica", size=10)
        self._font_badge = tkfont.Font(family="Helvetica", size=8, weight="bold")
        self._font_check = tkfont.Font(family="Helvetica", size=14)

        # Keyboard bindings
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<F5>", lambda e: self.run_preview())

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

        ttk.Button(
            btn_area, text="API Keys",
            command=lambda: dialogs.manage_keys_dialog(self),
            style="Small.TButton",
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            btn_area, text="Undo Last", command=self.undo,
            style="Small.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

        # ── Action bar ────────────────────────────────────────────────
        action_bar = ttk.Frame(self.root)
        action_bar.pack(fill="x", padx=20, pady=(10, 6))
        action_bar.columnconfigure(2, weight=1)

        self.select_btn_frame = ttk.Frame(action_bar)
        self.select_btn_frame.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.btn_select_folder = ttk.Button(
            self.select_btn_frame, text="Select Show Folder",
            command=self.pick_folder,
        )
        self.btn_select_folder.pack(side="left")

        self.btn_select_movie_folder = ttk.Button(
            self.select_btn_frame, text="Select Folder",
            command=self.pick_folder,
        )
        self.btn_select_movie_files = ttk.Button(
            self.select_btn_frame, text="Select File(s)",
            command=self.pick_files,
        )

        type_frame = ttk.Frame(action_bar)
        type_frame.grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(type_frame, text="Type:", foreground=c["text_dim"]).pack(
            side="left", padx=(0, 4))
        self.type_var = tk.StringVar(value="TV Series")
        type_combo = ttk.Combobox(
            type_frame, textvariable=self.type_var,
            values=["TV Series", "Movie"], width=10, state="readonly",
        )
        type_combo.pack(side="left")
        type_combo.bind("<<ComboboxSelected>>", self._on_type_change)

        search_frame = ttk.Frame(action_bar)
        search_frame.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(search_frame, text="Filter:", foreground=c["text_dim"]).pack(
            side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: preview_canvas.update_search(self))

        sel_frame = ttk.Frame(action_bar)
        sel_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.tally_var = tk.StringVar(value="0 / 0")
        ttk.Label(
            sel_frame, textvariable=self.tally_var,
            foreground=c["accent"], font=("Helvetica", 11, "bold"),
        ).pack(side="left", padx=(0, 4))
        ttk.Label(
            sel_frame, text="selected", foreground=c["text_dim"],
            font=("Helvetica", 10),
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            sel_frame, text="Select All",
            command=lambda: preview_canvas.select_all(self),
            style="Small.TButton",
        ).pack(side="left")

        btn_frame = ttk.Frame(action_bar)
        btn_frame.grid(row=1, column=2, sticky="e", pady=(8, 0))

        ttk.Button(
            btn_frame, text="Refresh", command=self.run_preview,
        ).pack(side="left", padx=(0, 8))
        self.btn_rename = ttk.Button(
            btn_frame, text="Rename Files", command=self._execute_rename,
            style="Accent.TButton",
        )
        self.btn_rename.pack(side="left")

        # ── Main content ──────────────────────────────────────────────
        content = ttk.Frame(self.root)
        content.pack(fill="both", expand=True, padx=20)
        content.columnconfigure(0, weight=3, minsize=350)
        content.columnconfigure(1, weight=1, minsize=280)
        content.rowconfigure(0, weight=1)

        list_container = ttk.Frame(content)
        list_container.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

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

        detail_frame = ttk.Frame(content, style="Mid.TFrame")
        detail_frame.grid(row=0, column=1, sticky="nsew")

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

        # ── Status bar ────────────────────────────────────────────────
        status_bar = ttk.Frame(self.root, style="Mid.TFrame")
        status_bar.pack(fill="x", side="bottom")

        self.status_var = tk.StringVar(value="Ready — select a folder to begin")
        ttk.Label(
            status_bar, textvariable=self.status_var, style="Status.TLabel",
        ).pack(side="left", fill="x", expand=True)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            status_bar, variable=self.progress_var, maximum=100,
            style="Accent.Horizontal.TProgressbar", length=200,
        )

    # ══════════════════════════════════════════════════════════════════
    #  TMDB Client
    # ══════════════════════════════════════════════════════════════════

    def _ensure_tmdb(self) -> TMDBClient | None:
        """Get or create the shared TMDB client."""
        if self.tmdb is not None:
            return self.tmdb
        api_key = get_api_key("TMDB")
        if not api_key:
            messagebox.showwarning(
                "No Key", "Set your TMDB API key first via 'API Keys'.")
            return None
        self.tmdb = TMDBClient(api_key)
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

    def _set_scan_buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_select_folder, self.btn_select_movie_folder,
                    self.btn_select_movie_files):
            try:
                btn.configure(state=state)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════
    #  Event handlers
    # ══════════════════════════════════════════════════════════════════

    def _on_type_change(self, event=None):
        val = self.type_var.get()
        if val == "TV Series":
            self.media_type = MediaType.TV
            self.btn_select_movie_folder.pack_forget()
            self.btn_select_movie_files.pack_forget()
            self.btn_select_folder.pack(side="left")
        else:
            self.media_type = MediaType.MOVIE
            self.btn_select_folder.pack_forget()
            self.btn_select_movie_folder.pack(side="left", padx=(0, 4))
            self.btn_select_movie_files.pack(side="left")

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
            folder_name = self.folder.name
            cleaned = clean_folder_name(folder_name)
            search_query = re.sub(r"\s*\(\d{4}\)\s*$", "", cleaned).strip()
            self._search_tv(tmdb, search_query, folder_name)
        else:
            self._setup_movie_scan(tmdb)

    def pick_files(self):
        ext_list = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        files = filedialog.askopenfilenames(
            title="Select Movie File(s)",
            filetypes=[("Video files", ext_list), ("All files", "*.*")],
        )
        if not files:
            return
        file_paths = [Path(f) for f in files]
        self.folder = file_paths[0].parent
        self.status_var.set(f"Selected: {len(file_paths)} file(s) in {self.folder}")

        tmdb = self._ensure_tmdb()
        if not tmdb:
            return
        self._setup_movie_scan(tmdb, files=file_paths)

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
        self.media_info = chosen
        self.tv_scanner = TVScanner(tmdb, chosen, self.folder)
        self.movie_scanner = None
        self._selected_index = None
        preview_canvas.clear_completeness(self)

        # Clear any previous detail content (e.g. from movie mode)
        detail_panel.reset_detail(self)

        detail_panel.display_poster(self, tmdb, chosen["id"], "tv")
        detail_panel.populate_show_info(self, tmdb, chosen["id"])
        year = chosen.get("year", "")
        self.media_label_var.set(
            f"{chosen['name']}" + (f" ({year})" if year else ""))
        self.status_var.set("Scanning files...")
        self.root.update_idletasks()
        self.run_preview()

    def _setup_movie_scan(self, tmdb: TMDBClient, files: list[Path] | None = None):
        self.media_info = {"_type": "movie_batch"}
        self.movie_scanner = MovieScanner(tmdb, self.folder, files=files)
        self.tv_scanner = None
        self._selected_index = None
        preview_canvas.clear_completeness(self)

        self.poster_label.configure(image="", text="")
        self._poster_ref = None
        self.show_info_label.configure(text="")
        self.poster_row.pack_forget()
        detail_panel.reset_detail(self)

        if files and len(files) == 1:
            self.media_label_var.set(f"Movie — {files[0].name}")
        elif files:
            self.media_label_var.set(f"Movies — {len(files)} files selected")
        else:
            self.media_label_var.set(f"Movies — {self.folder.name}")

        if files and len(files) == 1:
            self._run_single_movie_scan(files[0])
        else:
            self.run_preview()

    def _run_single_movie_scan(self, file_path: Path):
        self.status_var.set("Searching TMDB...")
        self.root.update_idletasks()

        self.preview_items = self.movie_scanner.scan(pick_movie_callback=None)
        check_duplicates(self.preview_items)
        preview_canvas.display_preview(self)

        ok_items = [it for it in self.preview_items if it.status == "OK"]
        if ok_items and all(
            it.new_name == it.original.name
            and (it.target_dir is None or it.target_dir == it.original.parent)
            for it in ok_items
        ):
            result_views.show_already_renamed_movies(self, ok_items)
            return

        if len(ok_items) == 1:
            idx = self.preview_items.index(ok_items[0])
            preview_canvas.select_card(self, idx)

    # ══════════════════════════════════════════════════════════════════
    #  Preview scanning
    # ══════════════════════════════════════════════════════════════════

    def run_preview(self):
        if not self.folder or not self.media_info:
            messagebox.showwarning("Not Ready", "Select a folder and media first.")
            return

        self.preview_items = []
        self.check_vars = {}
        self._selected_index = None

        if self.media_type == MediaType.TV and self.tv_scanner:
            self.status_var.set("Scanning TV files...")
            self.root.update_idletasks()

            items, has_mismatch = self.tv_scanner.scan()

            if has_mismatch:
                info = self.tv_scanner.get_mismatch_info()
                if dialogs.prompt_season_fix(self.root, info):
                    items = self.tv_scanner.scan_consolidated()

            self.preview_items = items
            check_duplicates(self.preview_items)

            initial_checked = {
                i for i, it in enumerate(self.preview_items)
                if it.status == "OK"
            }
            self._completeness = self.tv_scanner.get_completeness(
                self.preview_items, checked_indices=initial_checked)

            preview_canvas.display_preview(self)
            preview_canvas.display_completeness(self)

            ok_items = [it for it in self.preview_items if it.status == "OK"]
            if ok_items and all(
                it.new_name == it.original.name
                and (it.target_dir is None or it.target_dir == it.original.parent)
                for it in ok_items
            ):
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
            self._run_movie_scan_async()

    def _run_movie_scan_async(self):
        scanner = self.movie_scanner
        self.status_var.set("Scanning files...")
        show_progress(self.progress_bar, self.progress_var, True)
        self._set_scan_buttons_enabled(False)
        self.root.update_idletasks()

        result_holder: list[list[PreviewItem] | None] = [None]
        error_holder: list[Exception | None] = [None]

        def _progress(done, total, phase):
            pct = (done / total * 100) if total else 0
            self.root.after(0, lambda: (
                self.status_var.set(f"{phase} {done}/{total}"),
                self.progress_var.set(pct),
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
                self.status_var.set("Scan failed.")
                return

            self.preview_items = result_holder[0] or []
            check_duplicates(self.preview_items)

            ok_items = [it for it in self.preview_items if it.status == "OK"]
            already_done = [
                it for it in ok_items
                if it.new_name == it.original.name
                and (it.target_dir is None or it.target_dir == it.original.parent)
            ]
            needs_action = [
                it for it in self.preview_items
                if it not in already_done
            ]

            if already_done and not needs_action:
                preview_canvas.display_preview(self)
                result_views.show_already_renamed_movies(self, already_done)
                return

            if already_done and needs_action:
                self.preview_items = needs_action
                check_duplicates(self.preview_items)
                preview_canvas.display_preview(self)
                self.status_var.set(
                    f"Preview: {len(needs_action)} file(s) to review  ·  "
                    f"{len(already_done)} already properly named")
            else:
                preview_canvas.display_preview(self)

            ok_remaining = [it for it in self.preview_items if it.status == "OK"]
            if ok_remaining:
                idx = self.preview_items.index(ok_remaining[0])
                preview_canvas.select_card(self, idx)

        threading.Thread(target=_scan_worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════
    #  Re-match (movies)
    # ══════════════════════════════════════════════════════════════════

    def _rematch_selected_movie(self):
        if self._selected_index is None:
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
        self.preview_items[self._selected_index] = new_item
        check_duplicates(self.preview_items)

        # Force the rematched item to be checked — it's now a valid OK match.
        # Set it in check_vars before display_preview so saved_checks picks it up.
        key = str(self._selected_index)
        if key in self.check_vars:
            self.check_vars[key].set(True)

        preview_canvas.display_preview(self)
        preview_canvas.select_card(self, self._selected_index)

    # ══════════════════════════════════════════════════════════════════
    #  Rename / Undo
    # ══════════════════════════════════════════════════════════════════

    def _execute_rename(self):
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

        result = execute_rename(
            self.preview_items, checked, media_name, self.folder,
            show_folder_name=show_folder,
        )

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

    def undo(self):
        log = load_log()
        if not log:
            messagebox.showinfo("Nothing to Undo", "No rename history found.")
            return

        last = log[-1]
        move_count = sum(
            1 for e in last["renames"]
            if Path(e["old"]).parent != Path(e["new"]).parent
        )

        desc = f"Undo {len(last['renames'])} renames for '{last['show']}'?"
        if move_count:
            desc += f"\n\n{move_count} file(s) will be moved back."
        if last.get("removed_dirs"):
            dirs = [Path(d).name for d in last["removed_dirs"]]
            desc += f"\n\nThese folders will be recreated: {', '.join(dirs)}"

        if not messagebox.askyesno("Undo Rename", desc):
            return

        success, errors = execute_undo()

        for entry in last.get("renamed_dirs", []):
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
    #  Run
    # ══════════════════════════════════════════════════════════════════

    def run(self):
        """Start the tkinter main loop."""
        self.root.mainloop()
