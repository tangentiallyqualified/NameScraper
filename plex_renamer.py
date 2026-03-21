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

# Tokens commonly found in release-group folder names that are NOT part
# of the show title. Matched case-insensitively. Order doesn't matter —
# we stop at the first token that matches to avoid eating title words.
_RELEASE_NOISE = re.compile(
    r"""
    (?:^|[ .\-_])                     # preceded by separator or start
    (?:
        # --- Resolution ---
        \d{3,4}[pi]                   # 480p, 720p, 1080p, 1080i, 2160p
        |4K|UHD
        # --- Source ---
        |Blu[\- .]?Ray|BDRip|BRRip|BDMV
        |WEB[\- .]?(?:DL|Rip)|WEBRip|HDTV|DVDRip|DVD|SDTV
        |AMZN|DSNP|ATVP|NF|HULU|HMAX|PMTP|iT
        # --- Video codec ---
        |[xh][\.]?26[45]|HEVC|AVC|AV1|MPEG[24]?|VP9|10[\- .]?Bit
        # --- Audio ---
        |AAC(?:[ .\-]?\d\.\d)?|AC3|EAC3|DTS(?:[\- .]?HD)?(?:[\- .]?MA)?
        |TrueHD|Atmos|FLAC|LPCM|Opus
        |(?:Dual|Multi)[\- .]?Audio|[257]\.\d
        # --- Release tags ---
        |REMUX|REPACK|PROPER|iNTERNAL|EXTENDED|UNCUT|DC|THEATRICAL
        |HQ|LQ|SDR|HDR(?:10)?(?:\+)?|DV|DoVi
        |COMPLETE
        # --- Season indicators (not part of the show title) ---
        |S\d{1,2}(?:[\-]S\d{1,2})?(?:E\d{1,3})?
        # --- General noise after a dash (release group name) ---
        # e.g. "-iAHD", "-SPARKS", "-FGT"
    )
    (?=[ .\-_]|$)                     # followed by separator or end
    """,
    re.IGNORECASE | re.VERBOSE
)

# The trailing release group after the last hyphen, e.g. "-iAHD"
_TRAILING_GROUP = re.compile(r"-[A-Za-z0-9]{2,10}$")


