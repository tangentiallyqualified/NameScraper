"""
Tkinter GUI for Plex Renamer.

This is a thin presentation layer.  All business logic (scanning, renaming,
undo, TMDB interaction) lives in the engine module.  The GUI's job is:
  - Collect user input (folder, show/movie selection, checkboxes)
  - Display preview items from the engine
  - Forward rename/undo commands to the engine
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .constants import MediaType
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
    """

    def __init__(self):
        # Windows DPI awareness (must be set BEFORE creating Tk)
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

        self.root = tk.Tk()
        self.root.title("Plex Renamer")

        # Window sizing
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = int(screen_w * 0.92)
        win_h = int(screen_h * 0.85)
        x = (screen_w - win_w) // 2
        y = 10
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(760, 500)

        try:
            self.dpi_scale = self.root.tk.call("tk", "scaling")
            if self.dpi_scale < 1.0:
                self.dpi_scale = 1.0
        except Exception:
            self.dpi_scale = 1.0

        # ── State ─────────────────────────────────────────────────────
        self.folder: Path | None = None
        self.media_type: str = MediaType.TV
        self.media_info: dict | None = None
        self.preview_items: list[PreviewItem] = []
        self.tv_scanner: TVScanner | None = None
        self.movie_scanner: MovieScanner | None = None

        self._image_refs: list = []
        self._poster_ref = None
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self._selected_index: int | None = None

        # ── Theme ─────────────────────────────────────────────────────
        self.colors = {
            "bg_dark":          "#0f0f0f",
            "bg_mid":           "#1a1a1a",
            "bg_card":          "#222222",
            "bg_card_hover":    "#2a2a2a",
            "bg_input":         "#2c2c2c",
            "border":           "#333333",
            "border_light":     "#444444",
            "text":             "#e8e8e8",
            "text_dim":         "#888888",
            "text_muted":       "#555555",
            "accent":           "#e5a00d",
            "accent_hover":     "#f0b429",
            "accent_dim":       "#7a5a10",
            "success":          "#3ea463",
            "error":            "#d44040",
            "info":             "#4a9eda",
            "move":             "#6c8ebf",
            "badge_multi_bg":   "#2d1f4e",
            "badge_multi_fg":   "#b48efa",
            "badge_multi_bd":   "#4a3370",
            "badge_special_bg": "#1a3a2a",
            "badge_special_fg": "#5ec4a0",
            "badge_special_bd": "#2a5e45",
        }

        self._setup_styles()
        self._build_layout()

    # ══════════════════════════════════════════════════════════════════
    #  Styles
    # ══════════════════════════════════════════════════════════════════

    def _setup_styles(self):
        c = self.colors
        self.root.configure(bg=c["bg_dark"])
        self.root.option_add("*Font", "Helvetica 11")

        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=c["bg_dark"], foreground=c["text"],
                         fieldbackground=c["bg_input"], bordercolor=c["border"],
                         insertcolor=c["text"], selectbackground=c["accent_dim"],
                         selectforeground=c["text"])

        style.configure("TFrame", background=c["bg_dark"])
        style.configure("Card.TFrame", background=c["bg_card"])
        style.configure("Mid.TFrame", background=c["bg_mid"])

        style.configure("TLabel", background=c["bg_dark"], foreground=c["text"],
                         font=("Helvetica", 11))
        style.configure("Title.TLabel", font=("Helvetica", 20, "bold"),
                         foreground=c["accent"])
        style.configure("Subtitle.TLabel", font=("Helvetica", 11),
                         foreground=c["text_dim"])
        style.configure("Card.TLabel", background=c["bg_card"], foreground=c["text"])
        style.configure("CardDim.TLabel", background=c["bg_card"],
                         foreground=c["text_dim"], font=("Helvetica", 10))
        style.configure("Detail.TLabel", background=c["bg_mid"], foreground=c["text"])
        style.configure("DetailDim.TLabel", background=c["bg_mid"],
                         foreground=c["text_dim"], font=("Helvetica", 10))
        style.configure("Status.TLabel", background=c["bg_mid"],
                         foreground=c["text_dim"], font=("Helvetica", 10),
                         padding=(12, 6))

        # Buttons
        style.configure("Accent.TButton", font=("Helvetica", 11, "bold"),
                         background=c["accent"], foreground=c["bg_dark"],
                         padding=(16, 8), borderwidth=0)
        style.map("Accent.TButton",
                   background=[("active", c["accent_hover"]),
                               ("disabled", c["border"])])

        style.configure("TButton", font=("Helvetica", 11),
                         background=c["bg_card"], foreground=c["text"],
                         padding=(14, 8), borderwidth=1)
        style.map("TButton",
                   background=[("active", c["border_light"]),
                               ("disabled", c["bg_mid"])])

        style.configure("Small.TButton", font=("Helvetica", 10), padding=(10, 5))

        # Entry / Combobox
        style.configure("TEntry", padding=(8, 6), font=("Helvetica", 11))
        style.configure("TCombobox", padding=(8, 6),
                         fieldbackground=c["bg_input"], background=c["bg_card"],
                         foreground=c["text"], arrowcolor=c["text_dim"])
        style.map("TCombobox",
                   fieldbackground=[("readonly", c["bg_input"]),
                                     ("readonly focus", c["bg_input"])],
                   foreground=[("readonly", c["text"])],
                   selectbackground=[("readonly", c["accent_dim"])],
                   selectforeground=[("readonly", c["text"])])

        self.root.option_add("*TCombobox*Listbox.background", c["bg_input"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["bg_dark"])
        self.root.option_add("*TCombobox*Listbox.font", "Helvetica 11")
        self.root.option_add("*TCombobox*Listbox.borderWidth", "0")
        self.root.option_add("*TCombobox*Listbox.highlightThickness", "0")

        # Checkbutton with custom images
        check_size = max(20, int(18 * self.dpi_scale))
        self._check_imgs = self._create_checkbox_images(c, size=check_size)
        style.element_create("custom_check", "image", self._check_imgs["unchecked"],
                              ("selected", self._check_imgs["checked"]), sticky="w")
        style.layout("Card.TCheckbutton", [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("custom_check", {"side": "left", "sticky": ""}),
                ("Checkbutton.label", {"side": "left", "sticky": "nswe"})
            ]})
        ])
        style.configure("Card.TCheckbutton", background=c["bg_card"],
                         foreground=c["text"])
        style.map("Card.TCheckbutton",
                   background=[("active", c["bg_card_hover"])])

        # Scrollbar
        sb_width = max(14, int(12 * self.dpi_scale))
        style.configure("TScrollbar", background=c["bg_mid"],
                         troughcolor=c["bg_dark"], borderwidth=0,
                         arrowcolor=c["text_dim"], width=sb_width, arrowsize=sb_width)

        style.configure("TSeparator", background=c["border"])

    # ══════════════════════════════════════════════════════════════════
    #  Layout
    # ══════════════════════════════════════════════════════════════════

    def _build_layout(self):
        c = self.colors

        # ── Header bar ────────────────────────────────────────────────
        header = ttk.Frame(self.root, style="Mid.TFrame")
        header.pack(fill="x")

        header_inner = ttk.Frame(header, style="Mid.TFrame")
        header_inner.pack(fill="x", padx=20, pady=(16, 12))

        title_area = ttk.Frame(header_inner, style="Mid.TFrame")
        title_area.pack(side="left")

        ttk.Label(title_area, text="PLEX RENAMER", style="Title.TLabel",
                  background=c["bg_mid"]).pack(anchor="w")

        self.media_label_var = tk.StringVar(value="No media selected")
        ttk.Label(title_area, textvariable=self.media_label_var,
                  style="Subtitle.TLabel",
                  background=c["bg_mid"]).pack(anchor="w", pady=(2, 0))

        btn_area = ttk.Frame(header_inner, style="Mid.TFrame")
        btn_area.pack(side="right")

        ttk.Button(btn_area, text="API Keys", command=self.manage_keys,
                   style="Small.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(btn_area, text="Undo Last", command=self.undo,
                   style="Small.TButton").pack(side="left", padx=(0, 8))

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

        # ── Action bar ────────────────────────────────────────────────
        action_bar = ttk.Frame(self.root)
        action_bar.pack(fill="x", padx=20, pady=(10, 6))
        action_bar.columnconfigure(3, weight=1)

        # Select button area — swaps between folder-only (TV) and
        # folder + file picker (Movies) based on media type.
        self.select_btn_frame = ttk.Frame(action_bar)
        self.select_btn_frame.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.btn_select_folder = ttk.Button(
            self.select_btn_frame, text="Select Show Folder",
            command=self.pick_folder, style="TButton")
        self.btn_select_folder.pack(side="left")

        # Movie-mode buttons (hidden initially)
        self.btn_select_movie_folder = ttk.Button(
            self.select_btn_frame, text="Select Folder",
            command=self.pick_folder, style="TButton")
        self.btn_select_movie_files = ttk.Button(
            self.select_btn_frame, text="Select File(s)",
            command=self.pick_files, style="TButton")

        # Media type selector
        type_frame = ttk.Frame(action_bar)
        type_frame.grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(type_frame, text="Type:",
                  foreground=c["text_dim"]).pack(side="left", padx=(0, 4))
        self.type_var = tk.StringVar(value="TV Series")
        type_combo = ttk.Combobox(type_frame, textvariable=self.type_var,
                                   values=["TV Series", "Movie"],
                                   width=10, state="readonly")
        type_combo.pack(side="left")
        type_combo.bind("<<ComboboxSelected>>", self._on_type_change)

        # Episode order (TV only)
        self.order_frame = ttk.Frame(action_bar)
        self.order_frame.grid(row=0, column=2, padx=(0, 8), sticky="w")
        ttk.Label(self.order_frame, text="Order:",
                  foreground=c["text_dim"]).pack(side="left", padx=(0, 4))
        self.order_var = tk.StringVar(value="aired")
        ttk.Combobox(self.order_frame, textvariable=self.order_var,
                      values=["aired", "dvd", "absolute"],
                      width=9, state="readonly").pack(side="left")

        # Filter
        search_frame = ttk.Frame(action_bar)
        search_frame.grid(row=0, column=3, sticky="ew", padx=(0, 8))
        ttk.Label(search_frame, text="Filter:",
                  foreground=c["text_dim"]).pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: self.update_search())

        # Row 1: selection controls + action buttons
        sel_frame = ttk.Frame(action_bar)
        sel_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.tally_var = tk.StringVar(value="0 / 0")
        ttk.Label(sel_frame, textvariable=self.tally_var,
                  foreground=c["accent"],
                  font=("Helvetica", 11, "bold")).pack(side="left", padx=(0, 4))
        ttk.Label(sel_frame, text="selected", foreground=c["text_dim"],
                  font=("Helvetica", 10)).pack(side="left", padx=(0, 10))
        ttk.Button(sel_frame, text="Select All", command=self.select_all,
                   style="Small.TButton").pack(side="left")

        btn_frame = ttk.Frame(action_bar)
        btn_frame.grid(row=1, column=3, sticky="e", pady=(8, 0))

        ttk.Button(btn_frame, text="Refresh",
                   command=lambda: self.run_preview(),
                   style="TButton").pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="Rename Files",
                   command=self.execute_rename,
                   style="Accent.TButton").pack(side="left")

        # ── Main content (preview list + detail panel) ────────────────
        content = ttk.Frame(self.root)
        content.pack(fill="both", expand=True, padx=20)
        content.columnconfigure(0, weight=3, minsize=350)
        content.columnconfigure(1, weight=1, minsize=300)
        content.rowconfigure(0, weight=1)

        # Left: scrollable preview list
        list_container = ttk.Frame(content)
        list_container.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.preview_canvas = tk.Canvas(list_container, bg=c["bg_dark"],
                                         highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical",
                                   command=self.preview_canvas.yview)
        self.preview_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.preview_canvas.pack(side="left", fill="both", expand=True)

        # Debounced redraw on canvas resize so card widths match
        self._resize_after_id = None
        def _on_canvas_resize(event):
            if self._resize_after_id:
                self.root.after_cancel(self._resize_after_id)
            self._resize_after_id = self.root.after(
                150, lambda: self._display_preview()
                if hasattr(self, '_card_positions') and self._card_positions
                else None)
        self.preview_canvas.bind("<Configure>", _on_canvas_resize)

        # Mousewheel
        def _on_mousewheel(event):
            self.preview_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.preview_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.preview_canvas.bind_all(
            "<Button-4>", lambda e: self.preview_canvas.yview_scroll(-3, "units"))
        self.preview_canvas.bind_all(
            "<Button-5>", lambda e: self.preview_canvas.yview_scroll(3, "units"))

        # Right: detail panel (scrollable)
        detail_panel = ttk.Frame(content, style="Mid.TFrame")
        detail_panel.grid(row=0, column=1, sticky="nsew")

        detail_canvas = tk.Canvas(detail_panel, bg=c["bg_mid"],
                                   highlightthickness=0, bd=0)
        detail_scrollbar = ttk.Scrollbar(detail_panel, orient="vertical",
                                          command=detail_canvas.yview)
        self.detail_inner = ttk.Frame(detail_canvas, style="Mid.TFrame")
        self.detail_inner.bind(
            "<Configure>",
            lambda e: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")))
        detail_canvas.create_window((0, 0), window=self.detail_inner, anchor="nw")
        detail_canvas.configure(yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.pack(side="right", fill="y")
        detail_canvas.pack(side="left", fill="both", expand=True)

        def _sync_detail_width(event):
            detail_canvas.itemconfig(detail_canvas.find_all()[0], width=event.width)
        detail_canvas.bind("<Configure>", _sync_detail_width)

        # Detail panel mousewheel management
        def _detail_mousewheel(event):
            detail_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        detail_canvas.bind("<Enter>",
            lambda e: detail_canvas.bind_all("<MouseWheel>", _detail_mousewheel))
        detail_canvas.bind("<Leave>",
            lambda e: detail_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        detail_canvas.bind("<Enter>", lambda e: (
            detail_canvas.bind_all("<Button-4>",
                lambda ev: detail_canvas.yview_scroll(-3, "units")),
            detail_canvas.bind_all("<Button-5>",
                lambda ev: detail_canvas.yview_scroll(3, "units"))
        ), add="+")
        detail_canvas.bind("<Leave>", lambda e: (
            self.preview_canvas.bind_all("<Button-4>",
                lambda ev: self.preview_canvas.yview_scroll(-3, "units")),
            self.preview_canvas.bind_all("<Button-5>",
                lambda ev: self.preview_canvas.yview_scroll(3, "units"))
        ), add="+")

        # Detail panel content
        pad = ttk.Frame(self.detail_inner, style="Mid.TFrame")
        pad.pack(fill="both", expand=True, padx=16, pady=16)

        self.poster_label = ttk.Label(pad, style="Detail.TLabel", background=c["bg_mid"])
        self.poster_label.pack(anchor="center", fill="x", pady=(0, 12))

        ttk.Separator(pad, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(pad, text="DETAIL", style="DetailDim.TLabel",
                  font=("Helvetica", 9, "bold")).pack(anchor="w", fill="x", pady=(8, 6))

        self.detail_label = ttk.Label(pad, text="Click an item to view details",
                                       style="Detail.TLabel",
                                       wraplength=260, justify="left")
        self.detail_label.pack(anchor="w", fill="x")

        self.detail_image = ttk.Label(pad, style="Detail.TLabel", background=c["bg_mid"])
        self.detail_image.pack(anchor="center", fill="x", pady=(12, 0))

        # Re-match button for movies — hidden until a movie card is selected
        self.rematch_btn = ttk.Button(
            pad, text="Re-match on TMDB",
            command=self._rematch_selected_movie,
            style="TButton")
        # Not packed yet — shown/hidden by _show_detail

        def _on_detail_resize(event):
            available = event.width - 40
            if available > 100:
                self.detail_label.configure(wraplength=available)
        pad.bind("<Configure>", _on_detail_resize)

        # ── Status bar ────────────────────────────────────────────────
        status_bar = ttk.Frame(self.root, style="Mid.TFrame")
        status_bar.pack(fill="x", side="bottom")

        self.status_var = tk.StringVar(value="Ready — select a folder to begin")
        ttk.Label(status_bar, textvariable=self.status_var,
                  style="Status.TLabel").pack(fill="x")

    # ══════════════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _create_checkbox_images(colors, size=18):
        from PIL import ImageDraw

        img_off = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw_off = ImageDraw.Draw(img_off)
        draw_off.rounded_rectangle([1, 1, size - 2, size - 2],
                                    radius=3, outline=colors["border_light"], width=2)

        img_on = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw_on = ImageDraw.Draw(img_on)
        draw_on.rounded_rectangle([1, 1, size - 2, size - 2],
                                   radius=3, fill=colors["accent"])
        dark = colors["bg_dark"]
        cx, cy = size * 0.28, size * 0.52
        mx, my = size * 0.45, size * 0.70
        ex, ey = size * 0.75, size * 0.32
        draw_on.line([(cx, cy), (mx, my), (ex, ey)],
                      fill=dark, width=max(2, size // 8))

        return {
            "unchecked": ImageTk.PhotoImage(img_off),
            "checked": ImageTk.PhotoImage(img_on),
        }

    def _create_dialog(self, title, width=500, height=300):
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=c["bg_mid"])
        win.transient(self.root)
        win.grab_set()

        scaled_w = int(width * self.dpi_scale)
        scaled_h = int(height * self.dpi_scale)

        self.root.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        x = max(0, root_x + (root_w - scaled_w) // 2)
        y = max(0, root_y + (root_h - scaled_h) // 2)

        win.geometry(f"{scaled_w}x{scaled_h}+{x}+{y}")
        win.minsize(scaled_w, scaled_h)
        return win

    def _get_tmdb_client(self) -> TMDBClient | None:
        """Get a TMDB client, or show a warning and return None."""
        api_key = get_api_key("TMDB")
        if not api_key:
            messagebox.showwarning(
                "No Key", "Set your TMDB API key first via 'API Keys'.")
            return None
        return TMDBClient(api_key)

    def _scale_to_panel(self, img: Image.Image) -> Image.Image:
        """Scale a PIL Image to fit the detail panel width."""
        self.root.update_idletasks()
        try:
            panel_w = self.detail_inner.winfo_width() - 40
        except Exception:
            panel_w = 280
        if panel_w < 150:
            panel_w = 280
        if img.width > panel_w:
            scale = panel_w / img.width
            img = img.resize((panel_w, int(img.height * scale)), Image.LANCZOS)
        return img

    # ══════════════════════════════════════════════════════════════════
    #  Event handlers
    # ══════════════════════════════════════════════════════════════════

    def _on_type_change(self, event=None):
        """Handle media type combobox change — swap buttons and controls."""
        val = self.type_var.get()
        if val == "TV Series":
            self.media_type = MediaType.TV
            self.order_frame.grid()
            # Show TV button, hide movie buttons
            self.btn_select_movie_folder.pack_forget()
            self.btn_select_movie_files.pack_forget()
            self.btn_select_folder.pack(side="left")
        else:
            self.media_type = MediaType.MOVIE
            self.order_frame.grid_remove()
            # Show movie buttons, hide TV button
            self.btn_select_folder.pack_forget()
            self.btn_select_movie_folder.pack(side="left", padx=(0, 4))
            self.btn_select_movie_files.pack(side="left")

    def manage_keys(self):
        c = self.colors
        win = self._create_dialog("API Keys", width=480, height=160)

        ttk.Label(win, text="API KEY MANAGER", style="Title.TLabel",
                  font=("Helvetica", 14, "bold"),
                  background=c["bg_mid"]).pack(anchor="w", padx=20, pady=(16, 12))

        row = ttk.Frame(win, style="Mid.TFrame")
        row.pack(fill="x", padx=20, pady=4)

        ttk.Label(row, text="TMDB:", width=6, background=c["bg_mid"],
                  foreground=c["text_dim"]).pack(side="left")
        var = tk.StringVar(value=get_api_key("TMDB") or "")
        entry = ttk.Entry(row, textvariable=var, width=36, show="*")
        entry.pack(side="left", padx=(8, 8), fill="x", expand=True)
        ttk.Button(row, text="Save", style="Small.TButton",
                   command=lambda: self._save_key("TMDB", var.get(), win)
                   ).pack(side="left")

    def _save_key(self, service, key, win):
        if key.strip():
            save_api_key(service, key.strip())
            messagebox.showinfo("Saved", f"{service} key saved.", parent=win)
        else:
            messagebox.showwarning("Empty", "Key cannot be empty.", parent=win)

    # ══════════════════════════════════════════════════════════════════
    #  Folder & media selection
    # ══════════════════════════════════════════════════════════════════

    def pick_folder(self):
        """
        Let the user select a folder, then begin the appropriate workflow.

        TV Series: folder name → TMDB show search → user picks show → scan
        Movies:    folder is just the container — each file is matched
                   individually against TMDB during the scan phase.
        """
        folder = filedialog.askdirectory(title="Select Media Folder")
        if not folder:
            return
        self.folder = Path(folder)
        self.status_var.set(f"Selected: {self.folder}")

        tmdb = self._get_tmdb_client()
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
        """
        Let the user select one or more individual movie files.

        The parent directory of the first file is used as the root folder
        for output (new movie subfolders are created there).
        """
        from .constants import VIDEO_EXTENSIONS

        ext_list = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        files = filedialog.askopenfilenames(
            title="Select Movie File(s)",
            filetypes=[("Video files", ext_list), ("All files", "*.*")],
        )
        if not files:
            return

        file_paths = [Path(f) for f in files]
        self.folder = file_paths[0].parent
        self.status_var.set(
            f"Selected: {len(file_paths)} file(s) in {self.folder}")

        tmdb = self._get_tmdb_client()
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
            results,
            title_key="name",
            dialog_title="Select Show",
            search_callback=tmdb.search_tv,
        )
        if not chosen:
            return

        self.media_info = chosen
        self.tv_scanner = TVScanner(tmdb, chosen, self.folder)
        self.movie_scanner = None

        self._display_poster(tmdb, chosen["id"], "tv")
        year = chosen.get("year", "")
        self.media_label_var.set(f"{chosen['name']}" + (f" ({year})" if year else ""))
        self.status_var.set("Scanning files...")
        self.root.update_idletasks()
        self.run_preview()

    def _setup_movie_scan(
        self, tmdb: TMDBClient, files: list[Path] | None = None,
    ):
        """
        Set up the movie workflow.

        Unlike TV, there is no single "show" to select up front — each
        file is its own movie matched individually against TMDB.

        Args:
            tmdb: TMDB client.
            files: Explicit file list (from file picker), or None to scan
                   the entire folder.
        """
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

        # For single-file explicit picks, run synchronously with the
        # confirmation dialog.  For everything else, run_preview will
        # launch the async background scan.
        if files and len(files) == 1:
            self._run_single_movie_scan(files[0])
        else:
            self.run_preview()

    def _run_single_movie_scan(self, file_path: Path):
        """
        Run a single-movie scan synchronously with the confirmation dialog.
        This is fast (1-2 API calls) and needs the dialog, so no threading.
        """
        self.status_var.set("Searching TMDB...")
        self.root.update_idletasks()

        self.preview_items = self.movie_scanner.scan(
            pick_movie_callback=self._pick_movie_for_file,
        )

        check_duplicates(self.preview_items)
        self._display_preview()

        # Auto-select the card to show poster
        ok_items = [it for it in self.preview_items if it.status == "OK"]
        if len(ok_items) == 1:
            idx = self.preview_items.index(ok_items[0])
            self._select_card(idx)

    def _pick_media_dialog(
        self,
        results: list[dict],
        title_key: str = "name",
        dialog_title: str = "Select",
        allow_skip: bool = False,
        search_callback: callable | None = None,
    ) -> dict | None:
        """
        Show a selection dialog for TMDB results.

        Always shows the dialog so the user can verify even single-result
        matches.  Includes a re-search field so the user can manually
        correct the query if the auto-detected name was wrong.

        Args:
            results: TMDB search results to display.
            title_key: Key for the display name ("name" for TV, "title" for movies).
            dialog_title: Window title.
            allow_skip: If True, show a Skip button (used for per-file movie matching).
            search_callback: If provided, enables the re-search field.
                Should be a function(query: str) -> list[dict].
        """
        c = self.colors
        win = self._create_dialog(dialog_title, width=520, height=440)

        ttk.Label(win, text=dialog_title.upper(), style="Title.TLabel",
                  font=("Helvetica", 14, "bold"),
                  background=c["bg_mid"]).pack(anchor="w", padx=20, pady=(16, 4))

        subtitle = ("No auto-match found — search manually:" if not results
                     else "Confirm the match:" if len(results) == 1
                     else "Multiple matches — select the correct one:")
        self._subtitle_label = ttk.Label(win, text=subtitle, style="Subtitle.TLabel",
                  background=c["bg_mid"])
        self._subtitle_label.pack(anchor="w", padx=20, pady=(0, 8))

        # Re-search bar
        current_results = list(results)

        if search_callback:
            search_row = ttk.Frame(win, style="Mid.TFrame")
            search_row.pack(fill="x", padx=20, pady=(0, 8))
            search_entry = ttk.Entry(search_row, width=40)
            search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        listbox = tk.Listbox(win, width=70, height=10,
                              bg=c["bg_card"], fg=c["text"],
                              selectbackground=c["accent"],
                              selectforeground=c["bg_dark"],
                              font=("Helvetica", 11),
                              borderwidth=0, highlightthickness=1,
                              highlightcolor=c["border_light"],
                              highlightbackground=c["border"])
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
            ttk.Button(btn_row, text="Skip", command=on_skip,
                       style="TButton").pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Confirm", command=on_ok,
                   style="Accent.TButton").pack(side="left")

        self.root.wait_window(win)
        return selected[0]

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
    #  Preview
    # ══════════════════════════════════════════════════════════════════

    def run_preview(self):
        """Scan the folder and display the rename preview."""
        if not self.folder or not self.media_info:
            messagebox.showwarning("Not Ready", "Select a folder and media first.")
            return

        self.preview_items = []
        self.check_vars = {}

        if self.media_type == MediaType.TV and self.tv_scanner:
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
        """
        Run the movie scan in a background thread so the GUI stays
        responsive during potentially hundreds of TMDB API calls.

        Progress updates are marshalled back to the main thread via
        root.after() which is the only thread-safe way to touch tkinter.
        """
        import threading

        scanner = self.movie_scanner
        self.status_var.set("Scanning files...")
        self.root.update_idletasks()

        # Disable buttons during scan to prevent double-starts
        self._set_scan_buttons_enabled(False)

        result_holder: list[list[PreviewItem]] = [None]
        error_holder: list[Exception | None] = [None]

        def _progress(done, total, phase):
            # Schedule GUI update on the main thread
            self.root.after(0, lambda: self.status_var.set(
                f"{phase} {done}/{total}"))

        def _scan_worker():
            try:
                items = scanner.scan(
                    pick_movie_callback=None,  # No dialogs from bg thread
                    progress_callback=_progress,
                )
                result_holder[0] = items
            except Exception as e:
                error_holder[0] = e

            # Schedule completion handler on the main thread
            self.root.after(0, _on_scan_complete)

        def _on_scan_complete():
            self._set_scan_buttons_enabled(True)

            if error_holder[0]:
                messagebox.showerror(
                    "Scan Error", f"Error during scan:\n{error_holder[0]}")
                self.status_var.set("Scan failed.")
                return

            self.preview_items = result_holder[0] or []
            check_duplicates(self.preview_items)
            self._display_preview()

            # For a single movie, auto-display its poster
            ok_items = [it for it in self.preview_items if it.status == "OK"]
            if len(ok_items) == 1:
                idx = self.preview_items.index(ok_items[0])
                self._select_card(idx)

        thread = threading.Thread(target=_scan_worker, daemon=True)
        thread.start()

    def _set_scan_buttons_enabled(self, enabled: bool):
        """Enable or disable scan-related buttons."""
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_select_folder, self.btn_select_movie_folder,
                    self.btn_select_movie_files):
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _pick_movie_for_file(self, results: list[dict], filename: str):
        """
        Callback for MovieScanner single-file mode.

        Returns a chosen dict, None to skip, or _CANCEL_SCAN to abort.
        """
        tmdb = self._get_tmdb_client()
        chosen = self._pick_media_dialog(
            results, title_key="title",
            dialog_title=f"Match: {filename}",
            allow_skip=True,
            search_callback=tmdb.search_movie if tmdb else None,
        )
        return chosen

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
    #  Display preview
    # ══════════════════════════════════════════════════════════════════

    def _display_preview(self):
        """
        Render the preview list using canvas primitives for performance.

        Draws styled cards with badge pills, accent bars, checkboxes,
        two-line text (original → new), and status indicators — all as
        lightweight canvas items instead of widget trees.

        Items are sorted: OK first, then REVIEW, then SKIP/CONFLICT.
        """
        c = self.colors
        cv = self.preview_canvas

        # Preserve existing selections across redraws
        saved_checks = {}
        for k, v in self.check_vars.items():
            saved_checks[k] = v.get()

        cv.delete("all")
        self._image_refs.clear()
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

        # Sort: OK first, then REVIEW, then everything else
        def _sort_key(idx):
            s = self.preview_items[idx].status
            if s == "OK":
                return (0, idx)
            elif "REVIEW" in s:
                return (1, idx)
            else:
                return (2, idx)

        self._display_order = sorted(
            range(len(self.preview_items)), key=_sort_key)

        # Create / restore BooleanVars
        self.check_vars.clear()
        for i, item in enumerate(self.preview_items):
            key = str(i)
            default = item.status == "OK"
            var = tk.BooleanVar(value=saved_checks.get(key, default))
            var.trace_add("write", lambda *_, s=self: s._update_tally())
            self.check_vars[key] = var

        # ── Layout constants (DPI-aware) ─────────────────────────────
        # Measure actual font heights from tkinter so we don't guess.
        import tkinter.font as tkfont

        font_orig = tkfont.Font(family="Helvetica", size=11)
        font_new = tkfont.Font(family="Helvetica", size=10)
        font_badge = tkfont.Font(family="Helvetica", size=8, weight="bold")
        font_check = tkfont.Font(family="Helvetica", size=14)
        font_season = tkfont.Font(family="Helvetica", size=9)

        # linespace gives the full line height including ascent + descent + leading
        line1_h = font_orig.metrics("linespace")     # original filename
        line2_h = font_new.metrics("linespace")      # new name
        line3_h = font_season.metrics("linespace")    # season info
        badge_text_h = font_badge.metrics("linespace")
        check_h = font_check.metrics("linespace")

        canvas_w = max(600, cv.winfo_width())
        scale = self.dpi_scale
        card_margin_x = int(6 * scale)
        card_margin_y = int(3 * scale)
        card_pad_x = int(14 * scale)
        card_pad_y = int(12 * scale)
        accent_bar_w = int(4 * scale)
        check_col_w = int(28 * scale)
        badge_h = badge_text_h + int(8 * scale)  # text + vertical padding
        badge_pad_x = int(6 * scale)
        badge_gap = int(6 * scale)
        line_gap = int(8 * scale)

        # Convert font objects to tuples for canvas (canvas doesn't accept Font objects)
        font_orig_t = ("Helvetica", 11)
        font_new_t = ("Helvetica", 10)
        font_badge_t = ("Helvetica", 8, "bold")
        font_check_t = ("Helvetica", 14)
        font_season_t = ("Helvetica", 9)

        y = card_margin_y

        for display_idx, item_idx in enumerate(self._display_order):
            item = self.preview_items[item_idx]
            is_multi = len(item.episodes) > 1
            is_special = item.season == 0
            is_movie = item.media_type == MediaType.MOVIE
            has_badges = is_multi or is_special
            item_tag = f"item_{item_idx}"

            # ── Determine text content and colors ─────────────────────
            if "SKIP" in item.status:
                name_fg, arrow_fg = c["text_muted"], c["text_muted"]
                arrow_text = item.status
                card_bg = c["bg_card"]
            elif "REVIEW" in item.status:
                name_fg, arrow_fg = c["text"], c["info"]
                arrow_text = item.status
                card_bg = c["bg_card"]
            elif "CONFLICT" in item.status:
                name_fg, arrow_fg = c["error"], c["error"]
                arrow_text = item.status
                card_bg = c["bg_card"]
            elif item.is_move():
                name_fg, arrow_fg = c["text"], c["move"]
                arrow_text = f"→  [{item.target_dir.name}]  {item.new_name}"
                card_bg = c["bg_card"]
            else:
                name_fg, arrow_fg = c["text"], c["success"]
                arrow_text = f"→  {item.new_name}" if item.new_name else ""
                card_bg = c["bg_card"]

            orig_text = item.original.name
            if item.is_move():
                orig_text = f"[{item.original.parent.name}]  {orig_text}"

            # Card border color
            if is_special:
                border_color = c["badge_special_bd"]
            elif is_multi:
                border_color = c["badge_multi_bd"]
            else:
                border_color = c["border"]

            # ── Calculate row height dynamically ──────────────────────
            # All heights come from actual font metrics, not guesses.
            # Season/episode info is shown in the detail panel only —
            # it's redundant on TV cards where S01E01 is in the filename.
            badge_row_h = (badge_h + line_gap) if has_badges else 0
            has_line2 = bool(arrow_text)

            row_content_h = (card_pad_y
                             + badge_row_h
                             + line1_h
                             + (line_gap + line2_h if has_line2 else 0)
                             + card_pad_y)
            row_h = max(int(48 * scale), row_content_h)

            y_start = y
            x_left = card_margin_x
            x_right = canvas_w - card_margin_x

            # ── Card background ───────────────────────────────────────
            cv.create_rectangle(
                x_left, y, x_right, y + row_h,
                fill=card_bg, outline=border_color,
                tags=("card", item_tag))

            # ── Accent bar (left edge) ────────────────────────────────
            if is_special:
                cv.create_rectangle(
                    x_left, y, x_left + accent_bar_w, y + row_h,
                    fill=c["badge_special_bd"], outline="",
                    tags=(item_tag,))
            elif is_multi:
                cv.create_rectangle(
                    x_left, y, x_left + accent_bar_w, y + row_h,
                    fill=c["badge_multi_bd"], outline="",
                    tags=(item_tag,))

            # ── Checkbox ──────────────────────────────────────────────
            check_var = self.check_vars[str(item_idx)]
            check_x = x_left + accent_bar_w + card_pad_x
            check_cy = y + row_h // 2
            check_char = "☑" if check_var.get() else "☐"
            check_color = c["accent"] if check_var.get() else c["border_light"]
            cv.create_text(
                check_x, check_cy, text=check_char,
                fill=check_color, font=font_check_t, anchor="w",
                tags=(f"check_{display_idx}", "check", item_tag))

            # Text content starts after checkbox column
            text_x = check_x + check_col_w
            text_y = y + card_pad_y

            # ── Badge pills ───────────────────────────────────────────
            if has_badges:
                bx = text_x
                by = text_y

                if is_multi:
                    label = f" {len(item.episodes)}-PART "
                    tw = font_badge.measure(label)
                    pill_w = tw + badge_pad_x * 2
                    cv.create_rectangle(
                        bx, by, bx + pill_w, by + badge_h,
                        fill=c["badge_multi_bg"], outline=c["badge_multi_bd"],
                        tags=(item_tag,))
                    cv.create_text(
                        bx + badge_pad_x, by + badge_h // 2, text=label,
                        fill=c["badge_multi_fg"], font=font_badge_t, anchor="w",
                        tags=(item_tag,))
                    bx += pill_w + badge_gap

                if is_special:
                    label = " SPECIAL "
                    tw = font_badge.measure(label)
                    pill_w = tw + badge_pad_x * 2
                    cv.create_rectangle(
                        bx, by, bx + pill_w, by + badge_h,
                        fill=c["badge_special_bg"], outline=c["badge_special_bd"],
                        tags=(item_tag,))
                    cv.create_text(
                        bx + badge_pad_x, by + badge_h // 2, text=label,
                        fill=c["badge_special_fg"], font=font_badge_t, anchor="w",
                        tags=(item_tag,))

                text_y += badge_h + line_gap

            # ── Line 1: Original filename ─────────────────────────────
            cv.create_text(
                text_x, text_y, text=orig_text,
                fill=name_fg, font=font_orig_t, anchor="nw",
                tags=("text", item_tag))
            text_y += line1_h

            # ── Line 2: Arrow + new name ──────────────────────────────
            if arrow_text:
                text_y += line_gap
                cv.create_text(
                    text_x + 4, text_y, text=arrow_text,
                    fill=arrow_fg, font=font_new_t, anchor="nw",
                    tags=("text", item_tag))

            self._card_positions.append((y_start, y_start + row_h, item_idx))
            y += row_h + card_margin_y

        # Scroll region
        cv.configure(scrollregion=(0, 0, canvas_w, y + 10))
        cv.bind("<Button-1>", self._on_canvas_click)

        # Status counts
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

    def _on_canvas_click(self, event):
        """Handle clicks on the preview canvas — checkbox toggles and card selection."""
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
        """Toggle checkbox and redraw just the checkbox character."""
        key = str(item_idx)
        var = self.check_vars.get(key)
        if not var:
            return
        var.set(not var.get())

        c = self.colors
        cv = self.preview_canvas
        scale = self.dpi_scale

        for display_idx, (y_start, y_end, idx) in enumerate(self._card_positions):
            if idx == item_idx:
                check_tag = f"check_{display_idx}"
                cv.delete(check_tag)
                check_char = "☑" if var.get() else "☐"
                check_color = c["accent"] if var.get() else c["border_light"]
                check_x = int(6 * scale) + int(4 * scale) + int(14 * scale)
                check_cy = y_start + (y_end - y_start) // 2
                cv.create_text(
                    check_x, check_cy, text=check_char,
                    fill=check_color, font=("Helvetica", 14), anchor="w",
                    tags=(check_tag, "check", f"item_{idx}"))
                break

    # ══════════════════════════════════════════════════════════════════
    #  Detail panel
    # ══════════════════════════════════════════════════════════════════

    def _select_card(self, item_idx):
        """Highlight the selected card on the canvas and show its detail."""
        c = self.colors

        # Reset all card backgrounds
        for tag_id in self.preview_canvas.find_withtag("card"):
            self.preview_canvas.itemconfigure(tag_id, outline=c["border"])

        # Highlight the selected card
        for tag_id in self.preview_canvas.find_withtag(f"item_{item_idx}"):
            item_type = self.preview_canvas.type(tag_id)
            if item_type == "rectangle":
                tags = self.preview_canvas.gettags(tag_id)
                if "card" in tags:
                    self.preview_canvas.itemconfigure(tag_id, outline=c["accent"])

        self._selected_index = item_idx
        self._show_detail(item_idx)

    def _show_detail(self, index):
        c = self.colors
        item = self.preview_items[index]

        is_multi = len(item.episodes) > 1
        is_special = item.season == 0
        is_movie = item.media_type == MediaType.MOVIE

        lines = []

        # Type indicator
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

        # Show/hide the Re-match button for movie items
        if is_movie:
            self.rematch_btn.pack(anchor="w", pady=(12, 0))
        else:
            self.rematch_btn.pack_forget()

        # Episode still (TV) or movie poster (Movie)
        tmdb = self._get_tmdb_client()
        if not tmdb or not self.media_info:
            self.detail_image.configure(image="")
            return

        if is_movie:
            movie_data = (self.movie_scanner.movie_info.get(item.original)
                          if self.movie_scanner else None)
            if movie_data and movie_data.get("poster_path"):
                img = tmdb.fetch_image(movie_data["poster_path"], target_width=400)
                if img:
                    img = self._scale_to_panel(img)
                    photo = ImageTk.PhotoImage(img)
                    self._image_refs.append(photo)
                    self.detail_image.configure(image=photo)
                    return
        elif self.tv_scanner and item.episodes:
            poster_path = self.tv_scanner.episode_posters.get(
                (item.season, item.episodes[0]))
            if poster_path:
                img = tmdb.fetch_image(poster_path, target_width=400)
                if img:
                    img = self._scale_to_panel(img)
                    photo = ImageTk.PhotoImage(img)
                    self._image_refs.append(photo)
                    self.detail_image.configure(image=photo)
                    return

        self.detail_image.configure(image="")

    def _rematch_selected_movie(self):
        """
        Open a match dialog for the currently selected movie card.

        Uses cached search results as the starting point but allows
        the user to re-search.  Updates the preview item in place.
        """
        if self._selected_index is None:
            return
        item = self.preview_items[self._selected_index]
        if item.media_type != MediaType.MOVIE or not self.movie_scanner:
            return

        tmdb = self._get_tmdb_client()
        if not tmdb:
            return

        # Start with cached results, allow re-search
        cached = self.movie_scanner.get_search_results(item.original)
        chosen = self._pick_media_dialog(
            cached,
            title_key="title",
            dialog_title=f"Re-match: {item.original.name}",
            allow_skip=True,
            search_callback=tmdb.search_movie,
        )

        if not chosen:
            return

        # Update the preview item in place
        new_item = self.movie_scanner.rematch_file(item, chosen)
        self.preview_items[self._selected_index] = new_item

        # Re-check for duplicates and refresh the display
        check_duplicates(self.preview_items)
        self._display_preview()

        # Re-select the same card to update the detail panel
        self._select_card(self._selected_index)

    # ══════════════════════════════════════════════════════════════════
    #  Rename / Undo
    # ══════════════════════════════════════════════════════════════════

    def execute_rename(self):
        if not self.preview_items or not self.check_vars:
            messagebox.showwarning(
                "Preview First",
                "Scan and review files before renaming.")
            return

        checked = set()
        for i, item in enumerate(self.preview_items):
            key = str(i)
            var = self.check_vars.get(key)
            if var and var.get() and item.status == "OK" and item.new_name:
                checked.add(i)

        if not checked:
            messagebox.showinfo("Nothing to do", "No files selected for rename.")
            return

        move_count = sum(
            1 for i in checked if self.preview_items[i].is_move()
        )
        msg = f"Rename {len(checked)} file(s)?"
        if move_count:
            msg += f"\n\n{move_count} file(s) will be moved to a different folder."
            msg += "\nEmpty source folders will be removed."
        msg += "\n\nThis can be undone via 'Undo Last'."

        if not messagebox.askyesno("Confirm Rename", msg):
            return

        media_name = (self.media_info.get("name")
                       or self.media_info.get("title")
                       or self.folder.name)

        result = execute_rename(
            self.preview_items, checked, media_name, self.folder,
        )

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
        if self.folder and self.media_info:
            self.run_preview()

    # ══════════════════════════════════════════════════════════════════
    #  Search / selection helpers
    # ══════════════════════════════════════════════════════════════════

    def update_search(self):
        query = self.search_var.get().lower()
        if not hasattr(self, '_card_positions'):
            return

        for y_start, y_end, item_idx in self._card_positions:
            item = self.preview_items[item_idx]
            text = (item.original.name + " " + (item.new_name or "")).lower()
            tag = f"item_{item_idx}"
            if query and query not in text:
                for cid in self.preview_canvas.find_withtag(tag):
                    self.preview_canvas.itemconfigure(cid, state="hidden")
            else:
                for cid in self.preview_canvas.find_withtag(tag):
                    self.preview_canvas.itemconfigure(cid, state="normal")

    def select_all(self):
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
        selected = 0
        for i, item in enumerate(self.preview_items):
            if item.status == "OK":
                var = self.check_vars.get(str(i))
                if var and var.get():
                    selected += 1
        self.tally_var.set(f"{selected} / {total}")

    # ══════════════════════════════════════════════════════════════════
    #  Run
    # ══════════════════════════════════════════════════════════════════

    def run(self):
        """Start the tkinter main loop."""
        self.root.mainloop()
