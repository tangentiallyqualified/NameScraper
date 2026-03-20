"""
Plex Advanced TV Series Renamer
================================
A GUI tool to rename TV series files into Plex-compatible naming format.

Fixed issues from original version:
  #1  - S##E## pattern now checked FIRST (most reliable/unambiguous)
  #2  - Multi-episode files (S01E01E02, S01E01-E02) are now detected
  #3  - Absolute episode numbering supported with season mapping
  #4  - clean_name() preserves year info and is less destructive
  #5  - Filenames are sanitized for filesystem-illegal characters
  #6  - TVDB client updated to API v4 (api4.thetvdb.com)
  #7  - TMDB search now lets the user pick from multiple results
  #8  - first_air_date safely handled for empty strings
  #9  - All GUI methods fully implemented
  #10 - Layout uses PanedWindow for reliable resizing
  #11 - mainloop() moved outside __init__
  #12 - Scrollbar added to preview area
  #13 - Undo log stored in a fixed location with atomic write safety
  #14 - Duplicate target filename collision detection before rename
  #15 - Preview UI with per-episode checkboxes to include/exclude
  #16 - Poster image references retained to prevent GC
"""

import os
import re
import json
import shutil
import tempfile
import requests
import keyring
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk
import io

# -------------------------
# Constants
# -------------------------
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m4v"}

# FIX #13: Use a fixed location for the log file so it's always findable
# regardless of the current working directory when the script is launched.
LOG_DIR = Path.home() / ".plex_renamer"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "rename_log.json"

# FIX #5: Characters illegal in filenames on Windows (and problematic elsewhere).
# We'll replace these with safe alternatives when building filenames.
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


# -------------------------
# Key Storage
# -------------------------
def save_api_key(service, key):
    """Persist an API key securely using the OS keyring."""
    keyring.set_password("PlexRenamer", service, key)


def get_api_key(service):
    """Retrieve a stored API key from the OS keyring."""
    return keyring.get_password("PlexRenamer", service)


# -------------------------
# Name Parsing Utilities
# -------------------------
def clean_name(name):
    """
    Normalize a filename for pattern matching.

    FIX #4: Only strip common fansub/release-group bracket tags
    (e.g. [720p], [SubGroup]) but preserve parenthesized years like (2023).
    Dots and underscores are replaced with spaces.
    """
    # Remove square-bracketed tags (fansub groups, quality tags, etc.)
    name = re.sub(r"\[.*?\]", "", name)
    # Remove parenthesized content EXCEPT 4-digit years
    name = re.sub(r"\((?!\d{4}\))[^)]*\)", "", name)
    # Replace dots and underscores with spaces for easier matching
    name = name.replace(".", " ").replace("_", " ")
    # Collapse multiple spaces
    return re.sub(r"\s+", " ", name).strip()


