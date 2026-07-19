"""Track inspection via ``mkvmerge -J`` with a stat-keyed result cache."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ._lang_normalize import normalize_lang

_log = logging.getLogger(__name__)

_CACHE_MAX_ENTRIES = 512
_cache: dict[tuple[str, int, int], ProbeResult] = {}

# Hide console windows spawned on Windows.
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass(frozen=True)
class MediaTrack:
    track_id: int
    track_type: str  # "video" | "audio" | "subtitles"
    codec: str
    language: str  # normalized ISO 639-2/B, "und" fallback
    name: str
    is_default: bool
    is_forced: bool


@dataclass
class ProbeResult:
    path: str
    ok: bool
    tracks: list[MediaTrack] = field(default_factory=list)
    container_type: str = ""
    error: str = ""

    @property
    def audio_tracks(self) -> list[MediaTrack]:
        return [t for t in self.tracks if t.track_type == "audio"]

    @property
    def subtitle_tracks(self) -> list[MediaTrack]:
        return [t for t in self.tracks if t.track_type == "subtitles"]

    @property
    def video_tracks(self) -> list[MediaTrack]:
        return [t for t in self.tracks if t.track_type == "video"]


def parse_identify_json(path: str, payload: dict) -> ProbeResult:
    """Pure parse of a ``mkvmerge -J`` JSON document."""
    container = payload.get("container", {})
    if not (container.get("recognized") and container.get("supported")):
        errors = payload.get("errors") or ["container not recognized"]
        return ProbeResult(path=path, ok=False, error="; ".join(str(e) for e in errors))

    tracks: list[MediaTrack] = []
    for raw in payload.get("tracks", []):
        props = raw.get("properties", {})
        tracks.append(
            MediaTrack(
                track_id=int(raw.get("id", -1)),
                track_type=str(raw.get("type", "")),
                codec=str(raw.get("codec", "")),
                language=normalize_lang(str(props.get("language", ""))) or "und",
                name=str(props.get("track_name", "")),
                is_default=bool(props.get("default_track", False)),
                is_forced=bool(props.get("forced_track", False)),
            )
        )
    return ProbeResult(
        path=path,
        ok=True,
        tracks=tracks,
        container_type=str(container.get("type", "")),
    )


def clear_probe_cache() -> None:
    _cache.clear()


def _cache_key(video_path: Path) -> tuple[str, int, int] | None:
    try:
        stat = video_path.stat()
    except OSError:
        return None
    return (str(video_path), stat.st_size, stat.st_mtime_ns)


def probe_file(mkvmerge_path: Path, video_path: Path) -> ProbeResult:
    """Run ``mkvmerge -J`` on *video_path*; cached on (path, size, mtime)."""
    key = _cache_key(video_path)
    if key is None:
        return ProbeResult(path=str(video_path), ok=False, error=f"File not found: {video_path}")
    cached = _cache.get(key)
    if cached is not None:
        return cached

    try:
        proc = subprocess.run(
            [str(mkvmerge_path), "-J", str(video_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=_CREATION_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return ProbeResult(path=str(video_path), ok=False, error=str(e))

    if proc.returncode not in (0, 1):  # 1 = identified with warnings
        return ProbeResult(
            path=str(video_path), ok=False, error=f"mkvmerge exited {proc.returncode}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return ProbeResult(path=str(video_path), ok=False, error=str(e))

    result = parse_identify_json(str(video_path), payload)
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[key] = result
    return result
