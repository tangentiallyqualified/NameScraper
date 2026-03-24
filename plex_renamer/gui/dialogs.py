"""
Dialog windows — media picker, API key manager, season mismatch prompt.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..keys import get_api_key, save_api_key
from ..styles import COLORS
from .helpers import create_dialog


def manage_keys_dialog(app) -> None:
    """Open the API key management dialog."""
    c = COLORS
    win = create_dialog(app.root, "API Keys", app.dpi_scale, width=480, height=160)

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
            app.tmdb = None  # Force client refresh with new key
            messagebox.showinfo("Saved", "TMDB key saved.", parent=win)
        else:
            messagebox.showwarning("Empty", "Key cannot be empty.", parent=win)

    ttk.Button(row, text="Save", style="Small.TButton",
               command=_save).pack(side="left")


def pick_media_dialog(
    app,
    results: list[dict],
    title_key: str = "name",
    dialog_title: str = "Select",
    allow_skip: bool = False,
    search_callback=None,
) -> dict | None:
    """
    Show a dialog to pick a media item from TMDB search results.

    Supports manual re-search via an optional search_callback.
    Returns the chosen result dict, or None if cancelled/skipped.
    """
    c = COLORS
    win = create_dialog(app.root, dialog_title, app.dpi_scale, width=520, height=440)

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

    app.root.wait_window(win)
    return selected[0]


def prompt_season_fix(root: tk.Tk, info: dict) -> bool:
    """Ask the user whether to auto-fix a season structure mismatch."""
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
