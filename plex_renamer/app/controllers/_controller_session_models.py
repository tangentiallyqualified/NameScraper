"""Private state containers for MediaController session ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...constants import MediaType
from ...engine import BatchTVOrchestrator, MovieScanner, PreviewItem, ScanState


@dataclass(slots=True)
class ControllerModeState:
    active_content_mode: MediaType = MediaType.TV
    active_library_mode: MediaType | None = None
    library_selected_index: int | None = None


@dataclass(slots=True)
class TVControllerSession:
    batch_mode: bool = False
    batch_states: list[ScanState] = field(default_factory=list)
    active_scan: ScanState | None = None
    batch_orchestrator: BatchTVOrchestrator | None = None
    root_folder: Path | None = None


@dataclass(slots=True)
class MovieControllerSession:
    library_states: list[ScanState] = field(default_factory=list)
    preview_items: list[PreviewItem] = field(default_factory=list)
    scanner: MovieScanner | None = None
    folder: Path | None = None
    media_info: dict[str, Any] | None = None