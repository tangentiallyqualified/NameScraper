"""Helpers for TV scan-state setup and execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...engine import ScanState
from ...parsing import get_season


def build_accepted_tv_state(
    folder: Path,
    tmdb: Any,
    show_info: dict,
    scanner_factory: Callable[..., Any],
) -> ScanState:
    season_hint = get_season(folder)
    scanner = scanner_factory(tmdb, show_info, folder, season_hint=season_hint)
    return ScanState(
        folder=folder,
        media_info=show_info,
        scanner=scanner,
        confidence=1.0,
        season_assignment=season_hint,
        scanned=False,
    )


def ensure_tv_scanner(
    state: ScanState,
    tmdb: Any,
    scanner_factory: Callable[..., Any],
):
    if state.scanner is None:
        state.scanner = scanner_factory(
            tmdb,
            state.media_info,
            state.folder,
            season_hint=state.season_assignment,
            season_folders=state.season_folders or None,
        )
    return state.scanner


def run_tv_scan(
    state: ScanState,
    tmdb: Any,
    scanner_factory: Callable[..., Any],
    duplicate_checker: Callable[[list[Any]], None],
) -> None:
    scanner = ensure_tv_scanner(state, tmdb, scanner_factory)
    items, has_mismatch = scanner.scan()
    if has_mismatch:
        items = scanner.scan_consolidated()
    duplicate_checker(items)
    initial_checked = {index for index, item in enumerate(items) if item.status == "OK"}
    state.preview_items = items
    state.completeness = scanner.get_completeness(items, checked_indices=initial_checked)
    state.scanned = True
    if not any(item.is_actionable for item in items):
        state.checked = False