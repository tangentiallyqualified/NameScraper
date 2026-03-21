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
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .constants import MediaType, VIDEO_EXTENSIONS
from .engine import (
    MovieScanner,
    PreviewItem,
    TVScanner,
    _CANCEL_SCAN,
    check_duplicates,
    execute_rename,
    execute_undo,
)
from .keys import get_api_key, save_api_key
from .parsing import clean_folder_name
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
        self._display_order: list[int] = []
        self._resize_after_id = None
        self._last_canvas_width: int = 0

        # ── Theme + layout ────────────────────────────────────────────
        self._check_imgs = setup_styles(self.root, self.dpi_scale)
        self._build_layout()

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
        action_bar.columnconfigure(3, weight=1)

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

        # Episode order (TV only)
        self.order_frame = ttk.Frame(action_bar)
        self.order_frame.grid(row=0, column=2, padx=(0, 8), sticky="w")
        ttk.Label(self.order_frame, text="Order:", foreground=c["text_dim"]).pack(
            side="left", padx=(0, 4))
        self.order_var = tk.StringVar(value="aired")
        ttk.Combobox(
            self.order_frame, textvariable=self.order_var,
            values=["aired", "dvd", "absolute"], width=9, state="readonly",
        ).pack(side="left")

        # Filter
        search_frame = ttk.Frame(action_bar)
        search_frame.grid(row=0, column=3, sticky="ew", padx=(0, 8))
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
        btn_frame.grid(row=1, column=3, sticky="e", pady=(8, 0))

        ttk.Button(
            btn_frame, text="Refresh", command=self.run_preview,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            btn_frame, text="Rename Files", command=self._execute_rename,
            style="Accent.TButton",
        ).pack(side="left")

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
        def _on_canvas_resize(event):
            if abs(event.width - self._last_canvas_width) < 10:
                return  # Width didn't meaningfully change
            self._last_canvas_width = event.width
            if self._resize_after_id:
                self.root.after_cancel(self._resize_after_id)
            self._resize_after_id = self.root.after(
                100, self._display_preview if self._card_positions else lambda: None,
            )
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

        # Detail content
        pad = ttk.Frame(self.detail_inner, style="Mid.TFrame")
        pad.pack(fill="both", expand=True, padx=16, pady=16)

        self.poster_label = ttk.Label(pad, style="Detail.TLabel", background=c["bg_mid"])
        self.poster_label.pack(anchor="center", fill="x", pady=(0, 12))

        ttk.Separator(pad, orient="horizontal").pack(fill="x", pady=8)

        # Detail header
        self.detail_header = ttk.Label(
            pad, text="SELECT AN ITEM",
            style="DetailDim.TLabel", font=("Helvetica", 9, "bold"),
        )
        self.detail_header.pack(anchor="w", fill="x", pady=(8, 6))

        self.detail_label = ttk.Label(
            pad, text="Click a file from the list\nto view its details",
            style="Detail.TLabel", wraplength=260, justify="left",
        )
        self.detail_label.pack(anchor="w", fill="x")

        self.detail_image = ttk.Label(pad, style="Detail.TLabel", background=c["bg_mid"])
        self.detail_image.pack(anchor="center", fill="x", pady=(12, 0))

        # Re-match button (movies only)
        self.rematch_btn = ttk.Button(
            pad, text="Re-match on TMDB",
            command=self._rematch_selected_movie,
        )

        def _on_detail_resize(event):
            available = event.width - 40
            if available > 100:
                self.detail_label.configure(wraplength=available)
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
        """Bind mousewheel scrolling for a canvas (cross-platform)."""
        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _scroll)
        canvas.bind_all(
            "<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
        canvas.bind_all(
            "<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

    def _setup_detail_mousewheel(self, detail_canvas: tk.Canvas):
        """Manage mousewheel focus between preview and detail canvases."""
        def _detail_scroll(event):
            detail_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _preview_scroll(event):
            self.preview_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        detail_canvas.bind("<Enter>", lambda e: (
            detail_canvas.bind_all("<MouseWheel>", _detail_scroll),
            detail_canvas.bind_all("<Button-4>",
                lambda ev: detail_canvas.yview_scroll(-3, "units")),
            detail_canvas.bind_all("<Button-5>",
                lambda ev: detail_canvas.yview_scroll(3, "units")),
        ))
        detail_canvas.bind("<Leave>", lambda e: (
            self.preview_canvas.bind_all("<MouseWheel>", _preview_scroll),
            self.preview_canvas.bind_all("<Button-4>",
                lambda ev: self.preview_canvas.yview_scroll(-3, "units")),
            self.preview_canvas.bind_all("<Button-5>",
                lambda ev: self.preview_canvas.yview_scroll(3, "units")),
        ))

    # ══════════════════════════════════════════════════════════════════
    #  TMDB Client management
    # ══════════════════════════════════════════════════════════════════

    def _ensure_tmdb(self) -> TMDBClient | None:
        """
        Get or create the shared TMDB client.

        Reuses the existing client/session instead of creating a new one
        for every operation (fixes the redundant session creation issue).
        """
        api_key = get_api_key("TMDB")
        if not api_key:
            messagebox.showwarning(
                "No Key", "Set your TMDB API key first via 'API Keys'.")
            return None
        if self.tmdb is None or self.tmdb.api_key != api_key:
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

    # ══════════════════════════════════════════════════════════════════
    #  Event handlers
    # ══════════════════════════════════════════════════════════════════

    def _on_type_change(self, event=None):
        """Handle media type combobox change — swap buttons and controls."""
        val = self.type_var.get()
        if val == "TV Series":
            self.media_type = MediaType.TV
            self.order_frame.grid()
            self.btn_select_movie_folder.pack_forget()
            self.btn_select_movie_files.pack_forget()
            self.btn_select_folder.pack(side="left")
        else:
            self.media_type = MediaType.MOVIE
            self.order_frame.grid_remove()
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

        chosen = self._pick_media_dialog(
            results, title_key="name", dialog_title="Select Show",
            search_callback=tmdb.search_tv,
        )
        if not chosen:
            return

        self.media_info = chosen
        self.tv_scanner = TVScanner(tmdb, chosen, self.folder)
        self.movie_scanner = None

        self._display_poster(tmdb, chosen["id"], "tv")
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

        self.poster_label.configure(image="", text="")
        self._poster_ref = None

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

        self.preview_items = self.movie_scanner.scan(
            pick_movie_callback=self._pick_movie_for_file,
        )

        check_duplicates(self.preview_items)
        self._display_preview()

        ok_items = [it for it in self.preview_items if it.status == "OK"]
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
        if img:
            img = self._scale_to_panel(img)
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
            self._display_preview()

        elif self.media_type == MediaType.MOVIE and self.movie_scanner:
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
            self._display_preview()

            ok_items = [it for it in self.preview_items if it.status == "OK"]
            if len(ok_items) == 1:
                idx = self.preview_items.index(ok_items[0])
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
        self._card_positions = []
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

        # Sort order
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
            var.trace_add("write", lambda *_: self._update_tally())
            self.check_vars[key] = var

        # Font metrics
        font_orig = tkfont.Font(family="Helvetica", size=11)
        font_new = tkfont.Font(family="Helvetica", size=10)
        font_badge = tkfont.Font(family="Helvetica", size=8, weight="bold")
        font_check = tkfont.Font(family="Helvetica", size=14)

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

        y = margin_y

        for display_idx, item_idx in enumerate(self._display_order):
            item = self.preview_items[item_idx]
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

            # Row height
            badge_row_h = (badge_h + gap) if has_badges else 0
            has_line2 = bool(arrow_text)
            content_h = (pad_y + badge_row_h + line1_h
                         + (gap + line2_h if has_line2 else 0) + pad_y)
            row_h = max(int(44 * s), content_h)

            y_start = y
            x_left = margin_x
            x_right = canvas_w - margin_x

            # Card background
            is_selected = (self._selected_index == item_idx)
            card_bg = c["bg_card_selected"] if is_selected else c["bg_card"]
            card_outline = c["accent"] if is_selected else border_color

            cv.create_rectangle(
                x_left, y, x_right, y + row_h,
                fill=card_bg, outline=card_outline,
                tags=("card", tag))

            # Accent bar
            bar_color = None
            if has_review:
                bar_color = c["badge_review_bd"]
            elif is_special:
                bar_color = c["badge_special_bd"]
            elif is_multi:
                bar_color = c["badge_multi_bd"]
            elif is_movie:
                bar_color = c["badge_movie_bd"]

            if bar_color:
                cv.create_rectangle(
                    x_left, y, x_left + bar_w, y + row_h,
                    fill=bar_color, outline="", tags=(tag,))

            # Checkbox
            check_var = self.check_vars[str(item_idx)]
            check_x = x_left + bar_w + pad_x
            check_cy = y + row_h // 2
            check_char = "☑" if check_var.get() else "☐"
            check_color = c["accent"] if check_var.get() else c["border_light"]
            cv.create_text(
                check_x, check_cy, text=check_char,
                fill=check_color, font=font_check_t, anchor="w",
                tags=(f"check_{display_idx}", "check", tag))

            text_x = check_x + check_w
            text_y = y + pad_y

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

            # Line 1: original filename
            cv.create_text(
                text_x, text_y, text=orig_text,
                fill=name_fg, font=font_orig_t, anchor="nw",
                tags=("text", tag))
            text_y += line1_h

            # Line 2: arrow + new name
            if arrow_text:
                text_y += gap
                cv.create_text(
                    text_x + 4, text_y, text=arrow_text,
                    fill=arrow_fg, font=font_new_t, anchor="nw",
                    tags=("text", tag))

            self._card_positions.append((y_start, y_start + row_h, item_idx))
            y += row_h + margin_y

        cv.configure(scrollregion=(0, 0, canvas_w, y + 10))
        cv.bind("<Button-1>", self._on_canvas_click)

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

    # ══════════════════════════════════════════════════════════════════
    #  Canvas interaction
    # ══════════════════════════════════════════════════════════════════

    def _on_canvas_click(self, event):
        cy = self.preview_canvas.canvasy(event.y)
        cx = self.preview_canvas.canvasx(event.x)
        check_zone = int(55 * self.dpi_scale)

        for y_start, y_end, item_idx in self._card_positions:
            if y_start <= cy <= y_end:
                if cx < check_zone:
                    self._toggle_check(item_idx)
                else:
                    self._select_card(item_idx)
                return

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

        # Reset all card outlines
        for tag_id in cv.find_withtag("card"):
            cv.itemconfigure(tag_id, outline=c["border"], fill=c["bg_card"])

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

    def _show_detail(self, index: int):
        c = self.c
        item = self.preview_items[index]

        is_multi = len(item.episodes) > 1
        is_special = item.season == 0
        is_movie = item.media_type == MediaType.MOVIE

        # Header
        if is_movie:
            self.detail_header.configure(text="MOVIE DETAILS")
        elif is_special:
            self.detail_header.configure(text="SPECIAL DETAILS")
        elif is_multi:
            self.detail_header.configure(text="MULTI-EPISODE DETAILS")
        else:
            self.detail_header.configure(text="FILE DETAILS")

        # Build detail text
        lines = []

        type_tags = []
        if is_movie:
            type_tags.append("MOVIE")
        if is_multi:
            type_tags.append(f"MULTI-EPISODE ({len(item.episodes)} parts)")
        if is_special:
            type_tags.append("SPECIAL")
        if type_tags:
            lines.append(" · ".join(type_tags) + "\n")

        lines.append(f"Original\n{item.original.name}\n")
        if item.new_name:
            lines.append(f"New Name\n{item.new_name}\n")

        if not is_movie and item.season is not None:
            season_label = "Specials" if item.season == 0 else f"Season {item.season}"
            ep_str = (", ".join(str(e) for e in item.episodes)
                      if item.episodes else "—")
            lines.append(f"{season_label}  ·  "
                         f"Episode{'s' if is_multi else ''} {ep_str}\n")

        status_text = item.status
        if item.is_move():
            status_text += f"\nMoving to {item.target_dir.name}"
        lines.append(status_text)

        self.detail_label.configure(text="\n".join(lines))

        # Re-match button visibility
        if is_movie:
            self.rematch_btn.pack(anchor="w", pady=(12, 0))
        else:
            self.rematch_btn.pack_forget()

        # Load image (uses shared tmdb client — no new sessions)
        self._load_detail_image(item)

    def _load_detail_image(self, item: PreviewItem):
        """Load the appropriate image for the detail panel."""
        tmdb = self._ensure_tmdb()
        if not tmdb or not self.media_info:
            self.detail_image.configure(image="")
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
            # Replace the single reference — no unbounded list growth
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
            if self.check_vars.get(str(i), tk.BooleanVar(value=False)).get()
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

        media_name = (
            self.media_info.get("name")
            or self.media_info.get("title")
            or self.folder.name
        )

        result = execute_rename(self.preview_items, checked, media_name, self.folder)

        if result.errors:
            messagebox.showwarning(
                "Partial Rename",
                f"Renamed {result.renamed_count} files.\n\n"
                f"Errors ({len(result.errors)}):\n"
                + "\n".join(result.errors[:5]))
        else:
            result_msg = f"Successfully renamed {result.renamed_count} files."
            if result.log_entry.get("renamed_dirs"):
                renamed = [
                    f"{Path(d['old']).name} → {Path(d['new']).name}"
                    for d in result.log_entry["renamed_dirs"]
                ]
                result_msg += f"\n\nRenamed folders:\n" + "\n".join(renamed)
            if result.log_entry.get("removed_dirs"):
                removed = [Path(d).name for d in result.log_entry["removed_dirs"]]
                result_msg += f"\n\nRemoved empty folders: {', '.join(removed)}"
            messagebox.showinfo("Done", result_msg)

        self.status_var.set(f"Renamed {result.renamed_count} files.")

        # Invalidate scanner cache since files have moved
        if self.tv_scanner:
            self.tv_scanner.invalidate_cache()
        self.run_preview()

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

        if errors:
            messagebox.showwarning("Partial Undo",
                                   f"Errors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Undone", "Rename successfully undone.")

        self.status_var.set("Undo complete.")
        if self.tv_scanner:
            self.tv_scanner.invalidate_cache()
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
            self.check_vars.get(k, tk.BooleanVar(value=False)).get()
            for k in selectable
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
            and self.check_vars.get(str(i), tk.BooleanVar(value=False)).get()
        )
        self.tally_var.set(f"{selected} / {total}")

    # ══════════════════════════════════════════════════════════════════
    #  Run
    # ══════════════════════════════════════════════════════════════════

    def run(self):
        """Start the tkinter main loop."""
        self.root.mainloop()
