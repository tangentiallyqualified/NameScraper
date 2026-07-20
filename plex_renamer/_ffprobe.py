"""Optional ffprobe helper: per-stream audio bitrates for containers
whose mkvmerge -J output lacks statistics tags (MP4/AVI, unmuxed MKVs).

Never required: callers treat a missing binary or empty result as
"bitrate unknown" and the dedup pass exempts the affected group.

Deliberately has no internal (plex_renamer.*) imports: ``_mkv_probe``
already imports this module (locally, inside ``probe_file``) to reach
``probe_audio_bitrates``/``merge_ffprobe_bitrates``. An import back the
other way -- e.g. to type-hint against ``_mkv_probe.ProbeResult`` -- would
close a dependency cycle the repository's audit contract forbids (see
``tests/audit/test_repository_contracts.py``). That's why
``merge_ffprobe_bitrates`` lives in ``_mkv_probe.py`` instead, colocated
with the ``ProbeResult``/``MediaTrack`` types it operates on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Hide console windows spawned on Windows (mirrors _mkv_probe._CREATION_FLAGS).
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def find_ffprobe(explicit: str = "") -> Path | None:
    """Resolve the ffprobe binary: an explicit path if it is a real file,
    else whatever ``shutil.which`` finds on PATH. A configured-but-wrong
    explicit path returns None rather than silently falling back."""
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        return None
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def probe_audio_bitrates(
    ffprobe: Path,
    video_path: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> list[int]:
    """Bitrate per audio stream in stream order; 0 unknown; [] on failure."""
    try:
        completed = runner(
            [
                str(ffprobe),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "a",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=_CREATION_FLAGS,
        )
        doc: dict[str, Any] = json.loads(completed.stdout or "{}")
    except Exception:
        return []
    bitrates: list[int] = []
    streams: list[dict[str, Any]] = doc.get("streams", [])
    for stream in streams:
        tags: dict[str, Any] = stream.get("tags") or {}
        raw: Any = stream.get("bit_rate") or tags.get("BPS") or tags.get("BPS-eng")
        try:
            bitrates.append(max(0, int(str(raw))))
        except (TypeError, ValueError):
            bitrates.append(0)
    return bitrates
