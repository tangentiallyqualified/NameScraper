"""
Tkinter GUI for Plex Renamer.

Responsibilities:
  - Collect user input (folder, show/movie selection, checkboxes)
  - Display preview items from the engine
  - Forward rename/undo commands to the engine

All business logic lives in the engine module.
Theme/styling lives in the styles module.
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .constants import MediaType, VIDEO_EXTENSIONS
from .engine import (
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
from .keys import get_api_key, save_api_key
from .parsing import build_show_folder_name, clean_folder_name, extract_year
from .styles import COLORS, get_dpi_scale, setup_styles
from .tmdb import TMDBClient
from .undo_log import load_log


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
        tmdb            – shared TMDBClient instance (avoids recreating sessions)
    """

    def __init__(self):
        self._init_platform()

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
        self.tmdb: TMDBClient | None = None  # Shared client — created once

        self._poster_ref = None       # Single poster reference (not a growing list)
        self._detail_img_ref = None   # Single detail image reference
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self._selected_index: int | None = None
        self._card_positions: list[tuple[int, int, int]] = []
        self._season_header_positions: list[tuple[int, int, int]] = []  # (y_start, y_end, season_num)
        self._display_order: list[int] = []
        self._resize_after_id = None
        self._last_canvas_width: int = 0
        self._completeness: CompletenessReport | None = None
        self._completeness_after_id = None  # Debounce timer for check changes
        self._collapsed_seasons: set[int] = set()  # Season nums collapsed in preview
        self._result_collapsed_seasons: set[int] = set()  # Collapsed in results view
        self._last_rename_result: RenameResult | None = None
        self._last_renamed_items: list[PreviewItem] | None = None

        # ── Theme + layout ────────────────────────────────────────────
        self._check_imgs = setup_styles(self.root, self.dpi_scale)
        self._build_layout()

        # ── Cached font objects (reused across redraws) ───────────────
        self._font_orig = tkfont.Font(family="Helvetica", size=11)
        self._font_new = tkfont.Font(family="Helvetica", size=10)
        self._font_badge = tkfont.Font(family="Helvetica", size=8, weight="bold")
        self._font_check = tkfont.Font(family="Helvetica", size=14)

        # Keyboard bindings
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<F5>", lambda e: self.run_preview())

    @staticmethod
    def _init_platform():
        """Platform-specific initialization (DPI awareness on Windows)."""
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

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
            btn_area, text="API Keys", command=self._manage_keys,
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

        # Select buttons
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

        # Media type selector
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

        # Filter
        search_frame = ttk.Frame(action_bar)
        search_frame.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(search_frame, text="Filter:", foreground=c["text_dim"]).pack(
            side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: self._update_search())

        # Row 1: selection controls + action buttons
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
            sel_frame, text="Select All", command=self._select_all,
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

        # Left: scrollable preview list
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

        # Smart resize — only redraws when width actually changes
        self._canvas_in_preview_mode = False  # Guard against resize during result views
        def _on_canvas_resize(event):
            if abs(event.width - self._last_canvas_width) < 10:
                return  # Width didn't meaningfully change
            self._last_canvas_width = event.width
            if self._resize_after_id:
                self.root.after_cancel(self._resize_after_id)
            if self._canvas_in_preview_mode and self._card_positions:
                self._resize_after_id = self.root.after(100, self._display_preview)
        self.preview_canvas.bind("<Configure>", _on_canvas_resize)

        # Mousewheel binding
        self._bind_mousewheel(self.preview_canvas)

        # Right: detail panel
        detail_panel = ttk.Frame(content, style="Mid.TFrame")
        detail_panel.grid(row=0, column=1, sticky="nsew")

        detail_canvas = tk.Canvas(
            detail_panel, bg=c["bg_mid"], highlightthickness=0, bd=0,
        )
        detail_sb = ttk.Scrollbar(
            detail_panel, orient="vertical", command=detail_canvas.yview,
        )
        self.detail_inner = ttk.Frame(detail_canvas, style="Mid.TFrame")
        self.detail_inner.bind(
            "<Configure>",
            lambda e: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")),
        )
        detail_canvas.create_window((0, 0), window=self.detail_inner, anchor="nw")
        detail_canvas.configure(yscrollcommand=detail_sb.set)
        detail_sb.pack(side="right", fill="y")
        detail_canvas.pack(side="left", fill="both", expand=True)

        self._detail_canvas = detail_canvas

        def _sync_detail_width(event):
            items = detail_canvas.find_all()
            if items:
                detail_canvas.itemconfig(items[0], width=event.width)
        detail_canvas.bind("<Configure>", _sync_detail_width)

        # Mousewheel focus management for detail panel
        self._setup_detail_mousewheel(detail_canvas)

        # Detail content — built as a structured panel that gets
        # populated/cleared by _show_detail and _reset_detail
        self._detail_pad = ttk.Frame(self.detail_inner, style="Mid.TFrame")
        self._detail_pad.pack(fill="both", expand=True, padx=14, pady=14)
        pad = self._detail_pad

        # ── Series poster + show info (side by side) ────────────────
        self.poster_row = ttk.Frame(pad, style="Mid.TFrame")
        self.poster_row.pack(fill="x", pady=(0, 6))

        # Poster on the left — fixed width so text gets the rest
        self.poster_label = ttk.Label(
            self.poster_row, style="Detail.TLabel", background=c["bg_mid"],
        )
        self.poster_label.pack(side="left", anchor="nw", padx=(0, 10))

        # Show info text to the right of the poster
        self.show_info_frame = ttk.Frame(self.poster_row, style="Mid.TFrame")
        self.show_info_frame.pack(side="left", fill="both", expand=True, anchor="nw")
        self.show_info_label = ttk.Label(
            self.show_info_frame, text="", style="DetailDim.TLabel",
            wraplength=140, justify="left",
        )
        self.show_info_label.pack(anchor="nw", fill="x")

        # Completeness summary (TV only) — lives under show info, beside poster
        self.completeness_summary_label = ttk.Label(
            self.show_info_frame, text="", style="DetailDim.TLabel",
            justify="left", wraplength=140,
        )
        self.completeness_summary_label.pack(anchor="nw", fill="x", pady=(4, 0))

        # Per-season collapsible details — each season is a clickable header + hidden body
        self.completeness_detail_frame = ttk.Frame(
            self.show_info_frame, style="Mid.TFrame")
        self.completeness_detail_frame.pack(anchor="nw", fill="x", pady=(2, 0))
        self._season_detail_widgets: dict[int, dict] = {}
        self._expanded_seasons: set[int] = set()

        self._separator_after_poster = ttk.Separator(pad, orient="horizontal")
        self._separator_after_poster.pack(fill="x", pady=6)

        # ── Section header (changes contextually) ────────────────────
        self.detail_header = ttk.Label(
            pad, text="SELECT AN ITEM",
            style="DetailDim.TLabel", font=("Helvetica", 9, "bold"),
        )
        self.detail_header.pack(anchor="w", fill="x", pady=(6, 4))

        # ── Episode still / movie poster (content-specific image) ────
        self.detail_image = ttk.Label(pad, style="Detail.TLabel", background=c["bg_mid"])
        self.detail_image.pack(anchor="center", fill="x", pady=(0, 8))

        # ── Episode/movie title ──────────────────────────────────────
        self.detail_ep_title = ttk.Label(
            pad, text="", style="DetailEpTitle.TLabel",
            wraplength=260, justify="left",
        )
        self.detail_ep_title.pack(anchor="w", fill="x", pady=(0, 2))

        # ── Metadata row (rating, runtime, air date) ─────────────────
        self.detail_meta_frame = ttk.Frame(pad, style="Mid.TFrame")
        self.detail_meta_frame.pack(fill="x", pady=(0, 8))
        self.detail_meta_label = ttk.Label(
            self.detail_meta_frame, text="", style="DetailDim.TLabel",
        )
        self.detail_meta_label.pack(anchor="w")

        # ── Rename info card (original → new, status) ────────────────
        # Placed above overview so it's always visible without scrolling
        self.detail_rename_frame = ttk.Frame(pad, style="DetailCard.TFrame")
        self.detail_rename_frame.pack(fill="x", pady=(0, 8))

        rename_inner = ttk.Frame(self.detail_rename_frame, style="DetailCard.TFrame")
        rename_inner.pack(fill="x", padx=10, pady=8)

        ttk.Label(
            rename_inner, text="RENAME", style="DetailMeta.TLabel",
            font=("Helvetica", 8, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        self.detail_orig_label = ttk.Label(
            rename_inner, text="", style="DetailMeta.TLabel",
            wraplength=240, justify="left",
        )
        self.detail_orig_label.pack(anchor="w", fill="x")

        self.detail_new_label = ttk.Label(
            rename_inner, text="", style="DetailMeta.TLabel",
            wraplength=240, justify="left", foreground=c["success"],
        )
        self.detail_new_label.pack(anchor="w", fill="x", pady=(2, 0))

        self.detail_status_label = ttk.Label(
            rename_inner, text="", style="DetailMeta.TLabel",
        )
        self.detail_status_label.pack(anchor="w", fill="x", pady=(4, 0))

        ttk.Separator(pad, orient="horizontal").pack(fill="x", pady=6)

        # ── Overview / synopsis ──────────────────────────────────────
        self.detail_overview = ttk.Label(
            pad, text="", style="DetailOverview.TLabel",
            wraplength=260, justify="left",
        )
        self.detail_overview.pack(anchor="w", fill="x", pady=(0, 8))

        # ── Crew & cast info ─────────────────────────────────────────
        self.detail_crew_frame = ttk.Frame(pad, style="Mid.TFrame")
        self.detail_crew_frame.pack(fill="x", pady=(0, 8))
        self.detail_crew_label = ttk.Label(
            self.detail_crew_frame, text="", style="DetailDim.TLabel",
            wraplength=260, justify="left",
        )
        self.detail_crew_label.pack(anchor="w", fill="x")

        # ── Re-match button (movies only) ────────────────────────────
        self.rematch_btn = ttk.Button(
            pad, text="Re-match on TMDB",
            command=self._rematch_selected_movie,
        )

        # ── Default empty state ──────────────────────────────────────
        self._reset_detail()

        def _on_detail_resize(event):
            available = event.width - 32
            if available > 100:
                self.detail_overview.configure(wraplength=available)
                self.detail_ep_title.configure(wraplength=available)
                # Show info sits beside the poster — gets ~50% of panel
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

        # Progress bar (hidden by default)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            status_bar, variable=self.progress_var, maximum=100,
            style="Accent.Horizontal.TProgressbar", length=200,
        )

    # ── Mousewheel helpers ────────────────────────────────────────────

    def _bind_mousewheel(self, canvas: tk.Canvas):
        """Bind mousewheel scrolling for a canvas via enter/leave focus tracking."""
        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _scroll_linux_up(event):
            canvas.yview_scroll(-3, "units")
        def _scroll_linux_down(event):
            canvas.yview_scroll(3, "units")
        # Store the scroll target on the app so enter/leave can swap it
        self._scroll_target = canvas
        self._scroll_fn = _scroll
        self._scroll_linux_up_fn = _scroll_linux_up
        self._scroll_linux_down_fn = _scroll_linux_down

        def _on_wheel(event):
            self._scroll_target.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_linux_up(event):
            self._scroll_target.yview_scroll(-3, "units")
        def _on_linux_down(event):
            self._scroll_target.yview_scroll(3, "units")

        canvas.bind_all("<MouseWheel>", _on_wheel)
        canvas.bind_all("<Button-4>", _on_linux_up)
        canvas.bind_all("<Button-5>", _on_linux_down)

        # Track which canvas the mouse is over
        canvas.bind("<Enter>", lambda e: setattr(self, '_scroll_target', canvas))

    def _setup_detail_mousewheel(self, detail_canvas: tk.Canvas):
        """Route mousewheel to detail canvas when mouse enters it."""
        detail_canvas.bind("<Enter>",
            lambda e: setattr(self, '_scroll_target', detail_canvas))
        detail_canvas.bind("<Leave>",
            lambda e: setattr(self, '_scroll_target', self.preview_canvas))

    # ══════════════════════════════════════════════════════════════════
    #  TMDB Client management
    # ══════════════════════════════════════════════════════════════════

    def _ensure_tmdb(self) -> TMDBClient | None:
        """
        Get or create the shared TMDB client.

        Reuses the existing client/session. Only reads the keyring when
        no client exists yet. Key changes are handled by _manage_keys
        which sets self.tmdb = None to force re-creation.
        """
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

    def _scale_to_panel(self, img: Image.Image) -> Image.Image:
        """Scale a PIL Image to fit the detail panel width."""
        self.root.update_idletasks()
        try:
            panel_w = self.detail_inner.winfo_width() - 40
        except Exception:
            panel_w = 260
        panel_w = max(150, panel_w)
        if img.width > panel_w:
            scale = panel_w / img.width
            img = img.resize((panel_w, int(img.height * scale)), Image.LANCZOS)
        return img

    def _scale_poster(self, img: Image.Image) -> Image.Image:
        """Scale the series/movie poster to ~45% of panel width for side-by-side layout."""
        self.root.update_idletasks()
        try:
            panel_w = self.detail_inner.winfo_width() - 40
        except Exception:
            panel_w = 260
        target_w = max(80, int(panel_w * 0.45))
        if img.width != target_w:
            scale = target_w / img.width
            img = img.resize((target_w, int(img.height * scale)), Image.LANCZOS)
        return img

    def _create_dialog(self, title: str, width: int = 500, height: int = 300) -> tk.Toplevel:
        """Create a centered modal dialog window."""
        c = self.c
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=c["bg_mid"])
        win.transient(self.root)
        win.grab_set()

        scaled_w = int(width * self.dpi_scale)
        scaled_h = int(height * self.dpi_scale)

        self.root.update_idletasks()
        rx = self.root.winfo_x()
        ry = self.root.winfo_y()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        x = max(0, rx + (rw - scaled_w) // 2)
        y = max(0, ry + (rh - scaled_h) // 2)

        win.geometry(f"{scaled_w}x{scaled_h}+{x}+{y}")
        win.minsize(scaled_w, scaled_h)
        return win

    def _show_progress(self, visible: bool):
        """Show or hide the progress bar in the status bar."""
        if visible:
            self.progress_bar.pack(side="right", padx=(8, 12), pady=4)
        else:
            self.progress_bar.pack_forget()
            self.progress_var.set(0)

    def _set_scan_buttons_enabled(self, enabled: bool):
        """Enable or disable scan-related buttons."""
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_select_folder, self.btn_select_movie_folder,
                    self.btn_select_movie_files):
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _clear_canvas(self) -> tuple[tk.Canvas, int, float]:
        """
        Reset the preview canvas to a blank state for result/status views.

        Clears all items, resets all card tracking state, and returns
        (canvas, canvas_width, dpi_scale) for the caller to draw on.
        """
        cv = self.preview_canvas
        cv.delete("all")
        self._canvas_in_preview_mode = False
        self._card_positions = []
        self._season_header_positions = []
        self._display_order = []
        self.check_vars.clear()
        self._selected_index = None
        return cv, max(600, cv.winfo_width()), self.dpi_scale

    def _draw_canvas_button(
        self,
        cv: tk.Canvas,
        x: int,
        y: int,
        w: int,
        h: int,
        text: str,
        fill: str,
        outline: str,
        text_color: str,
        tag: str,
    ) -> tuple[int, int, int, int]:
        """
        Draw a styled button on the canvas and return its hit region.

        Returns (x, y, x+w, y+h) for click hit-testing.
        """
        cv.create_rectangle(
            x, y, x + w, y + h,
            fill=fill, outline=outline, tags=(tag,))
        cv.create_text(
            x + w // 2, y + h // 2,
            text=text, fill=text_color,
            font=("Helvetica", 10, "bold"), anchor="center",
            tags=(tag,))
        return x, y, x + w, y + h

    def _draw_action_buttons(
        self,
        cv: tk.Canvas,
        y: int,
        canvas_w: int,
        show_undo: bool = True,
        show_scan: bool = True,
    ) -> tuple[int, int, dict[str, tuple[int, int, int, int]]]:
        """
        Draw Undo and/or Scan Again buttons centered on the canvas.

        Returns:
            (btn_y_top, btn_y_bottom, hit_regions)
            where hit_regions is a dict mapping "undo"/"scan" to (x1, y1, x2, y2).
        """
        c = self.c
        s = self.dpi_scale
        btn_h = int(36 * s)
        btn_w = int(130 * s)
        btn_gap = int(12 * s)
        regions: dict[str, tuple[int, int, int, int]] = {}

        if show_undo and show_scan:
            undo_x = canvas_w // 2 - btn_w - btn_gap // 2
            scan_x = canvas_w // 2 + btn_gap // 2
        elif show_undo:
            undo_x = canvas_w // 2 - btn_w // 2
            scan_x = 0  # unused
        else:
            undo_x = 0  # unused
            scan_x = canvas_w // 2 - btn_w // 2

        if show_undo:
            regions["undo"] = self._draw_canvas_button(
                cv, undo_x, y, btn_w, btn_h,
                "Undo", c["error_dim"], c["error"], c["error"], "btn_undo")

        if show_scan:
            regions["scan"] = self._draw_canvas_button(
                cv, scan_x, y, btn_w, btn_h,
                "Scan Again", c["bg_card"], c["border_light"], c["text"], "btn_scan")

        return y, y + btn_h, regions

    def _make_button_click_handler(
        self,
        cv: tk.Canvas,
        btn_y_top: int,
        btn_y_bottom: int,
        regions: dict[str, tuple[int, int, int, int]],
        extra_handler: Callable | None = None,
    ) -> None:
        """
        Bind a click handler to the canvas that dispatches to Undo/Scan buttons.

        Args:
            extra_handler: Optional callback(cx, cy) for additional hit regions
                (e.g. collapsible season headers). Called if no button was hit.
        """
        def _on_click(event):
            cx = cv.canvasx(event.x)
            cy_click = cv.canvasy(event.y)
            if btn_y_top <= cy_click <= btn_y_bottom:
                for name, (x1, y1, x2, y2) in regions.items():
                    if x1 <= cx <= x2:
                        if name == "undo":
                            self.undo()
                        elif name == "scan":
                            self.run_preview()
                        return
            if extra_handler:
                extra_handler(cx, cy_click)

        cv.bind("<Button-1>", _on_click)

    # ══════════════════════════════════════════════════════════════════
    #  Event handlers
    # ══════════════════════════════════════════════════════════════════

    def _on_type_change(self, event=None):
        """Handle media type combobox change — swap buttons and controls."""
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

    def _manage_keys(self):
        c = self.c
        win = self._create_dialog("API Keys", width=480, height=160)

        ttk.Label(
            win, text="API KEY MANAGER", style="Title.TLabel",
            font=("Helvetica", 14, "bold"), background=c["bg_mid"],
        ).pack(anchor="w", padx=20, pady=(16, 12))

        row = ttk.Frame(win, style="Mid.TFrame")
        row.pack(fill="x", padx=20, pady=4)

        ttk.Label(row, text="TMDB:", width=6, background=c["bg_mid"],
                  foreground=c["text_dim"]).pack(side="left")
        var = tk.StringVar(value=get_api_key("TMDB") or "")
        entry = ttk.Entry(row, textvariable=var, width=36, show="*")
        entry.pack(side="left", padx=(8, 8), fill="x", expand=True)

        def _save():
            key = var.get().strip()
            if key:
                save_api_key("TMDB", key)
                self.tmdb = None  # Force client refresh with new key
                messagebox.showinfo("Saved", "TMDB key saved.", parent=win)
            else:
                messagebox.showwarning("Empty", "Key cannot be empty.", parent=win)

        ttk.Button(row, text="Save", style="Small.TButton",
                   command=_save).pack(side="left")

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
        """
        Search TMDB for a TV show and select the best match.

        Auto-accepts the top result if it's a strong title+year match
        against the folder name. Only prompts the user when:
          - No results found (asks for manual search query)
          - Low confidence match (shows selection dialog)
          - Multiple close results (shows selection dialog)
        """
        results = tmdb.search_tv(query)
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

        # Score results against the cleaned folder name
        year_hint = extract_year(raw_name)
        scored = score_results(results, raw_name, year_hint, title_key="name")

        best, best_score = scored[0]

        # Auto-accept if high confidence and clear winner
        # (clear winner = top score is meaningfully above #2)
        runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
        clear_winner = (best_score - runner_up_score) > 0.1

        if best_score >= AUTO_ACCEPT_THRESHOLD and clear_winner:
            chosen = best
        else:
            # Ambiguous — let user pick
            chosen = self._pick_media_dialog(
                results, title_key="name", dialog_title="Select Show",
                search_callback=tmdb.search_tv,
            )
            if not chosen:
                return

        self._accept_tv_show(tmdb, chosen)

    def _accept_tv_show(self, tmdb: TMDBClient, chosen: dict):
        """Accept a TV show match and proceed to scanning."""
        self.media_info = chosen
        self.tv_scanner = TVScanner(tmdb, chosen, self.folder)
        self.movie_scanner = None
        self._clear_completeness()

        self._display_poster(tmdb, chosen["id"], "tv")
        self._populate_show_info(tmdb, chosen["id"])
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
        self._clear_completeness()

        self.poster_label.configure(image="", text="")
        self._poster_ref = None
        self.show_info_label.configure(text="")
        self.poster_row.pack_forget()  # Hide poster row to eliminate whitespace
        self._reset_detail()

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

        # Use batch scan with no callback — auto-matches using confidence scoring.
        # The pick_movie_callback dialog is only needed for manual re-matching.
        self.preview_items = self.movie_scanner.scan(
            pick_movie_callback=None,
        )

        check_duplicates(self.preview_items)
        self._display_preview()

        ok_items = [it for it in self.preview_items if it.status == "OK"]
        if ok_items and all(
            it.new_name == it.original.name
            and (it.target_dir is None or it.target_dir == it.original.parent)
            for it in ok_items
        ):
            self._show_already_renamed_movies(ok_items)
            return

        if len(ok_items) == 1:
            idx = self.preview_items.index(ok_items[0])
            self._select_card(idx)

    # ══════════════════════════════════════════════════════════════════
    #  Media selection dialog
    # ══════════════════════════════════════════════════════════════════

    def _pick_media_dialog(
        self,
        results: list[dict],
        title_key: str = "name",
        dialog_title: str = "Select",
        allow_skip: bool = False,
        search_callback: callable | None = None,
    ) -> dict | None:
        c = self.c
        win = self._create_dialog(dialog_title, width=520, height=440)

        ttk.Label(
            win, text=dialog_title.upper(), style="Title.TLabel",
            font=("Helvetica", 14, "bold"), background=c["bg_mid"],
        ).pack(anchor="w", padx=20, pady=(16, 4))

        subtitle = (
            "No auto-match found — search manually:" if not results
            else "Confirm the match:" if len(results) == 1
            else "Multiple matches — select the correct one:"
        )
        ttk.Label(
            win, text=subtitle, style="Subtitle.TLabel",
            background=c["bg_mid"],
        ).pack(anchor="w", padx=20, pady=(0, 8))

        current_results = list(results)

        if search_callback:
            search_row = ttk.Frame(win, style="Mid.TFrame")
            search_row.pack(fill="x", padx=20, pady=(0, 8))
            search_entry = ttk.Entry(search_row, width=40)
            search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        listbox = tk.Listbox(
            win, width=70, height=10,
            bg=c["bg_card"], fg=c["text"],
            selectbackground=c["accent"], selectforeground=c["bg_dark"],
            font=("Helvetica", 11), borderwidth=0,
            highlightthickness=1, highlightcolor=c["border_light"],
            highlightbackground=c["border"],
        )
        listbox.pack(padx=20, pady=(0, 12), fill="both", expand=True)

        def _populate(items):
            listbox.delete(0, tk.END)
            current_results.clear()
            current_results.extend(items)
            for i, item in enumerate(items):
                name = item.get(title_key, "Unknown")
                year = item.get("year", "")
                year_str = f" ({year})" if year else ""
                listbox.insert(i, f"  {name}{year_str}")
            if items:
                listbox.selection_set(0)

        _populate(results)

        if search_callback:
            def _do_search():
                query = search_entry.get().strip()
                if query:
                    new_results = search_callback(query)
                    if new_results:
                        _populate(new_results)
                    else:
                        listbox.delete(0, tk.END)
                        current_results.clear()
                        listbox.insert(0, "  (no results)")

            ttk.Button(search_row, text="Search", style="Small.TButton",
                       command=_do_search).pack(side="left")
            search_entry.bind("<Return>", lambda e: _do_search())

        selected = [None]

        def on_ok():
            sel = listbox.curselection()
            if sel and sel[0] < len(current_results):
                selected[0] = current_results[sel[0]]
            win.destroy()

        def on_skip():
            win.destroy()

        btn_row = ttk.Frame(win, style="Mid.TFrame")
        btn_row.pack(pady=(0, 16))
        if allow_skip:
            ttk.Button(btn_row, text="Skip", command=on_skip).pack(
                side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Confirm", command=on_ok,
                   style="Accent.TButton").pack(side="left")

        listbox.bind("<Double-Button-1>", lambda e: on_ok())

        self.root.wait_window(win)
        return selected[0]

    def _pick_movie_for_file(self, results: list[dict], filename: str):
        tmdb = self._ensure_tmdb()
        return self._pick_media_dialog(
            results, title_key="title",
            dialog_title=f"Match: {filename}",
            allow_skip=True,
            search_callback=tmdb.search_movie if tmdb else None,
        )

    def _display_poster(self, tmdb: TMDBClient, media_id: int, media_type: str):
        img = tmdb.fetch_poster(media_id, media_type, target_width=400)
        # Ensure poster row is visible
        if not self.poster_row.winfo_ismapped():
            self.poster_row.pack(fill="x", pady=(0, 6), before=self._separator_after_poster)
        if img:
            img = self._scale_poster(img)
            photo = ImageTk.PhotoImage(img)
            self._poster_ref = photo
            self.poster_label.configure(image=photo)
        else:
            self.poster_label.configure(image="", text="(No poster)")

    # ══════════════════════════════════════════════════════════════════
    #  Preview scanning
    # ══════════════════════════════════════════════════════════════════

    def run_preview(self):
        """Scan the folder and display the rename preview."""
        if not self.folder or not self.media_info:
            messagebox.showwarning("Not Ready", "Select a folder and media first.")
            return

        self.preview_items = []
        self.check_vars = {}

        if self.media_type == MediaType.TV and self.tv_scanner:
            self.status_var.set("Scanning TV files...")
            self.root.update_idletasks()

            items, has_mismatch = self.tv_scanner.scan()

            if has_mismatch:
                info = self.tv_scanner.get_mismatch_info()
                if self._prompt_season_fix(info):
                    items = self.tv_scanner.scan_consolidated()

            self.preview_items = items
            check_duplicates(self.preview_items)

            # Compute completeness so season headers can show tallies.
            # Use all OK items as "checked" — matches the default check_var
            # values that _display_preview will create.
            initial_checked = {
                i for i, it in enumerate(self.preview_items)
                if it.status == "OK"
            }
            self._completeness = self.tv_scanner.get_completeness(
                self.preview_items, checked_indices=initial_checked)

            self._display_preview()
            self._display_completeness()

            # Detect "already renamed" — all OK items have matching names
            ok_items = [it for it in self.preview_items if it.status == "OK"]
            if ok_items and all(
                it.new_name == it.original.name
                and (it.target_dir is None or it.target_dir == it.original.parent)
                for it in ok_items
            ):
                self._show_already_renamed(self._completeness)
                return

        elif self.media_type == MediaType.MOVIE and self.movie_scanner:
            # Recreate scanner to pick up any renamed/moved files
            tmdb = self._ensure_tmdb()
            if tmdb:
                old_files = self.movie_scanner.explicit_files
                if old_files:
                    # For explicit file mode, check if files still exist at old paths
                    # If not, fall back to folder scanning (files were renamed/moved)
                    still_exist = [f for f in old_files if f.exists()]
                    if still_exist:
                        self.movie_scanner = MovieScanner(tmdb, self.folder, files=still_exist)
                    else:
                        self.movie_scanner = MovieScanner(tmdb, self.folder)
                else:
                    self.movie_scanner = MovieScanner(tmdb, self.folder)
            self._run_movie_scan_async()

    def _run_movie_scan_async(self):
        """Run movie scan in background thread with progress updates."""
        scanner = self.movie_scanner
        self.status_var.set("Scanning files...")
        self._show_progress(True)
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
            self._show_progress(False)

            if error_holder[0]:
                messagebox.showerror(
                    "Scan Error", f"Error during scan:\n{error_holder[0]}")
                self.status_var.set("Scan failed.")
                return

            self.preview_items = result_holder[0] or []
            check_duplicates(self.preview_items)

            # Separate already-renamed items from items needing action
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
                # Everything is already properly named
                self._display_preview()
                self._show_already_renamed_movies(already_done)
                return

            if already_done and needs_action:
                # Partial: filter out the already-done items, show only what needs work
                self.preview_items = needs_action
                check_duplicates(self.preview_items)
                self._display_preview()
                # Show count of already-done files in status
                self.status_var.set(
                    f"Preview: {len(needs_action)} file(s) to review  ·  "
                    f"{len(already_done)} already properly named")
            else:
                self._display_preview()

            ok_remaining = [it for it in self.preview_items if it.status == "OK"]
            if len(ok_remaining) == 1:
                idx = self.preview_items.index(ok_remaining[0])
                self._select_card(idx)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _prompt_season_fix(self, info: dict) -> bool:
        extra = info["extra_user_seasons"]
        tmdb_desc = ", ".join(
            f"Season {sn} ({count} eps)"
            for sn, count in info["tmdb_seasons"].items()
        )
        user_desc = ", ".join(f"Season {sn}" for sn in info["user_seasons"])

        msg = (
            f"Folder structure mismatch detected!\n\n"
            f"Your folders: {user_desc}\n"
            f"TMDB structure: {tmdb_desc}\n\n"
            f"TMDB does not have: {', '.join(f'Season {s}' for s in extra)}\n\n"
            f"Would you like to automatically fix this?\n"
            f"Files will be renamed and moved into the proper TMDB season folder(s).\n"
            f"Empty folders will be removed after the move."
        )
        return messagebox.askyesno("Season Structure Mismatch", msg)

    # ══════════════════════════════════════════════════════════════════
    #  Preview rendering
    # ══════════════════════════════════════════════════════════════════

    def _display_preview(self):
        """
        Render the preview list using canvas primitives.

        Cards are sorted: OK first, then REVIEW, then SKIP/CONFLICT.
        Each card shows original filename, new name, status, and badges.
        """
        c = self.c
        cv = self.preview_canvas

        # Preserve selections across redraws
        saved_checks = {k: v.get() for k, v in self.check_vars.items()}

        cv.delete("all")
        cv.yview_moveto(0)
        self._card_positions = []
        self._season_header_positions = []
        self._display_order = []

        if not self.preview_items:
            cv.create_text(
                20, 50, text="No files to preview",
                fill=c["text_muted"], font=("Helvetica", 13), anchor="w")
            cv.create_text(
                20, 78, text="Select a media folder to begin",
                fill=c["text_muted"], font=("Helvetica", 10), anchor="w")
            cv.configure(scrollregion=(0, 0, 100, 120))
            self.check_vars.clear()
            self._selected_index = None
            return

        # Sort order — group by season for TV, flat for movies
        is_tv_mode = self.media_type == MediaType.TV
        if is_tv_mode:
            def _sort_key(idx):
                item = self.preview_items[idx]
                sn = item.season if item.season is not None else 9999
                status_pri = 0 if item.status == "OK" else (1 if "REVIEW" in item.status else 2)
                ep = item.episodes[0] if item.episodes else 9999
                return (sn, status_pri, ep, idx)
        else:
            def _sort_key(idx):
                s = self.preview_items[idx].status
                if s == "OK":
                    return (0, idx)
                elif "REVIEW" in s:
                    return (1, idx)
                return (2, idx)

        self._display_order = sorted(range(len(self.preview_items)), key=_sort_key)

        # Create BooleanVars
        self.check_vars.clear()
        for i, item in enumerate(self.preview_items):
            key = str(i)
            default = item.status == "OK"
            var = tk.BooleanVar(value=saved_checks.get(key, default))
            var.trace_add("write", lambda *_: self._on_check_changed())
            self.check_vars[key] = var

        # Font metrics (using cached font objects)
        font_orig = self._font_orig
        font_new = self._font_new
        font_badge = self._font_badge

        line1_h = font_orig.metrics("linespace")
        line2_h = font_new.metrics("linespace")
        badge_text_h = font_badge.metrics("linespace")

        canvas_w = max(600, cv.winfo_width())
        s = self.dpi_scale
        margin_x = int(4 * s)
        margin_y = int(2 * s)
        pad_x = int(14 * s)
        pad_y = int(10 * s)
        bar_w = int(4 * s)
        check_w = int(28 * s)
        badge_h = badge_text_h + int(8 * s)
        badge_px = int(6 * s)
        gap = int(6 * s)

        font_orig_t = ("Helvetica", 11)
        font_new_t = ("Helvetica", 10)
        font_badge_t = ("Helvetica", 8, "bold")
        font_check_t = ("Helvetica", 14)
        font_header_t = ("Helvetica", 10, "bold")
        font_header_sub_t = ("Helvetica", 9)

        y = margin_y
        last_season_drawn: int | None = None

        for display_idx, item_idx in enumerate(self._display_order):
            item = self.preview_items[item_idx]

            # ── Season header bar (TV mode only) ─────────────────────
            if is_tv_mode and item.season is not None and item.season != last_season_drawn:
                last_season_drawn = item.season
                y = self._draw_season_header(
                    cv, y, item.season, canvas_w, margin_x, margin_y, s,
                    font_header_t, font_header_sub_t,
                )

            # Skip cards for collapsed seasons
            if is_tv_mode and item.season is not None and item.season in self._collapsed_seasons:
                continue

            is_multi = len(item.episodes) > 1
            is_special = item.season == 0
            is_movie = item.media_type == MediaType.MOVIE
            has_review = "REVIEW" in item.status
            has_badges = is_multi or is_special or is_movie or has_review
            tag = f"item_{item_idx}"

            # Determine text and colors
            if "SKIP" in item.status:
                name_fg, arrow_fg = c["text_muted"], c["text_muted"]
                arrow_text = item.status
            elif has_review:
                name_fg, arrow_fg = c["text"], c["info"]
                arrow_text = item.status
            elif "CONFLICT" in item.status:
                name_fg, arrow_fg = c["error"], c["error"]
                arrow_text = item.status
            elif item.is_move():
                name_fg, arrow_fg = c["text"], c["move"]
                arrow_text = f"→  [{item.target_dir.name}]  {item.new_name}"
            else:
                name_fg, arrow_fg = c["text"], c["success"]
                arrow_text = f"→  {item.new_name}" if item.new_name else ""

            orig_text = item.original.name
            if item.is_move():
                orig_text = f"[{item.original.parent.name}]  {orig_text}"

            # Card border color
            if has_review:
                border_color = c["badge_review_bd"]
            elif is_special:
                border_color = c["badge_special_bd"]
            elif is_multi:
                border_color = c["badge_multi_bd"]
            else:
                border_color = c["border"]

            y_start = y
            x_left = margin_x
            x_right = canvas_w - margin_x

            # Card colors (computed now, drawn after text measurement)
            is_selected = (self._selected_index == item_idx)
            card_bg = c["bg_card_selected"] if is_selected else c["bg_card"]
            card_outline = c["accent"] if is_selected else border_color

            # Accent bar color
            bar_color = None
            if has_review:
                bar_color = c["badge_review_bd"]
            elif is_special:
                bar_color = c["badge_special_bd"]
            elif is_multi:
                bar_color = c["badge_multi_bd"]
            elif is_movie:
                bar_color = c["badge_movie_bd"]

            # Text starts after bar + padding + checkbox
            check_x = x_left + bar_w + pad_x

            text_x = check_x + check_w
            text_y = y + pad_y
            max_text_w = x_right - text_x - pad_x  # Available width for text

            # Badge pills
            if has_badges:
                bx = text_x
                badges_to_draw = []
                if has_review:
                    badges_to_draw.append((" NEEDS REVIEW ", c["badge_review_bg"],
                                            c["badge_review_fg"], c["badge_review_bd"]))
                if is_movie:
                    badges_to_draw.append((" MOVIE ", c["badge_movie_bg"],
                                            c["badge_movie_fg"], c["badge_movie_bd"]))
                if is_multi:
                    badges_to_draw.append((f" {len(item.episodes)}-PART ",
                                            c["badge_multi_bg"], c["badge_multi_fg"],
                                            c["badge_multi_bd"]))
                if is_special:
                    badges_to_draw.append((" SPECIAL ", c["badge_special_bg"],
                                            c["badge_special_fg"], c["badge_special_bd"]))

                for label, bg, fg, bd in badges_to_draw:
                    tw = font_badge.measure(label)
                    pill_w = tw + badge_px * 2
                    cv.create_rectangle(
                        bx, text_y, bx + pill_w, text_y + badge_h,
                        fill=bg, outline=bd, tags=(tag,))
                    cv.create_text(
                        bx + badge_px, text_y + badge_h // 2, text=label,
                        fill=fg, font=font_badge_t, anchor="w", tags=(tag,))
                    bx += pill_w + gap

                text_y += badge_h + gap

            # Line 1: original filename (with wrapping)
            id1 = cv.create_text(
                text_x, text_y, text=orig_text,
                fill=name_fg, font=font_orig_t, anchor="nw",
                width=max_text_w,
                tags=("text", tag))
            bbox1 = cv.bbox(id1)
            line1_actual_h = (bbox1[3] - bbox1[1]) if bbox1 else line1_h
            text_y += line1_actual_h

            # Line 2: arrow + new name (with wrapping)
            line2_actual_h = 0
            if arrow_text:
                text_y += gap
                id2 = cv.create_text(
                    text_x + 4, text_y, text=arrow_text,
                    fill=arrow_fg, font=font_new_t, anchor="nw",
                    width=max_text_w,
                    tags=("text", tag))
                bbox2 = cv.bbox(id2)
                line2_actual_h = (bbox2[3] - bbox2[1]) if bbox2 else line2_h

            # Compute actual card height now that text is placed
            content_bottom = text_y + line2_actual_h + pad_y
            row_h = max(int(44 * s), content_bottom - y)

            # Draw card background *behind* the already-placed text
            card_id = cv.create_rectangle(
                x_left, y, x_right, y + row_h,
                fill=card_bg, outline=card_outline,
                tags=("card", tag))
            cv.tag_lower(card_id)  # Send behind text and badges

            # Accent bar (on top of card bg, behind text)
            if bar_color:
                bar_id = cv.create_rectangle(
                    x_left, y, x_left + bar_w, y + row_h,
                    fill=bar_color, outline="", tags=(tag,))
                cv.tag_raise(bar_id, card_id)

            # Checkbox (vertically centered in final card height)
            check_var = self.check_vars[str(item_idx)]
            check_cy = y + row_h // 2
            check_char = "☑" if check_var.get() else "☐"
            check_color = c["accent"] if check_var.get() else c["border_light"]
            cv.create_text(
                check_x, check_cy, text=check_char,
                fill=check_color, font=font_check_t, anchor="w",
                tags=(f"check_{display_idx}", "check", tag))

            self._card_positions.append((y_start, y_start + row_h, item_idx))
            y += row_h + margin_y

        content_h = y + 10
        visible_h = cv.winfo_height()
        cv.configure(scrollregion=(0, 0, canvas_w, max(content_h, visible_h)))
        cv.bind("<Button-1>", self._on_canvas_click)
        self._canvas_in_preview_mode = True

        # Status summary
        count_ok = sum(1 for it in self.preview_items if it.status == "OK")
        count_move = sum(1 for it in self.preview_items if it.is_move())
        count_multi = sum(1 for it in self.preview_items if len(it.episodes) > 1)
        count_special = sum(1 for it in self.preview_items if it.season == 0)
        count_review = sum(1 for it in self.preview_items if "REVIEW" in it.status)
        parts = [f"{count_ok} ready"]
        if count_review:
            parts.append(f"{count_review} needs review")
        if count_multi:
            parts.append(f"{count_multi} multi-ep")
        if count_special:
            parts.append(f"{count_special} specials")
        if count_move:
            parts.append(f"{count_move} moving")
        skip = sum(1 for it in self.preview_items
                   if it.status != "OK" and "REVIEW" not in it.status)
        if skip:
            parts.append(f"{skip} skipped")
        self.status_var.set("Preview:  " + "  ·  ".join(parts))
        self._update_tally()

    def _draw_season_header(
        self,
        cv: tk.Canvas,
        y: int,
        season_num: int,
        canvas_w: int,
        margin_x: int,
        margin_y: int,
        s: float,
        font_header_t: tuple,
        font_header_sub_t: tuple,
    ) -> int:
        """
        Draw a season header bar with collapse toggle, season checkbox,
        completeness info, and progress bar.

        Returns the new y position after the header.
        """
        c = self.c
        header_h = int(32 * s)
        pad_x = int(12 * s)
        progress_h = int(4 * s)
        progress_w = int(80 * s)
        x_left = margin_x
        x_right = canvas_w - margin_x
        is_collapsed = season_num in self._collapsed_seasons
        tag = f"season_hdr_{season_num}"

        # Build label text
        arrow = "▸" if is_collapsed else "▾"
        if season_num == 0:
            label = f"{arrow}  Specials"
        else:
            label = f"{arrow}  Season {season_num}"

        # Season checkbox state — checked if all OK items in this season are checked
        season_items = [
            (i, it) for i, it in enumerate(self.preview_items)
            if it.season == season_num and it.status == "OK"
        ]
        all_checked = all(
            self.check_vars.get(str(i)) is not None and self.check_vars[str(i)].get()
            for i, _ in season_items
        ) if season_items else False

        # Get completeness data for this season
        sc = None
        if self._completeness:
            if season_num == 0:
                sc = self._completeness.specials
            else:
                sc = self._completeness.seasons.get(season_num)

        # Header background
        cv.create_rectangle(
            x_left, y, x_right, y + header_h,
            fill=c["bg_mid"], outline=c["border"],
            tags=("season_header", tag))

        # Season checkbox
        check_x = x_left + pad_x
        check_char = "☑" if all_checked else "☐"
        check_color = c["accent"] if all_checked else c["border_light"]
        cv.create_text(
            check_x, y + header_h // 2,
            text=check_char, fill=check_color,
            font=("Helvetica", 14), anchor="w",
            tags=("season_header", tag, f"season_check_{season_num}"))

        # Season label (after checkbox)
        label_x = check_x + int(24 * s)
        cv.create_text(
            label_x, y + header_h // 2,
            text=label, fill=c["text"], font=font_header_t,
            anchor="w", tags=("season_header", tag))

        if sc and sc.expected > 0:
            # Tally text
            if sc.is_complete:
                tally_text = f"{sc.matched}/{sc.expected} — Complete"
                tally_color = c["success"]
            else:
                tally_text = f"{sc.matched}/{sc.expected} ({sc.pct:.0f}%)"
                tally_color = c["accent"] if sc.pct >= 50 else c["error"]

            # Progress bar background (right-aligned)
            bar_x = x_right - pad_x - progress_w
            bar_y = y + (header_h - progress_h) // 2

            cv.create_rectangle(
                bar_x, bar_y, bar_x + progress_w, bar_y + progress_h,
                fill=c["bg_card"], outline="", tags=("season_header", tag))

            # Progress bar fill
            fill_w = int(progress_w * sc.pct / 100)
            if fill_w > 0:
                cv.create_rectangle(
                    bar_x, bar_y, bar_x + fill_w, bar_y + progress_h,
                    fill=tally_color, outline="", tags=("season_header", tag))

            # Tally text to the left of the progress bar
            cv.create_text(
                bar_x - int(8 * s), y + header_h // 2,
                text=tally_text, fill=tally_color, font=font_header_sub_t,
                anchor="e", tags=("season_header", tag))

        self._season_header_positions.append((y, y + header_h, season_num))
        return y + header_h + margin_y

    def _display_completeness(self):
        """
        Populate the completeness summary next to the poster.

        Shows overall progress on the summary label, then builds
        collapsible per-season rows with missing episode details.
        The rename button style changes when the series is 100% matched.
        """
        c = self.c
        report = self._completeness

        if not report:
            self.completeness_summary_label.configure(text="")
            self._clear_season_details()
            self._update_rename_button_style()
            return

        # ── Overall summary line ─────────────────────────────────────
        if report.is_complete:
            summary = (f"✓ Complete — "
                       f"{report.total_matched}/{report.total_expected} episodes")
            fg = c["success"]
        else:
            summary = (f"{report.total_matched}/{report.total_expected} "
                       f"episodes ({report.pct:.0f}%)")
            if report.pct >= 75:
                fg = c["accent"]
            elif report.pct >= 40:
                fg = c["info"]
            else:
                fg = c["error"]

        self.completeness_summary_label.configure(text=summary, foreground=fg)

        # ── Per-season collapsible rows ──────────────────────────────
        self._clear_season_details()
        self._expanded_seasons.clear()

        all_seasons: list[tuple[int, SeasonCompleteness]] = sorted(report.seasons.items())
        if report.specials and report.specials.expected > 0:
            all_seasons.append((0, report.specials))

        for sn, sc in all_seasons:
            self._build_season_row(sn, sc)

        # ── Rename button style ──────────────────────────────────────
        self._update_rename_button_style()

    def _build_season_row(self, sn: int, sc: SeasonCompleteness):
        """Build a single collapsible season row in the completeness detail area."""
        c = self.c
        frame = ttk.Frame(self.completeness_detail_frame, style="Mid.TFrame")
        frame.pack(fill="x", anchor="w")

        # Header line — clickable if there are missing episodes
        if sn == 0:
            label_text = f"Specials: {sc.matched}/{sc.expected}"
        else:
            label_text = f"S{sn:02d}: {sc.matched}/{sc.expected}"

        if sc.is_complete:
            label_text += " ✓"
            header_fg = c["success"]
        else:
            label_text += f" ({sc.pct:.0f}%)"
            header_fg = c["accent"] if sc.pct >= 50 else c["error"]

        has_missing = len(sc.missing) > 0

        if has_missing:
            label_text = "▸ " + label_text

        header = tk.Label(
            frame, text=label_text, fg=header_fg,
            bg=c["bg_mid"], font=("Helvetica", 9),
            anchor="w", cursor="hand2" if has_missing else "",
        )
        header.pack(fill="x", anchor="w")

        # Body — hidden by default, contains missing episodes
        body = ttk.Frame(frame, style="Mid.TFrame")
        # Don't pack body yet — collapsed by default

        if has_missing:
            for ep_num, title in sc.missing:
                prefix = f"S00E{ep_num:02d}" if sn == 0 else f"E{ep_num:02d}"
                tk.Label(
                    body, text=f"    {prefix} – {title}",
                    fg=c["text_muted"], bg=c["bg_mid"],
                    font=("Helvetica", 8), anchor="w",
                ).pack(fill="x", anchor="w")

            # Click handler to toggle
            def _toggle(event, _sn=sn):
                self._toggle_season_detail(_sn)
            header.bind("<Button-1>", _toggle)

        self._season_detail_widgets[sn] = {
            "frame": frame, "header": header, "body": body,
            "has_missing": has_missing,
        }

    def _toggle_season_detail(self, sn: int):
        """Expand or collapse a season's missing episode list."""
        c = self.c
        widgets = self._season_detail_widgets.get(sn)
        if not widgets or not widgets["has_missing"]:
            return

        header = widgets["header"]
        body = widgets["body"]
        text = header.cget("text")

        if sn in self._expanded_seasons:
            # Collapse
            self._expanded_seasons.discard(sn)
            body.pack_forget()
            header.configure(text=text.replace("▾ ", "▸ ", 1))
        else:
            # Expand
            self._expanded_seasons.add(sn)
            body.pack(fill="x", anchor="w")
            header.configure(text=text.replace("▸ ", "▾ ", 1))

    def _clear_season_details(self):
        """Remove all season detail widgets."""
        for sn, widgets in self._season_detail_widgets.items():
            widgets["frame"].destroy()
        self._season_detail_widgets.clear()

    def _update_rename_button_style(self):
        """Set rename button to green 'Complete' style when series is fully matched."""
        report = self._completeness
        if report and report.is_complete:
            self.btn_rename.configure(
                style="Complete.TButton", text="✓ Rename Files")
        else:
            self.btn_rename.configure(
                style="Accent.TButton", text="Rename Files")

    def _clear_completeness(self):
        """Clear completeness data and widgets (e.g. on mode/show switch)."""
        self._completeness = None
        self.completeness_summary_label.configure(text="")
        self._clear_season_details()
        self._update_rename_button_style()

    # ══════════════════════════════════════════════════════════════════
    #  Canvas interaction
    # ══════════════════════════════════════════════════════════════════

    def _on_canvas_click(self, event):
        cy = self.preview_canvas.canvasy(event.y)
        cx = self.preview_canvas.canvasx(event.x)
        check_zone = int(40 * self.dpi_scale)

        # Check season headers first
        for y_start, y_end, season_num in self._season_header_positions:
            if y_start <= cy <= y_end:
                if cx < check_zone:
                    # Season checkbox — toggle all OK items in this season
                    self._toggle_season_check(season_num)
                else:
                    # Collapse/expand toggle — redraw
                    if season_num in self._collapsed_seasons:
                        self._collapsed_seasons.discard(season_num)
                    else:
                        self._collapsed_seasons.add(season_num)
                    self._display_preview()
                return

        for y_start, y_end, item_idx in self._card_positions:
            if y_start <= cy <= y_end:
                if cx < check_zone:
                    self._toggle_check(item_idx)
                else:
                    self._select_card(item_idx)
                return

    def _toggle_season_check(self, season_num: int):
        """Toggle all OK checkboxes in a season on or off."""
        season_indices = [
            i for i, it in enumerate(self.preview_items)
            if it.season == season_num and it.status == "OK"
        ]
        if not season_indices:
            return

        # If all checked, uncheck all; otherwise check all
        all_checked = all(
            self.check_vars.get(str(i)) is not None and self.check_vars[str(i)].get()
            for i in season_indices
        )
        new_val = not all_checked
        for i in season_indices:
            key = str(i)
            if key in self.check_vars:
                self.check_vars[key].set(new_val)

        # Cancel any pending debounced refresh and update immediately
        # so the season header tally is correct when we redraw
        if self._completeness_after_id:
            self.root.after_cancel(self._completeness_after_id)
            self._completeness_after_id = None
        if self.tv_scanner and self.preview_items:
            checked = self._get_checked_indices()
            self._completeness = self.tv_scanner.get_completeness(
                self.preview_items, checked_indices=checked)

        self._update_tally()
        self._display_preview()
        self._display_completeness()

    def _toggle_check(self, item_idx: int):
        key = str(item_idx)
        var = self.check_vars.get(key)
        if not var:
            return
        var.set(not var.get())

        c = self.c
        cv = self.preview_canvas
        s = self.dpi_scale

        for display_idx, (y_start, y_end, idx) in enumerate(self._card_positions):
            if idx == item_idx:
                check_tag = f"check_{display_idx}"
                cv.delete(check_tag)
                check_char = "☑" if var.get() else "☐"
                check_color = c["accent"] if var.get() else c["border_light"]
                check_x = int(4 * s) + int(4 * s) + int(14 * s)
                check_cy = y_start + (y_end - y_start) // 2
                cv.create_text(
                    check_x, check_cy, text=check_char,
                    fill=check_color, font=("Helvetica", 14), anchor="w",
                    tags=(check_tag, "check", f"item_{idx}"))
                break

    def _select_card(self, item_idx: int):
        c = self.c
        cv = self.preview_canvas

        # Reset only the previously selected card (O(1) instead of O(n))
        prev = self._selected_index
        if prev is not None and prev != item_idx:
            # Determine the correct resting border for the old card
            old_item = self.preview_items[prev]
            if "REVIEW" in old_item.status:
                old_border = c["badge_review_bd"]
            elif old_item.season == 0:
                old_border = c["badge_special_bd"]
            elif len(old_item.episodes) > 1:
                old_border = c["badge_multi_bd"]
            else:
                old_border = c["border"]
            for tag_id in cv.find_withtag(f"item_{prev}"):
                if cv.type(tag_id) == "rectangle" and "card" in cv.gettags(tag_id):
                    cv.itemconfigure(
                        tag_id, outline=old_border, fill=c["bg_card"])

        # Highlight selected
        for tag_id in cv.find_withtag(f"item_{item_idx}"):
            if cv.type(tag_id) == "rectangle" and "card" in cv.gettags(tag_id):
                cv.itemconfigure(
                    tag_id, outline=c["accent"], fill=c["bg_card_selected"])

        self._selected_index = item_idx
        self._show_detail(item_idx)

    # ══════════════════════════════════════════════════════════════════
    #  Detail panel
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _format_rating(vote_avg: float, vote_count: int = 0) -> str:
        """Format a TMDB rating as a star display string."""
        if not vote_avg:
            return ""
        # Convert 0-10 scale to 5-star display
        stars = vote_avg / 2
        full = int(stars)
        half = stars - full >= 0.3
        empty = 5 - full - (1 if half else 0)
        star_str = "★" * full + ("½" if half else "") + "☆" * empty
        count_str = f"  ({vote_count})" if vote_count else ""
        return f"{star_str}  {vote_avg:.1f}/10{count_str}"

    @staticmethod
    def _format_runtime(minutes: int | None) -> str:
        """Format runtime in minutes to a human readable string."""
        if not minutes:
            return ""
        if minutes >= 60:
            h, m = divmod(minutes, 60)
            return f"{h}h {m}m" if m else f"{h}h"
        return f"{minutes}m"

    def _reset_detail(self):
        """Clear the detail panel to its empty state."""
        self.detail_header.configure(text="SELECT AN ITEM")
        self.detail_image.configure(image="")
        self._detail_img_ref = None
        self.detail_ep_title.configure(text="Click a file from the list\nto view its details")
        self.detail_meta_label.configure(text="")
        self.detail_overview.configure(text="")
        self.detail_crew_label.configure(text="")
        self.detail_orig_label.configure(text="")
        self.detail_new_label.configure(text="")
        self.detail_status_label.configure(text="")
        self.rematch_btn.pack_forget()

    def _populate_show_info(self, tmdb: TMDBClient, show_id: int):
        """Populate the show-level info beside the poster."""
        details = tmdb.get_tv_details(show_id)
        if not details:
            self.show_info_label.configure(text="")
            return

        lines = []

        # Rating on its own line (most prominent)
        vote_avg = details.get("vote_average", 0)
        if vote_avg:
            lines.append(self._format_rating(vote_avg, details.get("vote_count", 0)))

        # Genres
        genres = [g["name"] for g in details.get("genres", [])]
        if genres:
            lines.append(" · ".join(genres))

        # Status + network on same line
        status_parts = []
        status = details.get("status", "")
        if status:
            status_parts.append(status)
        networks = [n["name"] for n in details.get("networks", [])]
        if networks:
            status_parts.append(networks[0])
        if status_parts:
            lines.append(" · ".join(status_parts))

        # Seasons/episodes count
        n_seasons = details.get("number_of_seasons")
        n_episodes = details.get("number_of_episodes")
        if n_seasons and n_episodes:
            lines.append(f"{n_seasons} seasons, {n_episodes} eps")

        # Created by
        creators = [c["name"] for c in details.get("created_by", [])]
        if creators:
            lines.append(", ".join(creators))

        self.show_info_label.configure(text="\n".join(lines))

    def _show_detail(self, index: int):
        """Populate the detail panel with rich metadata for the selected item."""
        c = self.c
        item = self.preview_items[index]

        is_multi = len(item.episodes) > 1
        is_special = item.season == 0
        is_movie = item.media_type == MediaType.MOVIE

        # ── Section header ────────────────────────────────────────────
        if is_movie:
            self.detail_header.configure(text="MOVIE DETAILS")
        elif is_special:
            self.detail_header.configure(text="SPECIAL")
        elif is_multi:
            self.detail_header.configure(
                text=f"S{item.season:02d} · EPISODES "
                     + ", ".join(str(e) for e in item.episodes))
        elif item.season is not None and item.episodes:
            self.detail_header.configure(
                text=f"S{item.season:02d}E{item.episodes[0]:02d}")
        else:
            self.detail_header.configure(text="FILE DETAILS")

        # ── Load content-specific image ───────────────────────────────
        self._load_detail_image(item)

        # ── Populate based on media type ──────────────────────────────
        if is_movie:
            self._show_movie_detail(item)
        else:
            self._show_tv_detail(item)

        # ── Rename info card (common to both) ─────────────────────────
        self.detail_orig_label.configure(
            text=f"FROM:  {item.original.name}",
            foreground=c["text_dim"],
        )

        if item.new_name:
            new_text = f"TO:  {item.new_name}"
            if item.is_move():
                new_text += f"\nINTO:  {item.target_dir.name}/"
            self.detail_new_label.configure(text=new_text)
        else:
            self.detail_new_label.configure(text="")

        # Status with color coding
        status = item.status
        if status == "OK":
            self.detail_status_label.configure(
                text="✓ Ready to rename", foreground=c["success"])
        elif "REVIEW" in status:
            self.detail_status_label.configure(
                text=f"⚠ {status}", foreground=c["accent"])
        elif "CONFLICT" in status:
            self.detail_status_label.configure(
                text=f"✗ {status}", foreground=c["error"])
        elif "SKIP" in status:
            self.detail_status_label.configure(
                text=f"— {status}", foreground=c["text_muted"])
        else:
            self.detail_status_label.configure(
                text=status, foreground=c["text_dim"])

        # Re-match button visibility
        if is_movie:
            self.rematch_btn.pack(anchor="w", pady=(8, 0))
        else:
            self.rematch_btn.pack_forget()

    def _show_tv_detail(self, item: PreviewItem):
        """Populate detail panel with TV episode metadata from TMDB."""
        c = self.c
        meta = None

        # Get rich metadata for the first episode
        if self.tv_scanner and item.episodes:
            meta = self.tv_scanner.episode_meta.get(
                (item.season, item.episodes[0]))

        if not meta:
            # Fallback: just show the episode title from basic data
            if self.tv_scanner and item.episodes:
                title = self.tv_scanner.episode_titles.get(
                    (item.season, item.episodes[0]), "")
                self.detail_ep_title.configure(text=title or "Unknown Episode")
            else:
                self.detail_ep_title.configure(text="")
            self.detail_meta_label.configure(text="")
            self.detail_overview.configure(text="")
            self.detail_crew_label.configure(text="")
            return

        # Episode title
        ep_title = meta.get("name", "")
        if item.episodes and len(item.episodes) == 1:
            display_title = ep_title
        elif item.episodes:
            # Multi-episode: show first title
            titles = []
            for ep in item.episodes:
                m = self.tv_scanner.episode_meta.get((item.season, ep))
                if m:
                    titles.append(m.get("name", f"Episode {ep}"))
            display_title = " / ".join(titles) if titles else ep_title
        else:
            display_title = ep_title
        self.detail_ep_title.configure(text=display_title)

        # Metadata row: rating · runtime · air date
        meta_parts = []
        rating = meta.get("vote_average", 0)
        if rating:
            meta_parts.append(self._format_rating(
                rating, meta.get("vote_count", 0)))
        runtime = self._format_runtime(meta.get("runtime"))
        if runtime:
            meta_parts.append(runtime)
        air_date = meta.get("air_date", "")
        if air_date:
            meta_parts.append(air_date)
        self.detail_meta_label.configure(text="   ·   ".join(meta_parts))

        # Overview
        overview = meta.get("overview", "")
        self.detail_overview.configure(
            text=overview if overview else "No synopsis available.")

        # Crew & guest stars
        crew_parts = []
        directors = meta.get("directors", [])
        if directors:
            crew_parts.append(f"Directed by  {', '.join(directors)}")
        writers = meta.get("writers", [])
        if writers:
            crew_parts.append(f"Written by  {', '.join(writers)}")
        guests = meta.get("guest_stars", [])
        if guests:
            guest_strs = []
            for g in guests[:4]:
                name = g.get("name", "")
                char = g.get("character", "")
                if name and char:
                    guest_strs.append(f"{name} as {char}")
                elif name:
                    guest_strs.append(name)
            if guest_strs:
                crew_parts.append(f"Guest stars  {', '.join(guest_strs)}")
        self.detail_crew_label.configure(text="\n".join(crew_parts))

    def _show_movie_detail(self, item: PreviewItem):
        """Populate detail panel with movie metadata from TMDB."""
        c = self.c
        tmdb = self._ensure_tmdb()

        movie_data = (self.movie_scanner.movie_info.get(item.original)
                      if self.movie_scanner else None)

        if not movie_data or not tmdb:
            self.detail_ep_title.configure(text=item.new_name or "")
            self.detail_meta_label.configure(text="")
            self.detail_overview.configure(text="")
            self.detail_crew_label.configure(text="")
            return

        # Fetch full movie details for rich info
        details = tmdb.get_movie_details(movie_data["id"])
        if not details:
            self.detail_ep_title.configure(
                text=f"{movie_data.get('title', '')} ({movie_data.get('year', '')})")
            self.detail_meta_label.configure(text="")
            self.detail_overview.configure(
                text=movie_data.get("overview", ""))
            self.detail_crew_label.configure(text="")
            return

        # Title + tagline
        title = details.get("title", "")
        year = (details.get("release_date") or "")[:4]
        tagline = details.get("tagline", "")
        title_text = f"{title}" + (f" ({year})" if year else "")
        if tagline:
            title_text += f"\n\"{tagline}\""
        self.detail_ep_title.configure(text=title_text)

        # Metadata row: rating · runtime · genres · release date
        meta_parts = []
        vote_avg = details.get("vote_average", 0)
        if vote_avg:
            meta_parts.append(self._format_rating(
                vote_avg, details.get("vote_count", 0)))
        runtime = self._format_runtime(details.get("runtime"))
        if runtime:
            meta_parts.append(runtime)
        release_date = details.get("release_date", "")
        if release_date:
            meta_parts.append(release_date)
        self.detail_meta_label.configure(text="   ·   ".join(meta_parts))

        # Overview
        overview = details.get("overview", "")
        self.detail_overview.configure(
            text=overview if overview else "No synopsis available.")

        # Genres + production info
        info_parts = []
        genres = [g["name"] for g in details.get("genres", [])]
        if genres:
            info_parts.append(" · ".join(genres))
        companies = [c["name"] for c in details.get("production_companies", [])[:3]]
        if companies:
            info_parts.append(", ".join(companies))
        self.detail_crew_label.configure(text="\n".join(info_parts))

    def _load_detail_image(self, item: PreviewItem):
        """Load the appropriate image for the detail panel's episode/movie still."""
        tmdb = self._ensure_tmdb()
        if not tmdb or not self.media_info:
            self.detail_image.configure(image="")
            self._detail_img_ref = None
            return

        img = None
        is_movie = item.media_type == MediaType.MOVIE

        if is_movie and self.movie_scanner:
            movie_data = self.movie_scanner.movie_info.get(item.original)
            if movie_data and movie_data.get("poster_path"):
                img = tmdb.fetch_image(movie_data["poster_path"], target_width=400)
        elif self.tv_scanner and item.episodes:
            poster_path = self.tv_scanner.episode_posters.get(
                (item.season, item.episodes[0]))
            if poster_path:
                img = tmdb.fetch_image(poster_path, target_width=400)

        if img:
            img = self._scale_to_panel(img)
            photo = ImageTk.PhotoImage(img)
            self._detail_img_ref = photo
            self.detail_image.configure(image=photo)
        else:
            self.detail_image.configure(image="")
            self._detail_img_ref = None

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
        chosen = self._pick_media_dialog(
            cached, title_key="title",
            dialog_title=f"Re-match: {item.original.name}",
            allow_skip=True,
            search_callback=tmdb.search_movie,
        )

        if not chosen:
            return

        new_item = self.movie_scanner.rematch_file(item, chosen)
        self.preview_items[self._selected_index] = new_item
        check_duplicates(self.preview_items)
        self._display_preview()
        self._select_card(self._selected_index)

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
            and item.status == "OK" and item.new_name
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

        # Snapshot the items before they get invalidated
        renamed_items = [
            self.preview_items[i] for i in sorted(checked)
        ]

        media_name = (
            self.media_info.get("name")
            or self.media_info.get("title")
            or self.folder.name
        )

        # For TV, compute the proper show folder name so the root can be renamed
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

        # If the root show folder was renamed, update our state to point
        # to the new path so subsequent scans and undos work correctly
        if result.new_root:
            self.folder = result.new_root
            if self.tv_scanner:
                self.tv_scanner.root = result.new_root

        # Invalidate scanner cache since files have moved
        if self.tv_scanner:
            self.tv_scanner.invalidate_cache()

        # Show success state instead of messagebox + re-scan
        # Pre-collapse seasons where all files were successfully renamed
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
        self._show_rename_result(result, renamed_items)

    def _show_rename_result(self, result: RenameResult, renamed_items: list[PreviewItem]):
        """
        Replace the preview canvas with a success/result summary.

        Shows a completion badge, stats, the list of renames performed
        (old → new), any errors, and action buttons for scan-again / undo.
        """
        c = self.c
        cv, canvas_w, s = self._clear_canvas()
        margin_x = int(16 * s)
        x_left = margin_x
        x_right = canvas_w - margin_x
        y = int(20 * s)

        has_errors = len(result.errors) > 0

        # ── Completion badge ─────────────────────────────────────────
        if has_errors:
            badge_text = "⚠  Partially Complete"
            badge_fg = c["accent"]
        else:
            badge_text = "✓  Rename Complete"
            badge_fg = c["success"]

        cv.create_text(
            canvas_w // 2, y,
            text=badge_text, fill=badge_fg,
            font=("Helvetica", 18, "bold"), anchor="n")
        y += int(36 * s)

        # ── Stats line ───────────────────────────────────────────────
        stats_parts = [f"{result.renamed_count} files renamed"]
        move_count = sum(1 for it in renamed_items if it.is_move())
        if move_count:
            stats_parts.append(f"{move_count} moved")
        dir_renames = result.log_entry.get("renamed_dirs", [])
        if dir_renames:
            stats_parts.append(f"{len(dir_renames)} folders renamed")
        removed_dirs = result.log_entry.get("removed_dirs", [])
        if removed_dirs:
            stats_parts.append(f"{len(removed_dirs)} empty folders removed")

        cv.create_text(
            canvas_w // 2, y,
            text="  ·  ".join(stats_parts), fill=c["text_dim"],
            font=("Helvetica", 11), anchor="n")
        y += int(28 * s)

        # ── Action buttons (immediately visible at top) ──────────────
        is_single_movie = (
            self.media_type == MediaType.MOVIE
            and self.movie_scanner
            and self.movie_scanner.explicit_files
            and len(self.movie_scanner.explicit_files) == 1
        )
        show_scan_again = not is_single_movie

        btn_y_top, btn_y_bot, regions = self._draw_action_buttons(
            cv, y, canvas_w, show_undo=True, show_scan=show_scan_again)
        y = btn_y_bot + int(20 * s)

        # ── Errors section (if any) ──────────────────────────────────
        if has_errors:
            cv.create_text(
                x_left, y, text="ERRORS",
                fill=c["error"], font=("Helvetica", 9, "bold"), anchor="nw")
            y += int(18 * s)

            for err in result.errors[:10]:
                cv.create_text(
                    x_left + int(8 * s), y, text=f"  {err}",
                    fill=c["error"], font=("Helvetica", 9), anchor="nw")
                y += int(16 * s)

            y += int(12 * s)

        # ── Folder operations ────────────────────────────────────────
        if dir_renames or removed_dirs:
            cv.create_text(
                x_left, y, text="FOLDER CHANGES",
                fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
            y += int(18 * s)

            for d in dir_renames:
                old_name = Path(d["old"]).name
                new_name = Path(d["new"]).name
                cv.create_text(
                    x_left + int(8 * s), y,
                    text=f"{old_name}  →  {new_name}",
                    fill=c["move"], font=("Helvetica", 9), anchor="nw")
                y += int(16 * s)

            for d in removed_dirs:
                cv.create_text(
                    x_left + int(8 * s), y,
                    text=f"Removed: {Path(d).name}/",
                    fill=c["text_muted"], font=("Helvetica", 9), anchor="nw")
                y += int(16 * s)

            y += int(12 * s)

        # ── Renamed files list (grouped by season, collapsible) ────────
        cv.create_text(
            x_left, y, text="RENAMED FILES",
            fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
        y += int(22 * s)

        self._last_rename_result = result
        self._last_renamed_items = renamed_items

        by_season: dict[int | None, list[PreviewItem]] = defaultdict(list)
        for item in renamed_items:
            by_season[item.season].append(item)

        card_h = int(48 * s)
        pad = int(10 * s)
        bar_w = int(3 * s)
        result_season_positions: list[tuple[int, int, int | None]] = []

        for season_key in sorted(by_season.keys(), key=lambda k: k if k is not None else -1):
            items = by_season[season_key]
            is_collapsed = season_key in self._result_collapsed_seasons

            if season_key is not None and len(by_season) > 1:
                arrow = "\u25b8" if is_collapsed else "\u25be"
                if season_key == 0:
                    hdr_text = f"{arrow}  Specials ({len(items)} files)"
                else:
                    hdr_text = f"{arrow}  Season {season_key} ({len(items)} files)"

                hdr_h = int(24 * s)
                hdr_y = y
                cv.create_rectangle(
                    x_left, y, x_right, y + hdr_h,
                    fill=c["bg_mid"], outline=c["border"])
                cv.create_text(
                    x_left + int(8 * s), y + hdr_h // 2,
                    text=hdr_text, fill=c["text_dim"],
                    font=("Helvetica", 9, "bold"), anchor="w")
                result_season_positions.append((hdr_y, hdr_y + hdr_h, season_key))
                y += hdr_h + int(4 * s)

            if is_collapsed:
                continue

            for item in items:
                text_x = x_left + bar_w + pad + int(22 * s)
                max_text_w = x_right - text_x - pad

                # Line 1: original filename (with wrapping)
                id1 = cv.create_text(
                    text_x, y + pad,
                    text=item.original.name, fill=c["text_muted"],
                    font=("Helvetica", 9), anchor="nw",
                    width=max_text_w)

                new_text = item.new_name or item.original.name
                if item.is_move() and item.target_dir:
                    new_text = f"[{item.target_dir.name}]  {new_text}"

                # Measure line 1 to position line 2
                bbox1 = cv.bbox(id1)
                line1_bottom = (bbox1[3] if bbox1 else y + pad + int(14 * s))

                # Line 2: new name (with wrapping)
                id2 = cv.create_text(
                    text_x, line1_bottom + int(2 * s),
                    text=f"\u2192  {new_text}", fill=c["success"],
                    font=("Helvetica", 10), anchor="nw",
                    width=max_text_w)

                # Compute actual card height from content
                bbox2 = cv.bbox(id2)
                content_bottom = (bbox2[3] if bbox2 else line1_bottom + int(16 * s))
                actual_h = max(card_h, content_bottom - y + pad)

                # Draw card background behind text
                bg_id = cv.create_rectangle(
                    x_left, y, x_right, y + actual_h,
                    fill=c["bg_card"], outline=c["border"])
                cv.tag_lower(bg_id)

                # Accent bar
                bar_id = cv.create_rectangle(
                    x_left, y, x_left + bar_w, y + actual_h,
                    fill=c["success"], outline="")
                cv.tag_raise(bar_id, bg_id)

                # Checkmark
                cv.create_text(
                    x_left + bar_w + pad, y + actual_h // 2,
                    text="\u2713", fill=c["success"],
                    font=("Helvetica", 12, "bold"), anchor="w")

                y += actual_h + int(2 * s)

            y += int(8 * s)

        y += int(10 * s)
        cv.configure(scrollregion=(0, 0, canvas_w, y))

        # Click handler -- buttons + collapsible season headers
        def _on_season_click(cx, cy_click):
            for sy_top, sy_bot, sk in result_season_positions:
                if sy_top <= cy_click <= sy_bot:
                    if sk in self._result_collapsed_seasons:
                        self._result_collapsed_seasons.discard(sk)
                    else:
                        self._result_collapsed_seasons.add(sk)
                    self._show_rename_result(result, renamed_items)
                    return

        self._make_button_click_handler(
            cv, btn_y_top, btn_y_bot, regions, extra_handler=_on_season_click)

        # Update status bar
        if has_errors:
            self.status_var.set(
                f"Renamed {result.renamed_count} files with "
                f"{len(result.errors)} error(s)")
        else:
            self.status_var.set(
                f"✓ Successfully renamed {result.renamed_count} files")

        # Clear detail panel to show completion state
        self._reset_detail()
        self.detail_header.configure(text="RENAME COMPLETE")
        self.detail_ep_title.configure(text="")
        self.detail_overview.configure(text="")

    def _show_already_renamed(self, report: CompletenessReport | None):
        """
        Show an 'already renamed' state when all matched files already
        have their target names.

        Three cases:
        1. Fully complete including specials — nothing to do at all.
        2. Episodes complete but specials missing — note the missing specials.
        3. Some non-special episodes missing — show them.
        """
        c = self.c
        cv, canvas_w, s = self._clear_canvas()
        margin_x = int(16 * s)
        x_left = margin_x
        y = int(30 * s)

        episodes_complete = report and report.is_complete
        sp = report.specials if report else None
        specials_complete = sp and sp.expected > 0 and sp.is_complete
        specials_missing = sp and sp.expected > 0 and not sp.is_complete
        fully_complete = episodes_complete and (specials_complete or not sp or sp.expected == 0)

        # ── Badge ────────────────────────────────────────────────────
        if fully_complete:
            badge_text = "✓  Fully Complete"
            badge_fg = c["success"]
            sub_text = "All episodes and specials are present and correctly named."
        elif episodes_complete and specials_missing:
            badge_text = "✓  Episodes Complete"
            badge_fg = c["success"]
            sub_text = "All episodes are properly named. Some specials are missing."
        elif episodes_complete:
            badge_text = "✓  Already Properly Named"
            badge_fg = c["success"]
            sub_text = "All episodes are present and correctly named. No action needed."
        else:
            badge_text = "✓  Matched Files Already Named"
            badge_fg = c["accent"]
            sub_text = "All matched files already have their correct names."

        cv.create_text(
            canvas_w // 2, y,
            text=badge_text, fill=badge_fg,
            font=("Helvetica", 18, "bold"), anchor="n")
        y += int(34 * s)

        cv.create_text(
            canvas_w // 2, y,
            text=sub_text, fill=c["text_dim"],
            font=("Helvetica", 11), anchor="n")
        y += int(30 * s)

        # ── Completeness summary ─────────────────────────────────────
        if report and report.total_expected > 0:
            if episodes_complete:
                summary = (f"{report.total_matched}/{report.total_expected} "
                           f"episodes — complete")
                summary_fg = c["success"]
            else:
                summary = (f"{report.total_matched}/{report.total_expected} "
                           f"episodes matched ({report.pct:.0f}%)")
                summary_fg = c["accent"]

            cv.create_text(
                canvas_w // 2, y,
                text=summary, fill=summary_fg,
                font=("Helvetica", 12, "bold"), anchor="n")
            y += int(30 * s)

        # ── Action buttons ───────────────────────────────────────────
        has_undo = bool(load_log())

        btn_y_top, btn_y_bot, regions = self._draw_action_buttons(
            cv, y, canvas_w, show_undo=has_undo, show_scan=True)
        y = btn_y_bot + int(20 * s)

        # ── Missing episodes (if not complete) ───────────────────────
        if report and not episodes_complete and report.total_missing:
            cv.create_text(
                x_left, y, text="MISSING EPISODES",
                fill=c["error"], font=("Helvetica", 9, "bold"), anchor="nw")
            y += int(20 * s)

            for sn, ep_num, title in report.total_missing:
                cv.create_text(
                    x_left + int(8 * s), y,
                    text=f"S{sn:02d}E{ep_num:02d} – {title}",
                    fill=c["text_dim"], font=("Helvetica", 10), anchor="nw")
                y += int(18 * s)

            y += int(12 * s)

        # ── Missing specials (itemized) ──────────────────────────────
        if specials_missing and sp.missing:
            cv.create_text(
                x_left, y, text="MISSING SPECIALS",
                fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
            y += int(20 * s)

            for ep_num, title in sp.missing:
                cv.create_text(
                    x_left + int(8 * s), y,
                    text=f"S00E{ep_num:02d} – {title}",
                    fill=c["text_muted"], font=("Helvetica", 10), anchor="nw")
                y += int(18 * s)

            y += int(12 * s)

        # ── Specials tally (if present and complete) ─────────────────
        if specials_complete:
            cv.create_text(
                x_left, y,
                text=f"Specials: {sp.matched}/{sp.expected} ✓",
                fill=c["success"], font=("Helvetica", 10), anchor="nw")
            y += int(24 * s)

        y += int(10 * s)
        cv.configure(scrollregion=(0, 0, canvas_w, y))

        self._make_button_click_handler(cv, btn_y_top, btn_y_bot, regions)

        if fully_complete:
            self.status_var.set("✓ Series fully complete — no action needed")
        elif episodes_complete and specials_missing:
            self.status_var.set(
                f"✓ Episodes complete — {len(sp.missing)} specials missing")
        elif episodes_complete:
            self.status_var.set("✓ Series is properly named — no action needed")
        else:
            self.status_var.set(
                f"Matched files already named — "
                f"{len(report.total_missing)} episodes missing"
                if report else "Matched files already named")

    def _show_already_renamed_movies(self, ok_items: list[PreviewItem]):
        """
        Show an 'already renamed' state for movie mode when all matched
        files already have their target names and are in the right folders.
        """
        c = self.c
        cv, canvas_w, s = self._clear_canvas()
        margin_x = int(16 * s)
        x_left = margin_x
        y = int(30 * s)

        count = len(ok_items)
        badge_text = "✓  Already Properly Named"
        badge_fg = c["success"]
        if count == 1:
            sub_text = "This movie is already correctly named. No action needed."
        else:
            sub_text = f"All {count} movies are already correctly named. No action needed."

        cv.create_text(
            canvas_w // 2, y,
            text=badge_text, fill=badge_fg,
            font=("Helvetica", 18, "bold"), anchor="n")
        y += int(34 * s)

        cv.create_text(
            canvas_w // 2, y,
            text=sub_text, fill=c["text_dim"],
            font=("Helvetica", 11), anchor="n")
        y += int(30 * s)

        # ── Undo button (only if undo history exists) ────────────────
        has_undo = bool(load_log())

        if has_undo:
            btn_y_top, btn_y_bot, regions = self._draw_action_buttons(
                cv, y, canvas_w, show_undo=True, show_scan=False)
            y = btn_y_bot + int(20 * s)
        else:
            btn_y_top = btn_y_bot = y
            regions = {}

        # ── List the properly named files ────────────────────────────
        cv.create_text(
            x_left, y, text="PROPERLY NAMED FILES",
            fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
        y += int(20 * s)

        for item in ok_items:
            cv.create_text(
                x_left + int(8 * s), y,
                text=f"✓  {item.original.name}",
                fill=c["success"], font=("Helvetica", 10), anchor="nw")
            y += int(18 * s)

        y += int(10 * s)
        cv.configure(scrollregion=(0, 0, canvas_w, y))

        self._make_button_click_handler(cv, btn_y_top, btn_y_bot, regions)

        self.status_var.set("✓ Movies already properly named — no action needed")

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

        # If the root show folder was renamed as part of this batch,
        # revert self.folder to the original path
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
        self._reset_detail()
        if self.tv_scanner:
            self.tv_scanner.invalidate_cache()
        if self.movie_scanner:
            # Recreate movie scanner so it rescans fresh files
            tmdb = self._ensure_tmdb()
            if tmdb:
                files = self.movie_scanner.explicit_files
                self.movie_scanner = MovieScanner(tmdb, self.folder, files=files)
        if self.folder and self.media_info:
            self.run_preview()

    # ══════════════════════════════════════════════════════════════════
    #  Search / selection
    # ══════════════════════════════════════════════════════════════════

    def _update_search(self):
        query = self.search_var.get().lower()
        if not self._card_positions:
            return

        for y_start, y_end, item_idx in self._card_positions:
            item = self.preview_items[item_idx]
            text = (item.original.name + " " + (item.new_name or "")).lower()
            tag = f"item_{item_idx}"
            state = "normal" if (not query or query in text) else "hidden"
            for cid in self.preview_canvas.find_withtag(tag):
                self.preview_canvas.itemconfigure(cid, state=state)

    def _select_all(self):
        selectable = [
            str(i) for i, item in enumerate(self.preview_items)
            if item.status == "OK"
        ]
        if not selectable:
            return

        all_checked = all(
            self.check_vars[k].get()
            for k in selectable
            if k in self.check_vars
        )
        new_val = not all_checked
        for k in selectable:
            if k in self.check_vars:
                self.check_vars[k].set(new_val)
        self._update_tally()

    def _update_tally(self):
        total = sum(1 for it in self.preview_items if it.status == "OK")
        selected = sum(
            1 for i, item in enumerate(self.preview_items)
            if item.status == "OK"
            and self.check_vars.get(str(i)) is not None
            and self.check_vars[str(i)].get()
        )
        self.tally_var.set(f"{selected} / {total}")

    def _get_checked_indices(self) -> set[int]:
        """Return the set of item indices whose checkboxes are checked."""
        return {
            i for i in range(len(self.preview_items))
            if self.check_vars.get(str(i)) is not None
            and self.check_vars[str(i)].get()
        }

    def _on_check_changed(self):
        """Called when any checkbox changes — updates tally and schedules completeness refresh."""
        self._update_tally()
        # Debounce completeness refresh to avoid N recalculations during select-all
        if self._completeness_after_id:
            self.root.after_cancel(self._completeness_after_id)
        self._completeness_after_id = self.root.after(50, self._refresh_completeness)

    def _refresh_completeness(self):
        """Recalculate and redisplay completeness based on current checkbox state."""
        self._completeness_after_id = None
        if self.tv_scanner and self.preview_items:
            checked = self._get_checked_indices()
            self._completeness = self.tv_scanner.get_completeness(
                self.preview_items, checked_indices=checked)
            self._display_completeness()

    # ══════════════════════════════════════════════════════════════════
    #  Run
    # ══════════════════════════════════════════════════════════════════

    def run(self):
        """Start the tkinter main loop."""
        self.root.mainloop()
