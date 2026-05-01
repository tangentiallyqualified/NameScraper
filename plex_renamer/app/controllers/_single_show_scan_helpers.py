"""Helpers for single-show TV scan workflows."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from ..models import ScanLifecycle
from ._tv_state_helpers import ensure_tv_scanner, run_tv_scan

_log = logging.getLogger(__name__)


class _SingleShowScanController(Protocol):
    _batch_orchestrator: Any
    _batch_states: list[ScanState]

    @property
    def library_states(self) -> list[ScanState]: ...

    def _set_progress(
        self,
        lifecycle: ScanLifecycle,
        *,
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str | None = None,
        message: str = "",
    ) -> None: ...

    def _notify(self, event: str, *args: Any) -> None: ...

    def refresh_episode_guide(self, state: ScanState) -> Any: ...


def start_single_show_scan(
    controller: _SingleShowScanController,
    state: ScanState,
    tmdb: Any,
    *,
    scanner_factory: Any,
    duplicate_checker: Any,
) -> None:
    ensure_tv_scanner(state, tmdb, scanner_factory)

    controller._set_progress(
        ScanLifecycle.SCANNING,
        phase="Scanning TV files...",
        message=f"Scanning {state.display_name}...",
    )

    def _run_scan(target: ScanState) -> None:
        run_tv_scan(target, tmdb, scanner_factory, duplicate_checker)

    def _worker() -> None:
        final_state = state
        try:
            state.scanning = True
            controller._notify("library_changed", controller.library_states)
            _run_scan(state)
            state.scanning = False

            orchestrator = controller._batch_orchestrator
            if orchestrator is not None:
                orchestrator.states = controller._batch_states
                reconciled = orchestrator.reconcile_scanned_state(state)
                controller._batch_states = orchestrator.states
                if reconciled is not state:
                    final_state = reconciled
                    reconciled.scanning = True
                    controller._notify("library_changed", controller.library_states)
                    _run_scan(reconciled)
                    reconciled.scanning = False
        except Exception as exc:
            _log.exception("Single-show scan failed: %s", exc)
        finally:
            state.scanning = False
            if final_state is not state:
                final_state.scanning = False

        controller._set_progress(
            ScanLifecycle.READY,
            phase="TV scan complete",
            message=f"Preview ready — {len(final_state.preview_items)} file(s)",
        )
        if final_state.preview_items:
            controller.refresh_episode_guide(final_state)
        controller._notify("library_changed", controller.library_states)
        controller._notify("scan_complete", final_state)

    _submit_bg(_worker)
