"""AutoMux session coordinator for the media workspace (spec §8).

Owns background probe→plan requests (marshaled through a Qt bridge),
applies results to ScanState session fields, refreshes tracks widgets
and roster chips, and drives the Enable/Disable AutoMux header button.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ...app.services import automux_service
from ...thread_pool import submit as _submit_bg
from ._automux_tracks import AutoMuxTracksWidget


class _PlanBridge(QObject):
    plan_ready = Signal(object, int, object, str)   # state, index, plan|None, error


class MediaWorkspaceAutoMuxCoordinator:
    def __init__(self, workspace) -> None:
        self._workspace = workspace
        # Parent the bridge to the workspace widget so it is destroyed with
        # it — an orphaned QObject collected at interpreter exit races Qt
        # teardown and segfaults short pytest runs (see conftest_qt notes).
        parent = workspace if isinstance(workspace, QObject) else None
        self._bridge = _PlanBridge(parent)
        self._bridge.plan_ready.connect(self._on_plan_ready)
        self._inflight: set[tuple[int, int]] = set()             # (id(state), index)
        self._widgets: dict[tuple[int, int], AutoMuxTracksWidget] = {}

    # ── Availability ──────────────────────────────────────────────────

    def available(self) -> bool:
        return automux_service.automux_active(self._workspace._settings)

    def _source_root(self) -> Path | None:
        ctrl = self._workspace._media_ctrl
        if ctrl is None:
            return None
        if self._workspace._media_type == "movie":
            return ctrl.movie_folder
        return ctrl.tv_root_folder

    # ── Tracks sections ───────────────────────────────────────────────

    def tracks_widget_for(self, state, index: int) -> AutoMuxTracksWidget | None:
        """Create, register, and populate a tracks widget for one preview
        item. None when AutoMux has no UI to show (spec §3.1/§8.1)."""
        if state is None or not self.available() or state.automux_disabled:
            return None
        if not (0 <= index < len(state.preview_items)):
            return None
        widget = AutoMuxTracksWidget()
        self._widgets[(id(state), index)] = widget
        widget.plan_edited.connect(
            lambda plan, s=state, i=index: self._on_plan_edited(s, i, plan))
        self._populate(widget, state, index)
        return widget

    def _populate(self, widget: AutoMuxTracksWidget, state, index: int) -> None:
        error = state.mux_probe_errors.get(index)
        if error:
            widget.show_error(error)
            return
        plan = state.mux_plans.get(index)
        if plan is not None:
            widget.show_plan(plan, locked=bool(state.queued))
            return
        widget.show_probing()
        self._request(state, index)

    def _request(self, state, index: int) -> None:
        key = (id(state), index)
        if key in self._inflight:
            return
        svc = self._workspace._settings
        source_root = self._source_root()
        mkvmerge = automux_service.resolve_mkvmerge(svc)
        if svc is None or source_root is None or mkvmerge is None:
            return
        settings = automux_service.mux_settings_from_service(svc)
        item = state.preview_items[index]
        self._inflight.add(key)
        bridge = self._bridge

        def _worker() -> None:
            try:
                probe = automux_service.probe_file(mkvmerge, item.original)
                if not probe.ok:
                    bridge.plan_ready.emit(
                        state, index, None, probe.error or "Unreadable file")
                    return
                plan = automux_service.plan_for_item(
                    state, index, probe=probe, settings=settings,
                    mkvmerge_path=str(mkvmerge), source_root=source_root)
                bridge.plan_ready.emit(state, index, plan, "")
            except RuntimeError:
                pass                       # bridge deleted during shutdown
            finally:
                self._inflight.discard(key)

        _submit_bg(_worker)

    def _on_plan_ready(self, state, index: int, plan, error: str) -> None:
        if state not in self._workspace._current_states():
            return                          # stale: library was reloaded
        if error:
            state.mux_probe_errors[index] = error
            state.mux_plans.pop(index, None)
        else:
            state.mux_probe_errors.pop(index, None)
            if plan is None:
                state.mux_plans.pop(index, None)
            else:
                state.mux_plans[index] = plan
        self._refresh_widget(state, index)
        self._refresh_roster_row(state)
        if state is self._workspace._selected_state():
            self.update_button(state)

    def _refresh_widget(self, state, index: int) -> None:
        key = (id(state), index)
        widget = self._widgets.get(key)
        if widget is None:
            return
        try:
            error = state.mux_probe_errors.get(index)
            if error:
                widget.show_error(error)
            elif state.mux_plans.get(index) is not None:
                widget.show_plan(state.mux_plans[index], locked=bool(state.queued))
            else:
                widget.show_no_actions()
        except RuntimeError:
            self._widgets.pop(key, None)    # widget already deleted by Qt
            return
        # The widget just repopulated (Task 8): if it belongs to the row
        # currently expanded in the TV table, its editor's cached sizeHint()
        # (taken when the row opened) is now stale -- tell the model so the
        # delegate re-measures. Movie mode has no expanded-row concept (the
        # tracks widget is inlined in the work panel), and
        # notify_expanded_row_changed() is a no-op there / whenever the
        # widget that changed isn't the expanded row's own.
        self._workspace._work_panel.model.notify_expanded_row_changed()

    def _on_plan_edited(self, state, index: int, plan: dict) -> None:
        state.mux_plans[index] = plan
        self._refresh_roster_row(state)

    def _refresh_roster_row(self, state) -> None:
        workspace = self._workspace
        try:
            state_index = workspace._current_states().index(state)
        except (ValueError, AttributeError):
            return
        panel = getattr(workspace, "_roster_panel", None)
        model = getattr(panel, "model", None)
        if model is not None:
            model.refresh_state(state_index)

    # ── Proactive plan warming (Task 4) ──────────────────────────────

    def warm_plans_for_states(self, states) -> None:
        """Kick background probes for every preview item that has no cached
        plan/error yet, so roster chips and the toggle button appear without
        requiring an expansion. Cheap to call repeatedly: _request's
        _inflight dedup plus the cached plan/error checks below make an
        already-warmed state a no-op."""
        if not self.available():
            return
        for state in states:
            for index, item in enumerate(state.preview_items):
                if item.file_id is None:
                    continue
                if index in state.mux_plans or index in state.mux_probe_errors:
                    continue
                self._request(state, index)

    # ── Movie panel (Task 6) / header button (Task 7) ─────────────────

    def on_state_shown(self, state) -> None:
        """Movie mode: the tracks section is inline in the work panel
        (spec §8.2). TV mode shows tracks on expansion cards instead."""
        workspace = self._workspace
        if workspace._media_type != "movie":
            return
        panel = workspace._work_panel
        if state is None or not state.preview_items:
            panel.set_automux_tracks(None)
            return
        panel.set_automux_tracks(self.tracks_widget_for(state, 0))

    def update_button(self, state) -> None:
        """Spec §8.1: visible only when AutoMux is enabled, mkvmerge is
        available, AND the state actually has a plan with actions (Task 4)
        -- ignoring automux_disabled, so a disabled-but-eligible entry can
        still be re-enabled from the button. Locked with a tooltip while
        the entry is queued."""
        button = self._workspace._work_panel.automux_button
        if (
            state is None
            or not self.available()
            or not automux_service.state_mux_eligible(state)
        ):
            button.hide()
            return
        button.show()
        disabling = not state.automux_disabled
        button.setText("Disable AutoMux" if disabling else "Enable AutoMux")
        button.setProperty("cssClass", "danger" if disabling else "caution")
        style = button.style()
        if style is not None:
            style.unpolish(button)
            style.polish(button)
        if state.queued:
            button.setEnabled(False)
            button.setToolTip(
                "Unqueue this item to change its AutoMux configuration.")
        else:
            button.setEnabled(True)
            button.setToolTip("")

    def toggle_selected(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued:
            return
        state.automux_disabled = not state.automux_disabled
        self.update_button(state)
        self._refresh_roster_row(state)
        if workspace._media_type == "movie":
            self.on_state_shown(state)
