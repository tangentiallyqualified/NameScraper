"""Helpers for TV scan-state setup and execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ...engine import ScanState
from ...engine._episode_projection import project_preview_items
from ...engine.episode_assignments import carry_over_manual_assignments
from ...engine.models import TVScanStateScanner
from ...parsing import get_season


def build_accepted_tv_state(
    folder: Path,
    tmdb: Any,
    show_info: dict,
    scanner_factory: Callable[..., TVScanStateScanner],
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
    scanner_factory: Callable[..., TVScanStateScanner],
) -> TVScanStateScanner:
    if state.scanner is None:
        state.scanner = scanner_factory(
            tmdb,
            state.media_info,
            state.folder,
            season_hint=state.season_assignment,
            season_folders=state.season_folders or None,
        )
    return cast(TVScanStateScanner, state.scanner)


def run_tv_scan(
    state: ScanState,
    tmdb: Any,
    scanner_factory: Callable[..., TVScanStateScanner],
    duplicate_checker: Callable[[list[Any]], None],
) -> None:
    scanner = ensure_tv_scanner(state, tmdb, scanner_factory)
    items, has_mismatch = scanner.scan()
    if has_mismatch:
        items = scanner.scan_consolidated()
    new_table = getattr(scanner, "assignment_table", None)
    old_table = state.assignments
    if (
        new_table is not None
        and old_table is not None
        and state.show_id == scanner.show_info.get("id")
    ):
        carry_over_manual_assignments(old_table, new_table)
        items = project_preview_items(
            new_table,
            show_info=state.media_info,
            root=state.folder,
            media_fields={
                "media_id": state.show_id,
                "media_name": state.media_info.get("name"),
            },
        )
    state.assignments = new_table
    duplicate_checker(items)
    initial_checked = {index for index, item in enumerate(items) if item.status == "OK"}
    state.preview_items = items
    state.completeness = scanner.get_completeness(items, checked_indices=initial_checked)
    state.scanned = True
    if not any(item.is_actionable for item in items):
        state.checked = False