def clean_folder_name(name):
    """
    Extract a human-readable show title from a release-group style
    folder name like:
        Dragon.Ball.Super.1080p.Blu-Ray.10-Bit.Dual-Audio.TrueHD.x265-iAHD

    Strategy:
      1. Replace dots/underscores with spaces
      2. Remove bracketed tags [group] and (tags)
      3. Strip the trailing release group after the last hyphen
      4. Walk tokens left-to-right; stop at the first release-noise token
      5. Everything before that noise token is the show title
      6. If a 4-digit year is found, preserve it in parentheses

    Returns the cleaned show name string.
    """
    # Step 1: Replace dots and underscores with spaces
    s = name.replace(".", " ").replace("_", " ")

    # Step 2: Remove bracketed/parenthesized tags
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"\(.*?\)", "", s)

    # Step 3: Strip trailing release group (e.g. "-iAHD")
    s = _TRAILING_GROUP.sub("", s)

    # Step 4: Walk tokens and stop at the first noise match
    tokens = s.split()
    title_tokens = []
    for token in tokens:
        # Check if this token (with surrounding context) is noise
        if _RELEASE_NOISE.search(f" {token} "):
            break
        title_tokens.append(token)

    title = " ".join(title_tokens).strip()

    # Step 5: If we got nothing useful, fall back to the full cleaned string
    if len(title) < 2:
        title = re.sub(r"\s+", " ", s).strip()

    # Step 6: Try to extract a year from the original name and format
    # it consistently as "(YYYY)" appended to the title.
    year_match = re.search(r"(?:^|[.\s(\-])(\d{4})(?=[.\s)\-]|$)", name)
    if year_match:
        year = year_match.group(1)
        yr = int(year)
        if 1950 <= yr <= 2030:
            # Remove bare year from title if it leaked through as a token
            title = re.sub(r"\s*\(?\b" + year + r"\b\)?\s*", " ", title).strip()
            title = f"{title} ({year})"

    # Collapse spaces
    return re.sub(r"\s+", " ", title).strip()


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
        is_season_relative: bool — True if the number came from an S##E##
            pattern (guaranteed season-relative), False if it came from a
            bare-number or dash-delimited pattern (likely absolute for
            anime and other series with continuous numbering).

    FIX #1: S##E## pattern is tried first — it's the most reliable.
    FIX #2: Multi-episode patterns like S01E01E02 and S01E01-E02 are handled.
    """
    name = clean_name(Path(filename).stem)

    # --- Pattern 1 (BEST): S##E## with optional multi-episode ---
    # Matches: S01E05, S01E05E06, S01E05-E06, S1E5
    # These numbers are ALWAYS season-relative by convention.
    m = re.search(r"S(\d+)E(\d+)(?:[E-]?E?(\d+))?\s*[-.]?\s*(.*)", name, re.IGNORECASE)
    if m:
        eps = [int(m.group(2))]
        if m.group(3):
            eps.append(int(m.group(3)))
        title = m.group(4).strip() if m.group(4) else None
        return eps, title, True  # season-relative

    # --- Pattern 2: Dash-delimited " - 05 - Title" (common in organized releases) ---
    # These are typically ABSOLUTE episode numbers (e.g. anime fansubs).
    m = re.search(r"-\s*(\d{1,3})\s*-\s*(.*)", name)
    if m:
        return [int(m.group(1))], m.group(2).strip(), False  # likely absolute

    # --- Pattern 3: Episode number preceded by space/separator ---
    # Only match 1-3 digit numbers that DON'T look like a year (1900-2099)
    # or a resolution (480, 720, 1080, 2160). FIX #1: avoids false positives.
    # These are also typically absolute numbers.
    m = re.search(r"(?<!\d)(?:ep?|episode)?\s*(\d{1,3})(?!\d)(?:\s*[-._]+\s*(.*))?", name, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        # Reject numbers that look like years or resolutions
        if num not in (480, 720, 1080, 2160) and not (1900 <= num <= 2099):
            title = m.group(2).strip() if m.group(2) else None
            return [num], title, False  # likely absolute

    return [], None, False


def get_season(folder):
    """
    Extract the season number from a folder name.

    Recognizes many common formats:
      - "Season 02", "Season02", "season 2"
      - "S02", "s2"
      - "Show Name S02", "Show Name (2004) S02"
      - "Staffel 3" (German)
      - "Saison 3" (French)
      - Bare number folders: "02", "2" (only 1-2 digits)
      - "Season 00", "S00" → 0
      - Specials/extras folders → 0 (mapped to Plex Season 00)

    Returns the season number as an int, or None if not found.
    """
    name = folder.name

    # Pattern 0: Specials / extras folders → Season 0
    # These map to Plex's "Season 00" (Specials) convention.
    _specials = re.compile(
        r"^(?:"
        r"specials?|extras?|bonus|behind[\s._\-]*the[\s._\-]*scenes"
        r"|deleted[\s._\-]*scenes|featurettes?|shorts?"
        r"|OVAs?|OADs?|ONAs?|movies?"
        r"|special[\s._\-]*features?"
        r"|Season[\s._\-]*0+(?:[\s._\-]|$)"  # "Season 0", "Season 00"
        r")$",
        re.IGNORECASE
    )
    # Check if the ENTIRE folder name is a specials keyword,
    # or if it ends with one after the show name prefix
    if _specials.match(name.strip()):
        return 0
    # Also match "Show Name - Specials" or "Show Name Extras"
    if re.search(
        r"[\s._\-](?:specials?|extras?|bonus|OVAs?|OADs?|ONAs?|"
        r"special[\s._\-]*features?|featurettes?|shorts?)$",
        name, re.IGNORECASE
    ):
        return 0

    # Pattern 1: "Season ##" anywhere in the name
    m = re.search(r"season\s*(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Pattern 2: "S##" as a standalone token (not part of a longer word)
    # Handles: "S02", "Show Name S02", "Show Name (2004) S02"
    m = re.search(r"(?:^|[\s._\-])S(\d{1,2})(?:[\s._\-]|$)", name)
    if m:
        return int(m.group(1))

    # Pattern 3: International variants
    m = re.search(r"(?:staffel|saison|temporada|stagione)\s*(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Pattern 4: Bare number folder (e.g. "01", "2") — only if the
    # entire folder name is just 1-2 digits
    m = re.fullmatch(r"(\d{1,2})", name.strip())
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


def build_name(show, year, season, episodes, titles, ext):
    """
    Build a Plex-compatible episode filename.

    Supports multi-episode files with proper formatting:
      Single:  Show (2004) - S01E01 - Pilot.mkv
      Multi:   Show (2004) - S01E01-E02 - Title 1-Title 2.mkv

    Args:
        show: Show name string
        year: Year string or empty
        season: Season number (int)
        episodes: List of episode numbers
        titles: List of episode title strings (one per episode),
                or a single string for backward compatibility
        ext: File extension including the dot
    """
    year_part = f" ({year})" if year else ""

    # Episode number part: S01E01 or S01E01-E02
    if len(episodes) == 1:
        ep_part = f"E{episodes[0]:02d}"
    else:
        ep_part = "-".join(f"E{ep:02d}" for ep in episodes)

    # Title part: combine multiple titles with a dash
    if isinstance(titles, str):
        title_part = titles
    elif len(titles) == 1:
        title_part = titles[0]
    else:
        # Deduplicate if all titles are the same (e.g. both parts named "Rising")
        unique = list(dict.fromkeys(titles))  # preserves order
        title_part = "-".join(unique)

    raw = f"{show}{year_part} - S{season:02d}{ep_part} - {title_part}{ext}"
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


def fetch_tmdb_poster(tmdb_id, api_key, season=None, ep_poster=None, target_width=300):
    """
    Fetch a poster/still image from TMDB.

    Priority: episode still -> season poster -> show poster.
    Returns a PIL Image object scaled to target_width, or None.
    """
    base = "https://image.tmdb.org/t/p/w500"
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
            # Scale to target width while preserving aspect ratio
            scale = target_width / img.width
            new_h = int(img.height * scale)
            img = img.resize((target_width, new_h), Image.LANCZOS)
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
        # --- Windows DPI awareness (must be set BEFORE creating Tk) ---
        # Without this, Windows UI scaling (125%, 150%, etc.) causes
        # blurry text and incorrect layout measurements.
        try:
            import ctypes
            # Per-monitor DPI aware (Windows 8.1+)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                # Fallback: system DPI aware (Windows Vista+)
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass  # Not on Windows, or old version — skip

        self.root = tk.Tk()
        self.root.title("Plex Renamer")

        # Tkinter's tk scaling tells us the ratio of pixels to "points".
        # On a 96 DPI display this is 1.0; at 150% Windows scaling it's ~1.5.
        # winfo_screenwidth/height return values in tk's coordinate space,
        # which may already be divided by the scale factor. We use these
        # directly for geometry (since geometry uses the same coordinate
        # space) but remove the hard pixel cap that was preventing the
        # window from being large enough on high-DPI screens.
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        # Use 92% of screen width and 85% of height — leaves room for
        # the taskbar which winfo_screenheight includes in its measurement.
        win_w = int(screen_w * 0.92)
        win_h = int(screen_h * 0.85)

        # Center horizontally, pin near the top vertically.
        # winfo_screenheight() includes the taskbar, so centering
        # vertically pushes the bottom of the window behind it.
        # A small top offset (10px) keeps the title bar accessible.
        x = (screen_w - win_w) // 2
        y = 10
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(760, 500)

        # Detect the DPI scale factor so we can size custom-drawn elements
        # (checkboxes, dialog windows) correctly on high-DPI displays.
        # tk scaling returns pixels-per-point; base is ~1.0 at 96 DPI.
        try:
            self.dpi_scale = self.root.tk.call("tk", "scaling")
            if self.dpi_scale < 1.0:
                self.dpi_scale = 1.0
        except Exception:
            self.dpi_scale = 1.0

        # State
        self.folder = None
        self.show_info = None
        self.episode_titles = {}
        self.episode_posters = {}
        self.preview_items = []
        self._image_refs = []          # Episode still images (cleared on refresh)
        self._poster_ref = None        # Show poster image (never cleared by preview)
        self.check_vars = {}
        self._selected_index = None

        # --- Color palette: dark cinema theme ---
        self.colors = {
            "bg_dark":      "#0f0f0f",
            "bg_mid":       "#1a1a1a",
            "bg_card":      "#222222",
            "bg_card_hover":"#2a2a2a",
            "bg_input":     "#2c2c2c",
            "border":       "#333333",
            "border_light": "#444444",
            "text":         "#e8e8e8",
            "text_dim":     "#888888",
            "text_muted":   "#555555",
            "accent":       "#e5a00d",     # Plex gold
            "accent_hover": "#f0b429",
            "accent_dim":   "#7a5a10",
            "success":      "#3ea463",
            "error":        "#d44040",
            "info":         "#4a9eda",
            "move":         "#6c8ebf",
            # Badge colors for episode types
            "badge_multi_bg":   "#2d1f4e",     # Deep purple bg
            "badge_multi_fg":   "#b48efa",     # Soft purple text
            "badge_multi_bd":   "#4a3370",     # Purple border
            "badge_special_bg": "#1a3a2a",     # Deep teal bg
            "badge_special_fg": "#5ec4a0",     # Teal text
            "badge_special_bd": "#2a5e45",     # Teal border
        }
        c = self.colors

        # Configure root
        self.root.configure(bg=c["bg_dark"])
        self.root.option_add("*Font", "Helvetica 11")

        # --- Configure ttk styles ---
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
        style.configure("Card.TLabel", background=c["bg_card"],
                         foreground=c["text"])
        style.configure("CardDim.TLabel", background=c["bg_card"],
                         foreground=c["text_dim"], font=("Helvetica", 10))
        style.configure("Detail.TLabel", background=c["bg_mid"],
                         foreground=c["text"])
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

        style.configure("Small.TButton", font=("Helvetica", 10),
                         padding=(10, 5))

        # Entry
        style.configure("TEntry", padding=(8, 6), font=("Helvetica", 11))

        # Combobox — both the widget and its dropdown Listbox
        style.configure("TCombobox", padding=(8, 6),
                         fieldbackground=c["bg_input"],
                         background=c["bg_card"],
                         foreground=c["text"],
                         arrowcolor=c["text_dim"])
        style.map("TCombobox",
                   fieldbackground=[("readonly", c["bg_input"]),
                                     ("readonly focus", c["bg_input"])],
                   foreground=[("readonly", c["text"])],
                   selectbackground=[("readonly", c["accent_dim"])],
                   selectforeground=[("readonly", c["text"])])
        # The dropdown Listbox is a Tk widget — style via option_add
        self.root.option_add("*TCombobox*Listbox.background", c["bg_input"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["bg_dark"])
        self.root.option_add("*TCombobox*Listbox.font", "Helvetica 11")
        self.root.option_add("*TCombobox*Listbox.borderWidth", "0")
        self.root.option_add("*TCombobox*Listbox.highlightThickness", "0")

        # Checkbutton — custom indicator images for usable size on high-DPI
        # ttk's native checkbox is tiny on Windows with DPI scaling.
        # Scale the checkbox size with the DPI factor.
        check_size = max(20, int(18 * self.dpi_scale))
        self._check_imgs = self._create_checkbox_images(c, size=check_size)
        style.element_create("custom_check", "image", self._check_imgs["unchecked"],
                              ("selected", self._check_imgs["checked"]),
                              sticky="w")
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

        # Scrollbar — scale width with DPI for usability
        sb_width = max(14, int(12 * self.dpi_scale))
        style.configure("TScrollbar", background=c["bg_mid"],
                         troughcolor=c["bg_dark"], borderwidth=0,
                         arrowcolor=c["text_dim"], width=sb_width,
                         arrowsize=sb_width)

        # Separator
        style.configure("TSeparator", background=c["border"])

        # =====================================================================
        # LAYOUT
        # =====================================================================

        # --- Header bar ---
        header = ttk.Frame(self.root, style="Mid.TFrame")
        header.pack(fill="x", padx=0, pady=0)

        header_inner = ttk.Frame(header, style="Mid.TFrame")
        header_inner.pack(fill="x", padx=20, pady=(16, 12))

        # App title + show info
        title_area = ttk.Frame(header_inner, style="Mid.TFrame")
        title_area.pack(side="left")

        ttk.Label(title_area, text="PLEX RENAMER", style="Title.TLabel",
                  background=c["bg_mid"]).pack(anchor="w")

        self.show_label_var = tk.StringVar(value="No show selected")
        ttk.Label(title_area, textvariable=self.show_label_var,
                  style="Subtitle.TLabel",
                  background=c["bg_mid"]).pack(anchor="w", pady=(2, 0))

        # Header buttons (right side)
        btn_area = ttk.Frame(header_inner, style="Mid.TFrame")
        btn_area.pack(side="right")

        ttk.Button(btn_area, text="API Keys",
                   command=self.manage_keys,
                   style="Small.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(btn_area, text="Undo Last",
                   command=self.undo,
                   style="Small.TButton").pack(side="left", padx=(0, 8))

        # Separator
        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

        # --- Action bar (two-row grid for proper scaling) ---
        action_bar = ttk.Frame(self.root)
        action_bar.pack(fill="x", padx=20, pady=(10, 6))
        # Column 0 stretches to absorb extra space (filter entry lives here)
        action_bar.columnconfigure(2, weight=1)

        # Row 0: Folder selector, order dropdown, filter
        ttk.Button(action_bar, text="Select Show Folder",
                   command=self.pick_folder,
                   style="TButton").grid(row=0, column=0, padx=(0, 8), sticky="w")

        order_frame = ttk.Frame(action_bar)
        order_frame.grid(row=0, column=1, padx=(0, 8), sticky="w")
        ttk.Label(order_frame, text="Order:",
                  foreground=c["text_dim"]).pack(side="left", padx=(0, 4))
        self.order_var = tk.StringVar(value="aired")
        ttk.Combobox(order_frame, textvariable=self.order_var,
                      values=["aired", "dvd", "absolute"],
                      width=9, state="readonly").pack(side="left")

        search_frame = ttk.Frame(action_bar)
        search_frame.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(search_frame, text="Filter:",
                  foreground=c["text_dim"]).pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True)
        self.search_var.trace_add("write", lambda *_: self.update_search())

        # Row 1: Selection controls (left) + action buttons (right)
        # Small vertical gap between rows
        sel_frame = ttk.Frame(action_bar)
        sel_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.tally_var = tk.StringVar(value="0 / 0")
        ttk.Label(sel_frame, textvariable=self.tally_var,
                  foreground=c["accent"],
                  font=("Helvetica", 11, "bold")).pack(side="left", padx=(0, 4))
        ttk.Label(sel_frame, text="selected",
                  foreground=c["text_dim"],
                  font=("Helvetica", 10)).pack(side="left", padx=(0, 10))
        ttk.Button(sel_frame, text="Select All",
                   command=self.select_all,
                   style="Small.TButton").pack(side="left")

        btn_frame = ttk.Frame(action_bar)
        btn_frame.grid(row=1, column=2, sticky="e", pady=(8, 0))

        ttk.Button(btn_frame, text="Refresh",
                   command=lambda: self.run_preview(dry_run=True),
                   style="TButton").pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="Rename Files",
                   command=self.execute_rename,
                   style="Accent.TButton").pack(side="left")

        # --- Main content area (split: file list + detail panel) ---
        content = ttk.Frame(self.root)
        content.pack(fill="both", expand=True, padx=20, pady=(0, 0))
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
        self.preview_inner = ttk.Frame(self.preview_canvas)
        self.preview_inner.bind(
            "<Configure>",
            lambda e: self.preview_canvas.configure(
                scrollregion=self.preview_canvas.bbox("all")
            )
        )
        self.preview_canvas.create_window((0, 0), window=self.preview_inner,
                                           anchor="nw")
        self.preview_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.preview_canvas.pack(side="left", fill="both", expand=True)

        # Sync the inner frame width to the canvas width so cards
        # packed with fill="x" stretch to the full available width,
        # eliminating the gap between the cards and the scrollbar.
        def _sync_preview_width(event):
            self.preview_canvas.itemconfig(
                self.preview_canvas.find_all()[0], width=event.width
            )
        self.preview_canvas.bind("<Configure>", _sync_preview_width)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            self.preview_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.preview_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        # Linux scroll support
        self.preview_canvas.bind_all("<Button-4>",
                                      lambda e: self.preview_canvas.yview_scroll(-3, "units"))
        self.preview_canvas.bind_all("<Button-5>",
                                      lambda e: self.preview_canvas.yview_scroll(3, "units"))

        # Right: detail / poster panel (scrollable to prevent overflow)
        detail_panel = ttk.Frame(content, style="Mid.TFrame")
        detail_panel.grid(row=0, column=1, sticky="nsew")

        # Scrollable container for the detail panel — prevents content
        # (poster + detail text + episode still) from running off the
        # bottom of the window on smaller or scaled displays.
        detail_canvas = tk.Canvas(detail_panel, bg=c["bg_mid"],
                                   highlightthickness=0, bd=0)
        detail_scrollbar = ttk.Scrollbar(detail_panel, orient="vertical",
                                          command=detail_canvas.yview)
        self.detail_inner = ttk.Frame(detail_canvas, style="Mid.TFrame")
        self.detail_inner.bind(
            "<Configure>",
            lambda e: detail_canvas.configure(
                scrollregion=detail_canvas.bbox("all")
            )
        )
        detail_canvas.create_window((0, 0), window=self.detail_inner,
                                     anchor="nw")
        detail_canvas.configure(yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.pack(side="right", fill="y")
        detail_canvas.pack(side="left", fill="both", expand=True)

        # Sync detail_inner width to the canvas so content fills horizontally
        def _sync_detail_width(event):
            detail_canvas.itemconfig(
                detail_canvas.find_all()[0], width=event.width
            )
        detail_canvas.bind("<Configure>", _sync_detail_width)

        # Mousewheel scrolling for detail panel
        def _detail_mousewheel(event):
            detail_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        detail_canvas.bind("<Enter>",
                            lambda e: detail_canvas.bind_all("<MouseWheel>", _detail_mousewheel))
        detail_canvas.bind("<Leave>",
                            lambda e: detail_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        # Linux scroll for detail panel
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

        # Detail panel content (inside scrollable frame)
        pad = ttk.Frame(self.detail_inner, style="Mid.TFrame")
        pad.pack(fill="both", expand=True, padx=16, pady=16)

        # Show poster at top of detail panel — centered
        self.show_poster_label = ttk.Label(pad, style="Detail.TLabel",
                                            background=c["bg_mid"])
        self.show_poster_label.pack(anchor="center", fill="x", pady=(0, 12))

        ttk.Separator(pad, orient="horizontal").pack(fill="x", pady=8)

        # Episode detail section
        ttk.Label(pad, text="EPISODE DETAIL",
                  style="DetailDim.TLabel",
                  font=("Helvetica", 9, "bold")).pack(anchor="w", fill="x", pady=(8, 6))

        # wraplength is set dynamically when the panel resizes
        self.detail_label = ttk.Label(pad, text="Click an episode to view details",
                                       style="Detail.TLabel",
                                       wraplength=260, justify="left")
        self.detail_label.pack(anchor="w", fill="x")

        self.detail_image = ttk.Label(pad, style="Detail.TLabel",
                                       background=c["bg_mid"])
        self.detail_image.pack(anchor="center", fill="x", pady=(12, 0))

        # Dynamically adjust wraplength and image sizes when panel resizes
        def _on_detail_resize(event):
            available = event.width - 40  # account for padding
            if available > 100:
                self.detail_label.configure(wraplength=available)
        pad.bind("<Configure>", _on_detail_resize)

        # --- Status bar ---
        status_bar = ttk.Frame(self.root, style="Mid.TFrame")
        status_bar.pack(fill="x", side="bottom")

        self.status_var = tk.StringVar(value="Ready — select a show folder to begin")
        ttk.Label(status_bar, textvariable=self.status_var,
                  style="Status.TLabel").pack(fill="x")

    # ------------------------------------------------------------------
    # FIX #9: All GUI methods fully implemented below
    # ------------------------------------------------------------------

    @staticmethod
    def _create_checkbox_images(colors, size=18):
        """
        Draw custom checkbox indicator images at the given size.
        Returns a dict with 'checked' and 'unchecked' PhotoImage objects.
        These are used as ttk Checkbutton indicators so the checkboxes
        are a usable size on high-DPI Windows displays.
        """
        from PIL import ImageDraw

        # Unchecked: rounded square outline
        img_off = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw_off = ImageDraw.Draw(img_off)
        # Parse the border color
        border = colors["border_light"]
        draw_off.rounded_rectangle([1, 1, size - 2, size - 2],
                                    radius=3, outline=border, width=2)

        # Checked: filled rounded square with a checkmark
        img_on = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw_on = ImageDraw.Draw(img_on)
        accent = colors["accent"]
        draw_on.rounded_rectangle([1, 1, size - 2, size - 2],
                                   radius=3, fill=accent)
        # Draw a checkmark in dark color
        dark = colors["bg_dark"]
        # Checkmark path scaled to the box size
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
        """
        Create a properly sized and centered Toplevel dialog window.
        Accounts for DPI scaling so dialogs aren't squished on high-DPI
        displays. Centers the dialog over the main window.
        """
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=c["bg_mid"])
        win.transient(self.root)
        win.grab_set()

        # Scale dimensions with DPI
        scaled_w = int(width * self.dpi_scale)
        scaled_h = int(height * self.dpi_scale)

        # Center over the main window
        self.root.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        x = root_x + (root_w - scaled_w) // 2
        y = root_y + (root_h - scaled_h) // 2
        # Keep on screen
        x = max(0, x)
        y = max(0, y)

        win.geometry(f"{scaled_w}x{scaled_h}+{x}+{y}")
        win.minsize(scaled_w, scaled_h)
        return win

    def manage_keys(self):
        """Dialog to set/update TMDB and TVDB API keys via OS keyring."""
        c = self.colors
        win = self._create_dialog("API Keys", width=480, height=200)

        ttk.Label(win, text="API KEY MANAGER", style="Title.TLabel",
                  font=("Helvetica", 14, "bold"),
                  background=c["bg_mid"]).pack(anchor="w", padx=20, pady=(16, 12))

        for service in ["TMDB", "TVDB"]:
            row = ttk.Frame(win, style="Mid.TFrame")
            row.pack(fill="x", padx=20, pady=4)

            ttk.Label(row, text=f"{service}:", width=6,
                      background=c["bg_mid"],
                      foreground=c["text_dim"]).pack(side="left")
            var = tk.StringVar(value=get_api_key(service) or "")
            entry = ttk.Entry(row, textvariable=var, width=36, show="*")
            entry.pack(side="left", padx=(8, 8), fill="x", expand=True)
            ttk.Button(row, text="Save", style="Small.TButton",
                       command=lambda s=service, v=var: self._save_key(s, v.get(), win)
                       ).pack(side="left")

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

        # Use the folder name as the initial search query, cleaned of
        # release-group noise (codecs, resolution, source, group tags).
        show_name = self.folder.name
        show_name_clean = clean_folder_name(show_name)
        # Also strip a trailing year for the search query (TMDB handles
        # year matching better as a separate parameter)
        search_query = re.sub(r"\s*\(\d{4}\)\s*$", "", show_name_clean).strip()

        results = tmdb_search_show(search_query, api_key)
        if not results:
            # Let the user manually enter a show name if auto-detection failed
            manual = simpledialog.askstring(
                "Show Not Found",
                f"No TMDB results for '{search_query}'.\n\n"
                f"(Extracted from: {show_name})\n\n"
                f"Enter the show name manually:",
                parent=self.root
            )
            if manual and manual.strip():
                results = tmdb_search_show(manual.strip(), api_key)
            if not results:
                return

        # FIX #7: Let the user pick from the search results
        self.show_info = self._pick_show_dialog(results)
        if not self.show_info:
            return

        # Display show poster
        self._display_show_poster()
        self.show_label_var.set(f"{self.show_info['name']} ({self.show_info['year']})")
        self.status_var.set(f"Scanning files...")

        # Auto-preview after folder selection
        self.root.update_idletasks()
        self.run_preview(dry_run=True)

    def _pick_show_dialog(self, results):
        """
        Present a dialog with all TMDB search results so the user
        can pick the correct show.
        """
        if len(results) == 1:
            return results[0]

        c = self.colors
        win = self._create_dialog("Select Show", width=520, height=400)

        ttk.Label(win, text="SELECT SHOW", style="Title.TLabel",
                  font=("Helvetica", 14, "bold"),
                  background=c["bg_mid"]).pack(anchor="w", padx=20, pady=(16, 4))
        ttk.Label(win, text="Multiple matches found — select the correct one:",
                  style="Subtitle.TLabel",
                  background=c["bg_mid"]).pack(anchor="w", padx=20, pady=(0, 12))

        listbox = tk.Listbox(win, width=70, height=12,
                              bg=c["bg_card"], fg=c["text"],
                              selectbackground=c["accent"],
                              selectforeground=c["bg_dark"],
                              font=("Helvetica", 11),
                              borderwidth=0, highlightthickness=1,
                              highlightcolor=c["border_light"],
                              highlightbackground=c["border"])
        listbox.pack(padx=20, pady=(0, 12), fill="both", expand=True)

        for i, show in enumerate(results):
            year = f" ({show['year']})" if show['year'] else ""
            listbox.insert(i, f"  {show['name']}{year}")

        listbox.selection_set(0)
        selected = [None]

        def on_ok():
            sel = listbox.curselection()
            if sel:
                selected[0] = results[sel[0]]
            win.destroy()

        ttk.Button(win, text="Confirm Selection", command=on_ok,
                   style="Accent.TButton").pack(pady=(0, 16))
        self.root.wait_window(win)
        return selected[0]

    def _display_show_poster(self):
        """Fetch and display the show poster in the detail panel, sized to fit."""
        if not self.show_info:
            return
        api_key = get_api_key("TMDB")
        # Fetch at a generous width — will be displayed at panel width
        img = fetch_tmdb_poster(self.show_info["id"], api_key, target_width=400)
        if img:
            # Scale poster to fit the detail panel width (minus padding)
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

            photo = ImageTk.PhotoImage(img)
            self._poster_ref = photo
            self.show_poster_label.configure(image=photo)
        else:
            self.show_poster_label.configure(image="", text="(No poster)")

    def _fetch_tmdb_season_map(self, api_key):
        """
        Build a complete map of TMDB's season structure for this show.

        Returns:
            tmdb_seasons: dict of season_num -> {titles: {ep->title}, posters: {ep->path}, count: int}
            total_episodes: total episode count across all TMDB seasons (excluding season 0/specials)
        """
        # First, get the show details to find out how many seasons TMDB has
        try:
            r = requests.get(
                f"https://api.themoviedb.org/3/tv/{self.show_info['id']}",
                params={"api_key": api_key}, timeout=10
            )
            if not r.ok:
                return {}, 0
            show_data = r.json()
        except requests.RequestException:
            return {}, 0

        tmdb_seasons = {}
        total_episodes = 0

        for season_info in show_data.get("seasons", []):
            sn = season_info.get("season_number", 0)
            titles, posters = tmdb_episode_titles(self.show_info["id"], sn, api_key)
            count = max(titles.keys()) if titles else season_info.get("episode_count", 0)
            tmdb_seasons[sn] = {"titles": titles, "posters": posters, "count": count}
            # Don't count specials toward the total episode count
            # (used for season mismatch detection)
            if sn > 0:
                total_episodes += count

        return tmdb_seasons, total_episodes

    def _detect_season_mismatch(self, season_dirs, tmdb_seasons):
        """
        Detect whether the user's folder structure matches TMDB's seasons.

        A mismatch occurs when the user has season folders that TMDB
        doesn't recognize (e.g., user has Season 1 + Season 2 but TMDB
        has only Season 1 with all 64 episodes).

        Returns:
            mismatched: bool — True if folder structure doesn't match TMDB
            user_season_nums: set of season numbers from the user's folders
            tmdb_season_nums: set of season numbers from TMDB
        """
        user_season_nums = {sn for _, sn in season_dirs}
        tmdb_season_nums = set(tmdb_seasons.keys())

        # Exclude Season 0 (specials) from mismatch detection — specials
        # folders are handled separately and shouldn't trigger consolidation.
        extra_user_seasons = (user_season_nums - tmdb_season_nums) - {0}
        if extra_user_seasons:
            return True, user_season_nums, tmdb_season_nums

        return False, user_season_nums, tmdb_season_nums

    def _prompt_season_fix(self, user_season_nums, tmdb_season_nums, tmdb_seasons):
        """
        Prompt the user about the season structure mismatch and ask if
        they want to consolidate files into the correct TMDB structure.

        Returns True if the user accepts the fix, False otherwise.
        """
        extra = sorted(user_season_nums - tmdb_season_nums)
        tmdb_desc = ", ".join(
            f"Season {sn} ({tmdb_seasons[sn]['count']} eps)"
            for sn in sorted(tmdb_season_nums)
        )
        user_desc = ", ".join(f"Season {sn}" for sn in sorted(user_season_nums))

        msg = (
            f"Folder structure mismatch detected!\n\n"
            f"Your folders: {user_desc}\n"
            f"TMDB structure: {tmdb_desc}\n\n"
            f"TMDB does not have: {', '.join(f'Season {s}' for s in extra)}\n\n"
            f"Would you like to automatically fix this?\n"
            f"Files will be renamed with correct TMDB episode numbers "
            f"and moved into the proper TMDB season folder(s).\n\n"
            f"Empty folders will be removed after the move."
        )
        return messagebox.askyesno("Season Structure Mismatch", msg)

    def _build_absolute_file_list(self, season_dirs):
        """
        Collect ALL video files across all season folders, sorted by
        their absolute episode number (parsed from filename) or by
        folder order + filename order as a fallback.

        Returns a list of (file_path, parsed_absolute_ep, raw_title) tuples,
        sorted by absolute episode number.
        """
        all_files = []
        for season_dir, season_num in season_dirs:
            if isinstance(season_dir, tuple):
                season_dir, season_num = season_dir
            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                eps, raw_title, is_season_relative = extract_episode(f.name)
                # Use the parsed episode number for sorting; fall back to
                # a large number so unparseable files sort to the end
                abs_num = eps[0] if eps else 9999
                all_files.append((f, abs_num, raw_title, eps, is_season_relative))

        # Sort by absolute episode number to get the correct global order
        all_files.sort(key=lambda x: x[1])
        return all_files

    def run_preview(self, dry_run=True):
        """
        Scan the folder, match files to TMDB episode titles,
        and display the preview. The Rename button calls execute_rename()
        directly so that the user's checkbox selections are preserved.

        Detects season structure mismatches between the user's folders
        and TMDB, and offers to consolidate files into the correct
        TMDB season structure.
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

        # Fetch the full TMDB season structure for this show
        tmdb_seasons, total_tmdb_eps = self._fetch_tmdb_season_map(api_key)

        # Detect season structure mismatch
        mismatched, user_season_nums, tmdb_season_nums = self._detect_season_mismatch(
            season_dirs, tmdb_seasons
        )

        if mismatched and self._prompt_season_fix(user_season_nums, tmdb_season_nums, tmdb_seasons):
            # User accepted the fix — consolidate into TMDB structure
            self._build_consolidated_preview(season_dirs, tmdb_seasons, api_key)
        else:
            # No mismatch or user declined — normal per-folder processing
            self._build_normal_preview(season_dirs, tmdb_seasons, api_key)

        # FIX #14: Check for duplicate target filenames
        self._check_duplicates()

        # Always show the preview — rename uses the existing state
        self.display_preview()

    def _build_consolidated_preview(self, season_dirs, tmdb_seasons, api_key):
        """
        Build preview items that consolidate files from mismatched season
        folders into the correct TMDB season structure.

        All files are collected, sorted by absolute episode number, then
        mapped sequentially to TMDB's season/episode structure. Files are
        targeted to the correct TMDB season folder (created if necessary).
        """
        # Collect all video files in absolute order across all folders
        all_files = self._build_absolute_file_list(season_dirs)

        # Build a flat list of (tmdb_season, tmdb_episode, title) in order
        tmdb_episode_list = []
        for sn in sorted(tmdb_seasons.keys()):
            season_data = tmdb_seasons[sn]
            for ep_num in sorted(season_data["titles"].keys()):
                tmdb_episode_list.append((sn, ep_num, season_data["titles"][ep_num]))

        # Store TMDB data for detail panel lookups
        for sn, sdata in tmdb_seasons.items():
            self.episode_titles.update({(sn, k): v for k, v in sdata["titles"].items()})
            self.episode_posters.update({(sn, k): v for k, v in sdata["posters"].items()})

        # Map each file to its correct TMDB season + episode.
        # Multi-episode files consume multiple entries from the list.
        tmdb_idx = 0
        for f, abs_num, raw_title, eps, is_sr in all_files:
            # How many TMDB episodes does this file cover?
            num_eps = max(1, len(eps))

            if tmdb_idx >= len(tmdb_episode_list):
                self.preview_items.append({
                    "original": f,
                    "new_name": None,
                    "target_dir": None,
                    "season": 0,
                    "episodes": eps,
                    "status": "SKIP: no matching TMDB episode (extra file?)",
                })
                continue

            # Gather TMDB entries for all episodes this file covers
            file_eps = []
            file_titles = []
            target_season = tmdb_episode_list[tmdb_idx][0]
            for j in range(num_eps):
                if tmdb_idx + j < len(tmdb_episode_list):
                    sn, ep, title = tmdb_episode_list[tmdb_idx + j]
                    file_eps.append(ep)
                    file_titles.append(title)
                    target_season = sn
            tmdb_idx += num_eps

            # Build the target season folder path
            target_dir = self.folder / f"Season {target_season:02d}"

            new_name = build_name(
                self.show_info["name"],
                self.show_info["year"],
                target_season,
                file_eps,
                file_titles,
                f.suffix
            )

            self.preview_items.append({
                "original": f,
                "new_name": new_name,
                "target_dir": target_dir,
                "season": target_season,
                "episodes": file_eps,
                "status": "OK",
            })

    def _build_normal_preview(self, season_dirs, tmdb_seasons, api_key):
        """
        Build preview items using normal per-folder processing.
        Used when folder structure matches TMDB or the user declined
        the consolidation fix.

        Season 0 (specials/extras) gets special handling:
          - Fetches TMDB Season 0 data if available
          - Tries to match files by episode number or fuzzy title match
          - If matched: renames with proper Plex formatting
          - If not matched: keeps original filename, just moves to Season 00
        """
        for season_dir, season_num in season_dirs:
            if isinstance(season_dir, tuple):
                season_dir, season_num = season_dir

            # Get TMDB data for this season (from cache or fetch)
            if season_num in tmdb_seasons:
                titles = tmdb_seasons[season_num]["titles"]
                posters = tmdb_seasons[season_num]["posters"]
            else:
                titles, posters = tmdb_episode_titles(self.show_info["id"], season_num, api_key)

            self.episode_titles.update({(season_num, k): v for k, v in titles.items()})
            self.episode_posters.update({(season_num, k): v for k, v in posters.items()})

            # For Season 0 (specials), build a lookup of normalized TMDB
            # titles so we can fuzzy-match files that don't have episode numbers.
            tmdb_title_lookup = {}  # normalized_title -> (ep_num, original_title)
            if season_num == 0 and titles:
                for ep_num, title in titles.items():
                    normalized = re.sub(r"[^a-z0-9]+", "", title.lower())
                    tmdb_title_lookup[normalized] = (ep_num, title)

            # Target dir for specials: always "Season 00"
            specials_target = self.folder / "Season 00" if season_num == 0 else None

            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue

                eps, raw_title, is_season_relative = extract_episode(f.name)

                # --- Season 0 special handling ---
                if season_num == 0:
                    matched_ep = None
                    matched_title = None

                    # Try 1: Match by episode number if we parsed one
                    if eps:
                        for ep_num in eps:
                            if ep_num in titles:
                                matched_ep = ep_num
                                matched_title = titles[ep_num]
                                break

                    # Try 2: Fuzzy match by title from the filename
                    if not matched_ep and raw_title:
                        normalized_raw = re.sub(r"[^a-z0-9]+", "", raw_title.lower())
                        if normalized_raw in tmdb_title_lookup:
                            matched_ep, matched_title = tmdb_title_lookup[normalized_raw]
                        else:
                            # Partial match: check if any TMDB title contains
                            # the filename title or vice versa
                            for norm_key, (ep_n, orig_t) in tmdb_title_lookup.items():
                                if (normalized_raw and norm_key and
                                    (normalized_raw in norm_key or norm_key in normalized_raw)):
                                    matched_ep = ep_n
                                    matched_title = orig_t
                                    break

                    if matched_ep is not None:
                        # Found a TMDB match — rename with proper formatting
                        new_name = build_name(
                            self.show_info["name"],
                            self.show_info["year"],
                            0,
                            [matched_ep],
                            [matched_title],
                            f.suffix
                        )
                        self.preview_items.append({
                            "original": f,
                            "new_name": new_name,
                            "target_dir": specials_target,
                            "season": 0,
                            "episodes": [matched_ep],
                            "status": "OK",
                        })
                    else:
                        # No TMDB match — keep original filename, just
                        # ensure it ends up in the Season 00 directory.
                        self.preview_items.append({
                            "original": f,
                            "new_name": f.name,  # Keep original name
                            "target_dir": specials_target,
                            "season": 0,
                            "episodes": eps,
                            "status": "OK",
                        })
                    continue

                # --- Normal season handling ---
                if not eps:
                    self.preview_items.append({
                        "original": f,
                        "new_name": None,
                        "target_dir": None,
                        "season": season_num,
                        "episodes": [],
                        "status": "SKIP: could not parse episode number",
                    })
                    continue

                # Look up TMDB titles for ALL episodes (multi-ep files
                # like S01E01-E02 need both "Rising (1)" and "Rising (2)").
                ep_titles = []
                for ep_num in eps:
                    ep_titles.append(titles.get(ep_num, raw_title or f"Episode {ep_num}"))

                new_name = build_name(
                    self.show_info["name"],
                    self.show_info["year"],
                    season_num,
                    eps,
                    ep_titles,
                    f.suffix
                )

                self.preview_items.append({
                    "original": f,
                    "new_name": new_name,
                    "target_dir": None,  # None = same folder as source
                    "season": season_num,
                    "episodes": eps,
                    "status": "OK",
                })

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
        Show the rename preview with per-file checkboxes and styled dark cards.
        """
        c = self.colors

        # Clear existing preview widgets
        for w in self.preview_inner.winfo_children():
            w.destroy()
        self._image_refs.clear()
        self.check_vars.clear()
        self._selected_index = None

        if not self.preview_items:
            placeholder = ttk.Frame(self.preview_inner, style="TFrame")
            placeholder.pack(fill="x", pady=60)
            ttk.Label(placeholder, text="No files to preview",
                      foreground=c["text_muted"],
                      font=("Helvetica", 13)).pack(anchor="center")
            ttk.Label(placeholder, text="Select a show folder, then click Preview",
                      foreground=c["text_muted"],
                      font=("Helvetica", 10)).pack(anchor="center", pady=(4, 0))
            return

        for i, item in enumerate(self.preview_items):
            # Detect card type for visual distinction
            is_multi = len(item.get("episodes", [])) > 1
            is_special = item.get("season") == 0

            # Card container — specials and multi-eps get a colored left border
            if is_special:
                card_border = c["badge_special_bd"]
            elif is_multi:
                card_border = c["badge_multi_bd"]
            else:
                card_border = c["border"]

            card = tk.Frame(self.preview_inner, bg=c["bg_card"],
                            highlightthickness=1,
                            highlightbackground=card_border,
                            highlightcolor=c["accent"])
            card.pack(fill="x", padx=4, pady=2, ipadx=10, ipady=7)

            # Colored left accent bar for specials/multi-episode
            if is_special or is_multi:
                accent_color = c["badge_special_bd"] if is_special else c["badge_multi_bd"]
                accent_bar = tk.Frame(card, bg=accent_color, width=4)
                accent_bar.pack(side="left", fill="y", padx=(0, 6))

            # Checkbox — traces _update_tally on every toggle
            key = str(i)
            var = tk.BooleanVar(value=(item["status"] == "OK"))
            var.trace_add("write", lambda *_, s=self: s._update_tally())
            self.check_vars[key] = var
            cb = ttk.Checkbutton(card, variable=var, style="Card.TCheckbutton")
            cb.pack(side="left", padx=(4, 10))

            # Text content area
            text_area = tk.Frame(card, bg=c["bg_card"])
            text_area.pack(side="left", fill="x", expand=True)

            # Top row: badges + original filename
            top_row = tk.Frame(text_area, bg=c["bg_card"])
            top_row.pack(anchor="w", fill="x")

            # Type badges
            if is_multi:
                ep_count = len(item["episodes"])
                badge_m = tk.Label(top_row, text=f" {ep_count}-PART ",
                                    bg=c["badge_multi_bg"],
                                    fg=c["badge_multi_fg"],
                                    font=("Helvetica", 8, "bold"),
                                    padx=4, pady=1,
                                    highlightthickness=1,
                                    highlightbackground=c["badge_multi_bd"])
                badge_m.pack(side="left", padx=(0, 6), pady=1)

            if is_special:
                badge_s = tk.Label(top_row, text=" SPECIAL ",
                                    bg=c["badge_special_bg"],
                                    fg=c["badge_special_fg"],
                                    font=("Helvetica", 8, "bold"),
                                    padx=4, pady=1,
                                    highlightthickness=1,
                                    highlightbackground=c["badge_special_bd"])
                badge_s.pack(side="left", padx=(0, 6), pady=1)

            orig_text = item["original"].name
            src_folder = item["original"].parent.name

            # Determine colors and display text by status
            if "SKIP" in item["status"]:
                name_fg, arrow_fg = c["text_muted"], c["text_muted"]
                var.set(False)
                arrow_text = item["status"]
            elif "CONFLICT" in item["status"]:
                name_fg, arrow_fg = c["error"], c["error"]
                var.set(False)
                arrow_text = item["status"]
            elif item.get("target_dir") and item["target_dir"] != item["original"].parent:
                name_fg, arrow_fg = c["text"], c["move"]
                arrow_text = f"[{item['target_dir'].name}]  {item['new_name']}"
                orig_text = f"[{src_folder}]  {orig_text}"
            else:
                name_fg, arrow_fg = c["text"], c["success"]
                arrow_text = item["new_name"] or ""

            orig_lbl = tk.Label(top_row, text=orig_text, bg=c["bg_card"],
                                fg=name_fg, anchor="w", font=("Helvetica", 11))
            orig_lbl.pack(side="left", fill="x", expand=True)

            if arrow_text:
                new_lbl = tk.Label(text_area, text=f"  →  {arrow_text}",
                                    bg=c["bg_card"], fg=arrow_fg, anchor="w",
                                    font=("Helvetica", 10))
                new_lbl.pack(anchor="w")
            else:
                new_lbl = None

            # Click handlers for detail view
            clickables = [card, text_area, top_row, orig_lbl]
            if new_lbl:
                clickables.append(new_lbl)
            if is_special or is_multi:
                # Include accent bar and badges in click targets
                for child in card.winfo_children():
                    if child not in clickables:
                        clickables.append(child)
                for child in top_row.winfo_children():
                    if child not in clickables:
                        clickables.append(child)
            for w in clickables:
                w.bind("<Button-1>", lambda e, idx=i: self._select_card(idx))

        # Status bar with counts by type
        count_ok = sum(1 for it in self.preview_items if it["status"] == "OK")
        count_move = sum(1 for it in self.preview_items
                         if it.get("target_dir") and it["target_dir"] != it["original"].parent)
        count_multi = sum(1 for it in self.preview_items
                          if len(it.get("episodes", [])) > 1)
        count_special = sum(1 for it in self.preview_items
                            if it.get("season") == 0)
        parts = [f"{count_ok} ready"]
        if count_multi:
            parts.append(f"{count_multi} multi-ep")
        if count_special:
            parts.append(f"{count_special} specials")
        if count_move:
            parts.append(f"{count_move} moving")
        skip = len(self.preview_items) - count_ok
        if skip:
            parts.append(f"{skip} skipped")
        self.status_var.set("Preview:  " + "  ·  ".join(parts))

        # Update selection tally
        self._update_tally()

    def _select_card(self, index):
        """Highlight the selected card and show its detail."""
        c = self.colors
        for i, widget in enumerate(self.preview_inner.winfo_children()):
            if isinstance(widget, tk.Frame):
                widget.configure(highlightbackground=c["border"])
        children = self.preview_inner.winfo_children()
        if index < len(children) and isinstance(children[index], tk.Frame):
            children[index].configure(highlightbackground=c["accent"])
        self._selected_index = index
        self.show_episode_detail(index)

    def show_episode_detail(self, index):
        """Show styled detail info and episode still for a selected item."""
        c = self.colors
        item = self.preview_items[index]

        is_multi = len(item.get("episodes", [])) > 1
        is_special = item.get("season") == 0

        # Build detail text with labels
        lines = []

        # Type indicator at the top
        type_tags = []
        if is_multi:
            type_tags.append(f"MULTI-EPISODE ({len(item['episodes'])} parts)")
        if is_special:
            type_tags.append("SPECIAL")
        if type_tags:
            lines.append(" · ".join(type_tags) + "\n")

        lines.append(f"Original\n{item['original'].name}\n")
        if item['new_name']:
            lines.append(f"New Name\n{item['new_name']}\n")

        season_label = "Specials" if item['season'] == 0 else f"Season {item['season']}"
        lines.append(f"{season_label}  ·  "
                      f"Episode{'s' if is_multi else ''} "
                      f"{', '.join(str(e) for e in item['episodes']) if item['episodes'] else '—'}\n")

        status_text = item['status']
        if item.get("target_dir") and item["target_dir"] != item["original"].parent:
            status_text += f"\nMoving to {item['target_dir'].name}"

        lines.append(status_text)
        self.detail_label.configure(text="\n".join(lines))

        # Try to load episode still image, scaled to panel width
        if item["episodes"]:
            poster_path = self.episode_posters.get((item["season"], item["episodes"][0]))
            api_key = get_api_key("TMDB")
            if poster_path and api_key and self.show_info:
                img = fetch_tmdb_poster(
                    self.show_info["id"], api_key,
                    season=item["season"], ep_poster=poster_path,
                    target_width=400
                )
                if img:
                    # Scale to fit panel width
                    try:
                        panel_w = self.detail_inner.winfo_width() - 40
                    except Exception:
                        panel_w = 280
                    if panel_w < 150:
                        panel_w = 280
                    if img.width > panel_w:
                        scale = panel_w / img.width
                        img = img.resize((panel_w, int(img.height * scale)), Image.LANCZOS)

                    photo = ImageTk.PhotoImage(img)
                    self._image_refs.append(photo)
                    self.detail_image.configure(image=photo)
                    return
        self.detail_image.configure(image="")

    def execute_rename(self):
        """
        Perform the actual file renames/moves for checked items.
        Uses the existing preview_items and check_vars built by run_preview + display_preview.

        Supports cross-folder moves when target_dir differs from the
        source folder (used for season structure consolidation).
        Creates target directories as needed and removes empty source
        directories after all moves complete.
        """
        # Guard: must preview before renaming so check_vars exist
        if not self.preview_items or not self.check_vars:
            messagebox.showwarning("Preview First",
                                   "Click 'Preview' to scan and review files before renaming.")
            return

        renames = []
        source_dirs = set()  # Track source dirs for cleanup

        for i, item in enumerate(self.preview_items):
            key = str(i)
            # Use the checkbox state set by the user in the preview UI
            check_var = self.check_vars.get(key)
            if check_var is None or not check_var.get():
                continue
            if item["new_name"] is None or item["status"] != "OK":
                continue

            src = item["original"]
            source_dirs.add(src.parent)

            # Determine destination: target_dir if set, otherwise same folder
            target_dir = item.get("target_dir") or src.parent
            dst = target_dir / item["new_name"]

            # FIX #14: Final safety check — don't overwrite existing files
            if dst.exists() and src != dst:
                messagebox.showerror("Conflict",
                                     f"Target already exists:\n{dst}\n\nAborting all renames.")
                return

            renames.append((src, dst, target_dir))

        if not renames:
            messagebox.showinfo("Nothing to do", "No files selected for rename.")
            return

        # Build a descriptive confirmation message
        move_count = sum(1 for s, d, td in renames if s.parent != td)
        msg = f"Rename {len(renames)} file(s)?"
        if move_count:
            msg += f"\n\n{move_count} file(s) will be moved to a different folder."
            msg += "\nEmpty source folders will be removed."
        msg += "\n\nThis can be undone via 'Undo Last'."

        if not messagebox.askyesno("Confirm Rename", msg):
            return

        # Build undo log entry BEFORE renaming
        log_entry = {
            "show": self.show_info["name"] if self.show_info else "Unknown",
            "renames": [],
            "created_dirs": [],   # Track dirs we create for undo
            "removed_dirs": [],   # Track dirs we remove for undo
            "renamed_dirs": [],   # Track season folders we normalize for undo
        }

        errors = []
        for src, dst, target_dir in renames:
            try:
                # Create the target directory if it doesn't exist
                if not target_dir.exists():
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if str(target_dir) not in log_entry["created_dirs"]:
                        log_entry["created_dirs"].append(str(target_dir))

                # Use shutil.move for cross-filesystem moves; Path.rename
                # only works within the same filesystem
                if src.parent != target_dir:
                    shutil.move(str(src), str(dst))
                else:
                    src.rename(dst)

                log_entry["renames"].append({
                    "old": str(src),
                    "new": str(dst),
                })
            except (OSError, shutil.Error) as e:
                errors.append(f"{src.name}: {e}")

        # Normalize season folder names to Plex standard "Season ##" format.
        # Folders like "Show Name S02" or "Staffel 3" get renamed.
        # This runs AFTER file moves so the files are already in the right place.
        all_season_dirs = set()
        for src_dir in source_dirs:
            all_season_dirs.add(src_dir)
        # Also include target dirs that were created or already existed
        for _, dst, target_dir in renames:
            all_season_dirs.add(target_dir)

        for season_dir in all_season_dirs:
            if not season_dir.exists() or season_dir == self.folder:
                continue
            season_num = get_season(season_dir)
            if season_num is None:
                continue
            proper_name = f"Season {season_num:02d}"
            if season_dir.name == proper_name:
                continue  # Already correct
            proper_path = season_dir.parent / proper_name
            if proper_path.exists():
                continue  # Target name already taken — skip to avoid conflict
            try:
                season_dir.rename(proper_path)
                log_entry["renamed_dirs"].append({
                    "old": str(season_dir),
                    "new": str(proper_path),
                })
            except OSError:
                pass  # Not critical

        # Clean up empty source directories
        for src_dir in source_dirs:
            try:
                # Only remove if it's a season subfolder (not the root show folder)
                # and it's now empty (no files or subdirs left)
                if src_dir != self.folder and src_dir.exists():
                    remaining = list(src_dir.iterdir())
                    if not remaining:
                        src_dir.rmdir()
                        log_entry["removed_dirs"].append(str(src_dir))
            except OSError:
                pass  # Not critical if cleanup fails

        # Save log (appending to history)
        log = load_log()
        log.append(log_entry)
        save_log(log)

        if errors:
            messagebox.showwarning("Partial Rename",
                                   f"Renamed {len(log_entry['renames'])} files.\n\n"
                                   f"Errors ({len(errors)}):\n" + "\n".join(errors[:5]))
        else:
            result_msg = f"Successfully renamed {len(log_entry['renames'])} files."
            if log_entry.get("renamed_dirs"):
                renamed = [f"{Path(d['old']).name} → {Path(d['new']).name}"
                           for d in log_entry["renamed_dirs"]]
                result_msg += f"\n\nRenamed folders:\n" + "\n".join(renamed)
            if log_entry["removed_dirs"]:
                removed = [Path(d).name for d in log_entry["removed_dirs"]]
                result_msg += f"\n\nRemoved empty folders: {', '.join(removed)}"
            messagebox.showinfo("Done", result_msg)

        self.status_var.set(f"Renamed {len(log_entry['renames'])} files.")
        # Refresh preview
        self.run_preview(dry_run=True)

    def undo(self):
        """
        Undo the most recent rename batch using the log file.
        Handles cross-folder moves by recreating removed directories
        and cleaning up directories that were created during the rename.
        """
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
            desc += f"\n\n{move_count} file(s) will be moved back to their original folders."
        if last.get("removed_dirs"):
            dirs = [Path(d).name for d in last["removed_dirs"]]
            desc += f"\n\nThese folders will be recreated: {', '.join(dirs)}"

        if not messagebox.askyesno("Undo Rename", desc):
            return

        errors = []

        # Step 0: Reverse any season folder renames FIRST, because file
        # paths in the log reference the new (normalized) folder names.
        # We need to revert folders so the files inside them are at the
        # expected paths when we move them back.
        dir_rename_map = {}  # new_path -> old_path for path fixup
        for entry in reversed(last.get("renamed_dirs", [])):
            new_dir = Path(entry["new"])
            old_dir = Path(entry["old"])
            try:
                if new_dir.exists():
                    new_dir.rename(old_dir)
                    dir_rename_map[str(new_dir)] = str(old_dir)
            except OSError as e:
                errors.append(f"Could not revert folder {new_dir.name}: {e}")

        # Step 1: Recreate any directories that were removed during the rename
        for dir_path_str in last.get("removed_dirs", []):
            dir_path = Path(dir_path_str)
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                errors.append(f"Could not recreate folder {dir_path.name}: {e}")

        # Step 2: Move/rename all files back to their original locations.
        # Fix up file paths if their parent folder was renamed in step 0.
        for entry in reversed(last["renames"]):
            new_path = Path(entry["new"])
            old_path = Path(entry["old"])

            # If the file's parent folder was reverted, update the path
            for renamed_new, renamed_old in dir_rename_map.items():
                new_str = str(new_path)
                if new_str.startswith(renamed_new):
                    new_path = Path(new_str.replace(renamed_new, renamed_old, 1))
                old_str = str(old_path)
                if old_str.startswith(renamed_new):
                    old_path = Path(old_str.replace(renamed_new, renamed_old, 1))

            try:
                # Ensure the original parent directory exists
                old_path.parent.mkdir(parents=True, exist_ok=True)

                if new_path.exists():
                    if new_path.parent != old_path.parent:
                        shutil.move(str(new_path), str(old_path))
                    else:
                        new_path.rename(old_path)
                else:
                    errors.append(f"File not found: {new_path.name}")
            except (OSError, shutil.Error) as e:
                errors.append(f"{new_path.name}: {e}")

        # Step 3: Remove any directories that were created during the rename
        # (only if they're now empty after moving files out)
        for dir_path_str in last.get("created_dirs", []):
            dir_path = Path(dir_path_str)
            try:
                if dir_path.exists() and not list(dir_path.iterdir()):
                    dir_path.rmdir()
            except OSError:
                pass  # Not critical

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
                widget.pack(fill="x", padx=4, pady=2, ipadx=10, ipady=7)
            else:
                widget.pack_forget()

    def select_all(self):
        """
        Toggle selection: if all selectable items are checked, uncheck them all.
        Otherwise, check all selectable items.
        """
        selectable = []
        for i, item in enumerate(self.preview_items):
            if item["status"] == "OK":
                selectable.append(str(i))

        if not selectable:
            return

        # Check if all selectable are currently checked
        all_checked = all(
            self.check_vars.get(k, tk.BooleanVar(value=False)).get()
            for k in selectable
        )

        # Toggle: if all checked -> uncheck all; otherwise check all
        new_val = not all_checked
        for k in selectable:
            if k in self.check_vars:
                self.check_vars[k].set(new_val)

        self._update_tally()

    def _update_tally(self):
        """
        Update the running tally showing how many episodes are selected
        out of the total selectable episodes.
        """
        total_selectable = sum(1 for it in self.preview_items if it["status"] == "OK")
        selected = 0
        for i, item in enumerate(self.preview_items):
            if item["status"] == "OK":
                var = self.check_vars.get(str(i))
                if var and var.get():
                    selected += 1

        self.tally_var.set(f"{selected} / {total_selectable}")

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
