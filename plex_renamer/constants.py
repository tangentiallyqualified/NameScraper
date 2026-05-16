"""
Shared constants and configuration for Plex Renamer.
"""

import re
from enum import StrEnum
from pathlib import Path

# ─── File types ───────────────────────────────────────────────────────────────

# ─── Year / resolution guards ────────────────────────────────────────────────
# Used by parsing and engine modules to distinguish episode numbers from years
# and resolution tags embedded in filenames.

YEAR_MIN = 1900
YEAR_MAX = 2099
YEAR_MIN_EXTRACT = 1920  # stricter lower bound for extract_year()

RESOLUTION_NUMBERS = frozenset({480, 720, 1080, 2160})

# ─── Scoring ─────────────────────────────────────────────────────────────────

SCORE_TIE_MARGIN = 0.02  # runner-up within this delta → flag for review

# ─── File types ───────────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m4v"}

# Subtitle/caption formats — renamed alongside their paired video file.
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup", ".mks"}

# ─── Logging / persistence paths ─────────────────────────────────────────────

LOG_DIR = Path.home() / ".plex_renamer"
DB_FILE = LOG_DIR / "job_queue.db"
CACHE_DB_FILE = LOG_DIR / "cache.db"


def ensure_log_dir() -> None:
    """Create the log directory if it doesn't exist. Called lazily on first use."""
    LOG_DIR.mkdir(exist_ok=True)


# ─── Job queue constants ─────────────────────────────────────────────────────

class JobStatus(StrEnum):
    """Status values for job queue entries."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERTED = "reverted"
    REVERT_FAILED = "revert_failed"


class JobKind(StrEnum):
    """Job type discriminator — extensible for future task types."""
    RENAME = "rename"
    # Future: download subtitles from the OpenSubtitles API.
    # This is a separate job kind (not an op within RENAME) because it
    # involves network I/O, rate limiting, and credential management.
    SUBTITLE_DOWNLOAD = "subtitle_download"

# ─── Filename sanitization ────────────────────────────────────────────────────

# Characters illegal in filenames on Windows (and problematic elsewhere).
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?]')

# ─── Release-group noise patterns ────────────────────────────────────────────
# Tokens commonly found in release-group folder/file names that are NOT part
# of the actual title.  Matched case-insensitively.

RELEASE_NOISE = re.compile(
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
        # --- Season indicators (not part of the title) ---
        |S\d{1,2}(?:[\-]S\d{1,2})?(?:E\d{1,3})?
    )
    (?=[ .\-_]|$)                     # followed by separator or end
    """,
    re.IGNORECASE | re.VERBOSE
)

# The trailing release group after the last hyphen, e.g. "-iAHD"
TRAILING_GROUP = re.compile(r"-[A-Za-z0-9]{2,10}$")

# ─── Media type enum ─────────────────────────────────────────────────────────

class MediaType(StrEnum):
    """Media type constants — StrEnum for type safety and string compatibility."""
    TV = "tv"
    MOVIE = "movie"
    OTHER = "other"