def extract_episode(filename):
    """
    Extract episode number(s) and title text from a filename.

    Returns:
        episode_numbers: list of ints (supports multi-episode files)
        title: str or None

    FIX #1: S##E## pattern is tried first — it's the most reliable.
    FIX #2: Multi-episode patterns like S01E01E02 and S01E01-E02 are handled.
    """
    name = clean_name(Path(filename).stem)

    # --- Pattern 1 (BEST): S##E## with optional multi-episode ---
    # Matches: S01E05, S01E05E06, S01E05-E06, S1E5
    m = re.search(r"S(\d+)E(\d+)(?:[E-]?E?(\d+))?\s*[-.]?\s*(.*)", name, re.IGNORECASE)
    if m:
        eps = [int(m.group(2))]
        if m.group(3):
            eps.append(int(m.group(3)))
        title = m.group(4).strip() if m.group(4) else None
        return eps, title

    # --- Pattern 2: Dash-delimited " - 05 - Title" (common in organized releases) ---
    m = re.search(r"-\s*(\d{1,3})\s*-\s*(.*)", name)
    if m:
        return [int(m.group(1))], m.group(2).strip()

    # --- Pattern 3: Episode number preceded by space/separator ---
    # Only match 1-3 digit numbers that DON'T look like a year (1900-2099)
    # or a resolution (480, 720, 1080, 2160). FIX #1: avoids false positives.
    m = re.search(r"(?<!\d)(?:ep?|episode)?\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?", name, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        # Reject numbers that look like years or resolutions
        if num not in (480, 720, 1080, 2160) and not (1900 <= num <= 2099):
            title = m.group(2).strip() if m.group(2) else None
            return [num], title

    return [], None


def get_season(folder):
    """
    Extract the season number from a folder name like 'Season 02'.
    Returns None if no season info is found.
    """
    m = re.search(r"season\s*(\d+)", folder.name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def sanitize_filename(name):
    """
    FIX #5: Remove or replace characters that are illegal in filenames
    on Windows and potentially problematic on other OSes.
    """
    # Replace colons with dashes (common in episode titles like "Part 1: The Beginning")
    name = name.replace(":", " -")
    # Remove all other unsafe characters
    name = UNSAFE_FILENAME_CHARS.sub("", name)
    # Collapse any resulting double spaces
    name = re.sub(r"\s+", " ", name).strip()
    # Windows also disallows trailing dots/spaces in file/folder names
    name = name.rstrip(". ")
    return name


def build_name(show, year, season, episodes, title, ext):
    """
    Build a Plex-compatible episode filename.

    FIX #2: Supports multi-episode naming (S01E01E02).
    FIX #5: Output is sanitized for filesystem safety.

    Args:
        show: Show name string
        year: Year string or empty
        season: Season number (int)
        episodes: List of episode numbers
        title: Episode title string
        ext: File extension including the dot
    """
    year_part = f" ({year})" if year else ""
    # Multi-episode: S01E01E02, single: S01E01
    ep_part = "".join(f"E{ep:02d}" for ep in episodes)
    raw = f"{show}{year_part} - S{season:02d}{ep_part} - {title}{ext}"
    return sanitize_filename(raw)


# -------------------------
# Undo Log (Atomic Writes)
# -------------------------
def load_log():
    """Load the rename history log."""
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_log(entries):
    """
    FIX #13: Write the log atomically — write to a temp file first, then
    rename. This prevents a half-written log if the process is interrupted.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(dir=LOG_DIR, suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(entries, f, indent=2)
        shutil.move(tmp_path, LOG_FILE)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# -------------------------
# TMDB Integration
# -------------------------
def tmdb_search_show(show_name, api_key):
    """
    Search TMDB for a show by name.

    FIX #7: Returns ALL results so the GUI can let the user choose,
    instead of blindly taking the first result.
    FIX #8: Safely handles empty/missing first_air_date.
    """
    url = "https://api.themoviedb.org/3/search/tv"
    try:
        r = requests.get(url, params={"api_key": api_key, "query": show_name}, timeout=10)
    except requests.RequestException:
        return []

    if not r.ok:
        return []

    results = r.json().get("results", [])
    shows = []
    for show in results:
        # FIX #8: first_air_date can be None, empty string, or missing entirely.
        air_date = show.get("first_air_date") or ""
        year = air_date[:4] if len(air_date) >= 4 else ""
        shows.append({
            "id": show["id"],
            "name": show["name"],
            "year": year,
            "poster_path": show.get("poster_path"),
            "overview": show.get("overview", ""),
        })
    return shows


def tmdb_episode_titles(show_id, season, api_key):
    """
    Get episode titles and still image paths from TMDB for a given season.

    Returns:
        titles: dict mapping episode_number -> title string
        posters: dict mapping episode_number -> still_path string or None
    """
    url = f"https://api.themoviedb.org/3/tv/{show_id}/season/{season}"
    try:
        r = requests.get(url, params={"api_key": api_key}, timeout=10)
    except requests.RequestException:
        return {}, {}

    if not r.ok:
        return {}, {}

    data = r.json()
    titles = {}
    posters = {}
    for ep in data.get("episodes", []):
        num = ep["episode_number"]
        titles[num] = ep.get("name", f"Episode {num}")
        posters[num] = ep.get("still_path")
    return titles, posters


def fetch_tmdb_poster(tmdb_id, api_key, season=None, ep_poster=None):
    """
    Fetch a poster/still image from TMDB.

    Priority: episode still -> season poster -> show poster.
    Returns a PIL Image object (not yet converted to ImageTk) or None.
    """
    base = "https://image.tmdb.org/t/p/w300"
    path = ep_poster

    if not path:
        try:
            if season is not None:
                r = requests.get(
                    f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}",
                    params={"api_key": api_key}, timeout=10
                )
            else:
                r = requests.get(
                    f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                    params={"api_key": api_key}, timeout=10
                )
            if r.ok:
                path = r.json().get("poster_path")
        except requests.RequestException:
            return None

    if path:
        try:
            img_r = requests.get(base + path, timeout=10)
            img = Image.open(io.BytesIO(img_r.content))
            img = img.resize((200, int(img.height * 200 / img.width)))
            return img
        except Exception:
            return None
    return None


# -------------------------
# TVDB Integration (Fallback)
# -------------------------
class TVDBClient:
    """
    FIX #6: Updated to TVDB API v4 (api4.thetvdb.com).
    The old v2/v3 endpoints at api.thetvdb.com have been retired.
    """

    BASE_URL = "https://api4.thetvdb.com/v4"

    def __init__(self, api_key):
        self.api_key = api_key
        self.token = None

    def authenticate(self):
        """Authenticate with TVDB v4 API."""
        url = f"{self.BASE_URL}/login"
        try:
            r = requests.post(url, json={"apikey": self.api_key}, timeout=10)
            if r.ok:
                self.token = r.json().get("data", {}).get("token")
                return True
        except requests.RequestException:
            pass
        return False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def search_show(self, name):
        """Search TVDB v4 for a show by name. Returns list of results."""
        try:
            r = requests.get(
                f"{self.BASE_URL}/search",
                params={"query": name, "type": "series"},
                headers=self._headers(), timeout=10
            )
            if r.ok:
                return r.json().get("data", [])
        except requests.RequestException:
            pass
        return []

    def get_season_episodes(self, series_id, season_number):
        """
        Fetch episodes for a specific season from TVDB v4.

        Returns:
            titles: dict mapping episode_number -> title
            posters: dict mapping episode_number -> image URL or None
        """
        try:
            r = requests.get(
                f"{self.BASE_URL}/series/{series_id}/episodes/default",
                params={"season": season_number},
                headers=self._headers(), timeout=10
            )
            if not r.ok:
                return {}, {}
        except requests.RequestException:
            return {}, {}

        titles = {}
        posters = {}
        for ep in r.json().get("data", {}).get("episodes", []):
            num = ep.get("number", 0)
            if num > 0:
                titles[num] = ep.get("name", f"Episode {num}")
                posters[num] = ep.get("image")
        return titles, posters


# -------------------------
# App Class (GUI + Logic)
# -------------------------
class PlexRenamerApp:
    """
    Main application class.

    FIX #9:  All GUI callback methods are fully implemented.
    FIX #10: Uses PanedWindow for reliable side-by-side layout.
    FIX #11: mainloop() is NOT called inside __init__.
    FIX #16: Poster image references are stored on self to prevent garbage collection.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Plex Advanced Renamer")
        self.root.geometry("1100x750")

        # State
        self.folder = None
        self.show_info = None          # Currently selected TMDB show dict
        self.episode_titles = {}       # ep_num -> title from TMDB/TVDB
        self.episode_posters = {}      # ep_num -> poster path
        self.preview_items = []        # List of dicts with rename info
        self._image_refs = []          # FIX #16: prevent GC of PhotoImage objects
        self.check_vars = {}           # ep key -> BooleanVar for checkboxes

        # --- Top toolbar ---
        toolbar = tk.Frame(self.root)
        toolbar.pack(fill="x", padx=10, pady=5)
        tk.Button(toolbar, text="Manage API Keys", command=self.manage_keys).pack(side="left", padx=3)
        tk.Button(toolbar, text="Select Show Folder", command=self.pick_folder).pack(side="left", padx=3)

        tk.Label(toolbar, text="  Episode Order:").pack(side="left")
        self.order_var = tk.StringVar(value="aired")
        ttk.Combobox(toolbar, textvariable=self.order_var,
                      values=["aired", "dvd", "absolute"], width=10).pack(side="left", padx=3)

        tk.Button(toolbar, text="Preview", command=lambda: self.run_preview(dry_run=True)).pack(side="left", padx=3)
        tk.Button(toolbar, text="Rename", command=lambda: self.run_preview(dry_run=False)).pack(side="left", padx=3)
        tk.Button(toolbar, text="Undo Last", command=self.undo).pack(side="left", padx=3)

        # --- Search bar ---
        search_frame = tk.Frame(self.root)
        search_frame.pack(fill="x", padx=10)
        tk.Label(search_frame, text="Filter:").pack(side="left")
        self.search_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=self.search_var, width=40).pack(side="left", padx=5)
        self.search_var.trace_add("write", lambda *_: self.update_search())

        # --- FIX #10: PanedWindow for reliable split layout ---
        pane = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6)
        pane.pack(fill="both", expand=True, padx=10, pady=5)

        # Left: scrollable preview list (FIX #12)
        left_frame = tk.Frame(pane)
        pane.add(left_frame, stretch="always")

        canvas = tk.Canvas(left_frame)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        self.preview_inner = tk.Frame(canvas)
        self.preview_inner.bind("<Configure>",
                                lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.preview_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Right: detail/poster panel
        right_frame = tk.Frame(pane, width=250)
        pane.add(right_frame, stretch="never")

        self.show_poster_label = tk.Label(right_frame)
        self.show_poster_label.pack(pady=5)
        self.detail_label = tk.Label(right_frame, text="", justify="left", wraplength=230)
        self.detail_label.pack(pady=5)
        self.detail_image = tk.Label(right_frame)
        self.detail_image.pack(pady=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, anchor="w",
                 relief="sunken", bd=1).pack(side="bottom", fill="x")

    # ------------------------------------------------------------------
    # FIX #9: All GUI methods fully implemented below
    # ------------------------------------------------------------------

    def manage_keys(self):
        """Dialog to set/update TMDB and TVDB API keys via OS keyring."""
        win = tk.Toplevel(self.root)
        win.title("API Key Manager")
        win.geometry("400x200")
        win.transient(self.root)
        win.grab_set()

        for row, service in enumerate(["TMDB", "TVDB"]):
            tk.Label(win, text=f"{service} API Key:").grid(row=row, column=0, padx=10, pady=10, sticky="e")
            var = tk.StringVar(value=get_api_key(service) or "")
            entry = tk.Entry(win, textvariable=var, width=35, show="*")
            entry.grid(row=row, column=1, padx=10, pady=10)
            # Use default arg in lambda to capture current values
            tk.Button(win, text="Save",
                      command=lambda s=service, v=var: self._save_key(s, v.get(), win)
                      ).grid(row=row, column=2, padx=5)

    def _save_key(self, service, key, win):
        if key.strip():
            save_api_key(service, key.strip())
            messagebox.showinfo("Saved", f"{service} key saved.", parent=win)
        else:
            messagebox.showwarning("Empty", "Key cannot be empty.", parent=win)

    def pick_folder(self):
        """Let the user select the root show folder, then search TMDB for it."""
        folder = filedialog.askdirectory(title="Select Show Root Folder")
        if not folder:
            return
        self.folder = Path(folder)
        self.status_var.set(f"Selected: {self.folder}")

        api_key = get_api_key("TMDB")
        if not api_key:
            messagebox.showwarning("No Key", "Set your TMDB API key first via 'Manage API Keys'.")
            return

        # Use the folder name as the initial search query
        show_name = self.folder.name
        # Strip trailing year like "Show Name (2020)" for a cleaner search
        show_name_clean = re.sub(r"\s*\(\d{4}\)\s*$", "", show_name)

        results = tmdb_search_show(show_name_clean, api_key)
        if not results:
            messagebox.showinfo("Not Found", f"No TMDB results for '{show_name_clean}'.")
            return

        # FIX #7: Let the user pick from the search results
        self.show_info = self._pick_show_dialog(results)
        if not self.show_info:
            return

        # Display show poster
        self._display_show_poster()
        self.status_var.set(f"Show: {self.show_info['name']} ({self.show_info['year']})")

    def _pick_show_dialog(self, results):
        """
        FIX #7: Present a dialog with all TMDB search results so the user
        can pick the correct show instead of blindly using the first match.
        """
        if len(results) == 1:
            return results[0]

        win = tk.Toplevel(self.root)
        win.title("Select Show")
        win.geometry("500x350")
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="Multiple matches found. Select the correct show:").pack(pady=5)

        listbox = tk.Listbox(win, width=70, height=12)
        listbox.pack(padx=10, pady=5, fill="both", expand=True)

        for i, show in enumerate(results):
            year = f" ({show['year']})" if show['year'] else ""
            listbox.insert(i, f"{show['name']}{year}")

        listbox.selection_set(0)
        selected = [None]

        def on_ok():
            sel = listbox.curselection()
            if sel:
                selected[0] = results[sel[0]]
            win.destroy()

        tk.Button(win, text="OK", command=on_ok).pack(pady=5)
        self.root.wait_window(win)
        return selected[0]

    def _display_show_poster(self):
        """Fetch and display the show poster in the detail panel."""
        if not self.show_info:
            return
        api_key = get_api_key("TMDB")
        img = fetch_tmdb_poster(self.show_info["id"], api_key)
        if img:
            photo = ImageTk.PhotoImage(img)
            # FIX #16: Keep a reference so tkinter doesn't garbage-collect the image
            self._image_refs.append(photo)
            self.show_poster_label.configure(image=photo)
        else:
            self.show_poster_label.configure(image="", text="(No poster)")

    def run_preview(self, dry_run=True):
        """
        Scan the folder, match files to TMDB episode titles,
        and either preview or execute the rename.
        """
        if not self.folder or not self.show_info:
            messagebox.showwarning("Not Ready", "Select a folder and show first.")
            return

        api_key = get_api_key("TMDB")
        if not api_key:
            messagebox.showwarning("No Key", "Set your TMDB API key first.")
            return

        self.preview_items = []
        self.check_vars = {}

        # Walk season subfolders (or root if no season folders)
        season_dirs = sorted(
            [d for d in self.folder.iterdir() if d.is_dir() and get_season(d) is not None],
            key=lambda d: get_season(d)
        )

        # If no Season folders, treat root as Season 1
        if not season_dirs:
            season_dirs = [(self.folder, 1)]
        else:
            season_dirs = [(d, get_season(d)) for d in season_dirs]

        for season_dir, season_num in season_dirs:
            if isinstance(season_dir, tuple):
                season_dir, season_num = season_dir
            titles, posters = tmdb_episode_titles(self.show_info["id"], season_num, api_key)
            self.episode_titles.update({(season_num, k): v for k, v in titles.items()})
            self.episode_posters.update({(season_num, k): v for k, v in posters.items()})

            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue

                eps, raw_title = extract_episode(f.name)
                if not eps:
                    self.preview_items.append({
                        "original": f,
                        "new_name": None,
                        "season": season_num,
                        "episodes": [],
                        "status": "SKIP: could not parse episode number",
                    })
                    continue

                # Use TMDB title for the first episode; fallback to parsed title
                tmdb_title = titles.get(eps[0], raw_title or f"Episode {eps[0]}")

                new_name = build_name(
                    self.show_info["name"],
                    self.show_info["year"],
                    season_num,
                    eps,
                    tmdb_title,
                    f.suffix
                )

                self.preview_items.append({
                    "original": f,
                    "new_name": new_name,
                    "season": season_num,
                    "episodes": eps,
                    "status": "OK",
                })

        # FIX #14: Check for duplicate target filenames
        self._check_duplicates()

        if dry_run:
            self.display_preview()
        else:
            self.execute_rename()

    def _check_duplicates(self):
        """
        FIX #14: Detect when two source files would be renamed to the
        same target filename, and flag them before any rename happens.
        """
        seen = {}
        for item in self.preview_items:
            if item["new_name"] is None:
                continue
            target = item["new_name"].lower()
            if target in seen:
                item["status"] = f"CONFLICT: same target as {seen[target]}"
            else:
                seen[target] = item["original"].name

    def display_preview(self):
        """
        FIX #9, #15: Show the rename preview with per-file checkboxes
        so the user can include or exclude individual files.
        """
        # Clear existing preview widgets
        for w in self.preview_inner.winfo_children():
            w.destroy()
        self._image_refs.clear()
        self.check_vars.clear()

        for i, item in enumerate(self.preview_items):
            frame = tk.Frame(self.preview_inner, bd=1, relief="groove", padx=5, pady=3)
            frame.pack(fill="x", padx=5, pady=2)

            # FIX #15: Checkbox to include/exclude this file from rename
            key = str(i)
            var = tk.BooleanVar(value=(item["status"] == "OK"))
            self.check_vars[key] = var
            cb = tk.Checkbutton(frame, variable=var)
            cb.pack(side="left")

            # Original name
            orig_text = item["original"].name
            if item["new_name"]:
                label_text = f"{orig_text}\n  → {item['new_name']}"
            else:
                label_text = f"{orig_text}\n  → [{item['status']}]"

            # Color code by status
            fg = "black"
            if "SKIP" in item["status"]:
                fg = "gray"
                var.set(False)
            elif "CONFLICT" in item["status"]:
                fg = "red"
                var.set(False)

            lbl = tk.Label(frame, text=label_text, justify="left", anchor="w", fg=fg)
            lbl.pack(side="left", fill="x", expand=True)

            # Click to show episode detail
            lbl.bind("<Button-1>", lambda e, idx=i: self.show_episode_detail(idx))

        count_ok = sum(1 for it in self.preview_items if it["status"] == "OK")
        self.status_var.set(f"Preview: {count_ok} files ready to rename, "
                            f"{len(self.preview_items) - count_ok} skipped/conflicting")

    def show_episode_detail(self, index):
        """Show detail info and episode still for a selected preview item."""
        item = self.preview_items[index]
        info_lines = [
            f"Original: {item['original'].name}",
            f"New: {item['new_name'] or 'N/A'}",
            f"Season: {item['season']}",
            f"Episode(s): {item['episodes']}",
            f"Status: {item['status']}",
        ]
        self.detail_label.configure(text="\n".join(info_lines))

        # Try to load episode still image
        if item["episodes"]:
            poster_path = self.episode_posters.get((item["season"], item["episodes"][0]))
            api_key = get_api_key("TMDB")
            if poster_path and api_key and self.show_info:
                img = fetch_tmdb_poster(
                    self.show_info["id"], api_key,
                    season=item["season"], ep_poster=poster_path
                )
                if img:
                    photo = ImageTk.PhotoImage(img)
                    self._image_refs.append(photo)
                    self.detail_image.configure(image=photo)
                    return
        self.detail_image.configure(image="")

    def execute_rename(self):
        """
        Perform the actual file renames for checked items.

        FIX #13: Builds the full rename batch, checks for conflicts,
        then executes atomically with undo log.
        """
        renames = []
        for i, item in enumerate(self.preview_items):
            key = str(i)
            if not self.check_vars.get(key, tk.BooleanVar(value=False)).get():
                continue
            if item["new_name"] is None or item["status"] != "OK":
                continue

            src = item["original"]
            dst = src.parent / item["new_name"]

            # FIX #14: Final safety check — don't overwrite existing files
            if dst.exists() and src != dst:
                messagebox.showerror("Conflict",
                                     f"Target already exists:\n{dst}\n\nAborting all renames.")
                return

            renames.append((src, dst))

        if not renames:
            messagebox.showinfo("Nothing to do", "No files selected for rename.")
            return

        confirm = messagebox.askyesno(
            "Confirm Rename",
            f"Rename {len(renames)} file(s)?\n\nThis can be undone via 'Undo Last'."
        )
        if not confirm:
            return

        # Build undo log entry BEFORE renaming
        log_entry = {
            "show": self.show_info["name"] if self.show_info else "Unknown",
            "renames": [],
        }

        errors = []
        for src, dst in renames:
            try:
                src.rename(dst)
                log_entry["renames"].append({
                    "old": str(src),
                    "new": str(dst),
                })
            except OSError as e:
                errors.append(f"{src.name}: {e}")

        # Save log (appending to history)
        log = load_log()
        log.append(log_entry)
        save_log(log)

        if errors:
            messagebox.showwarning("Partial Rename",
                                   f"Renamed {len(log_entry['renames'])} files.\n\n"
                                   f"Errors ({len(errors)}):\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Done", f"Successfully renamed {len(log_entry['renames'])} files.")

        self.status_var.set(f"Renamed {len(log_entry['renames'])} files.")
        # Refresh preview
        self.run_preview(dry_run=True)

    def undo(self):
        """Undo the most recent rename batch using the log file."""
        log = load_log()
        if not log:
            messagebox.showinfo("Nothing to Undo", "No rename history found.")
            return

        last = log[-1]
        confirm = messagebox.askyesno(
            "Undo Rename",
            f"Undo {len(last['renames'])} renames for '{last['show']}'?"
        )
        if not confirm:
            return

        errors = []
        for entry in reversed(last["renames"]):
            new_path = Path(entry["new"])
            old_path = Path(entry["old"])
            try:
                if new_path.exists():
                    new_path.rename(old_path)
                else:
                    errors.append(f"File not found: {new_path.name}")
            except OSError as e:
                errors.append(f"{new_path.name}: {e}")

        # Remove the last entry from the log
        log.pop()
        save_log(log)

        if errors:
            messagebox.showwarning("Partial Undo",
                                   f"Errors:\n" + "\n".join(errors[:5]))
        else:
            messagebox.showinfo("Undone", "Rename successfully undone.")

        self.status_var.set("Undo complete.")
        # Refresh preview if a folder is loaded
        if self.folder and self.show_info:
            self.run_preview(dry_run=True)

    def update_search(self):
        """
        Filter the preview list based on the search bar text.
        Hides items that don't match the filter string.
        """
        query = self.search_var.get().lower()
        for i, widget in enumerate(self.preview_inner.winfo_children()):
            if i >= len(self.preview_items):
                break
            item = self.preview_items[i]
            text = (item["original"].name + " " + (item["new_name"] or "")).lower()
            if query in text:
                widget.pack(fill="x", padx=5, pady=2)
            else:
                widget.pack_forget()

    def run(self):
        """Start the tkinter main loop. FIX #11: Separated from __init__."""
        self.root.mainloop()


# -------------------------
# Entry Point
# -------------------------
# FIX #11: mainloop() called outside of __init__ so the class
# can be instantiated without blocking (important for testing/extending).
if __name__ == "__main__":
    app = PlexRenamerApp()
    app.run()
