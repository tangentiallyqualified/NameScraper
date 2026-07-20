"""Track inspection via ``mkvmerge -J`` with a stat-keyed result cache."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
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
    channels: int = 0  # audio only; 0 = unknown
    bitrate_bps: int = 0  # audio only; 0 = unknown


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


def _as_int(value: object) -> int:
    """Tolerant int coercion — mkvmerge emits stats-tag values as strings."""
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


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
                channels=_as_int(props.get("audio_channels")),
                bitrate_bps=_as_int(props.get("tag_bps")),
            )
        )
    return ProbeResult(
        path=path,
        ok=True,
        tracks=tracks,
        container_type=str(container.get("type", "")),
    )


def clear_probe_cache() -> None:
    with _inflight_lock:
        _cache.clear()


def _cache_key(video_path: Path) -> tuple[str, int, int] | None:
    try:
        stat = video_path.stat()
    except OSError:
        return None
    return (str(video_path), stat.st_size, stat.st_mtime_ns)


class _InflightProbe:
    """Coalescing slot: the first caller probes, later callers wait on it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: ProbeResult | None = None


_inflight: dict[tuple[str, int, int], _InflightProbe] = {}
_inflight_lock = threading.Lock()

# Waiters outlast the prober's own subprocess timeout (120s) slightly so a
# timed-out probe still hands its error result to the waiters.
_INFLIGHT_WAIT_SECONDS = 150.0


def probe_file(mkvmerge_path: Path, video_path: Path) -> ProbeResult:
    """Run ``mkvmerge -J`` on *video_path*; cached on (path, size, mtime).

    Concurrent calls for the same key share one subprocess: the first
    caller probes, the rest block on its result (duplicate ``mkvmerge -J``
    of the same file was observed when the warm sweep and queue submission
    raced).
    """
    key = _cache_key(video_path)
    if key is None:
        return ProbeResult(path=str(video_path), ok=False, error=f"File not found: {video_path}")
    with _inflight_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        slot = _inflight.get(key)
        if slot is None:
            slot = _InflightProbe()
            _inflight[key] = slot
            owner = True
        else:
            owner = False

    if not owner:
        slot.done.wait(timeout=_INFLIGHT_WAIT_SECONDS)
        if slot.result is not None:
            return slot.result
        # Prober vanished without a result (unexpected): probe directly.
        return _probe_uncoalesced(mkvmerge_path, video_path, key)

    try:
        result = _probe_uncoalesced(mkvmerge_path, video_path, key)
        slot.result = result
        return result
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        slot.done.set()


def _probe_uncoalesced(
    mkvmerge_path: Path, video_path: Path, key: tuple[str, int, int]
) -> ProbeResult:
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
    with _inflight_lock:
        # FIFO eviction (dicts preserve insertion order): drop the oldest
        # entries instead of wiping — a full clear mid-sweep silently
        # re-probed everything already paid for on >512-file libraries.
        while len(_cache) >= _CACHE_MAX_ENTRIES:
            del _cache[next(iter(_cache))]
        _cache[key] = result
    return result
