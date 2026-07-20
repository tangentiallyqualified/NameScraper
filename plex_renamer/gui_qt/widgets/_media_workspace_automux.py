"""AutoMux session coordinator for the media workspace (spec §8).

Owns background probe→plan requests (marshaled through a Qt bridge),
applies results to ScanState session fields, refreshes tracks widgets
and roster chips, and drives the Enable/Disable AutoMux header button.
"""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ...app.services import automux_service
from ...thread_pool import submit as _submit_bg
from ._automux_tracks import AutoMuxTracksWidget

# Rest-of-library warm sweep fan-out. The shared pool has 8 workers; 3
# leaves headroom for episode-guide builds, poster fetches, and async
# queue submissions. NAS probes are latency-bound, so 3 concurrent
# header reads is close to a 3x sweep speedup.
_WARM_SWEEP_WORKERS = 3


class _PlanBridge(QObject):
    plan_ready = Signal(object, int, object, str)  # state, index, plan|None, error


class MediaWorkspaceAutoMuxCoordinator:
    def __init__(self, workspace) -> None:
        self._workspace = workspace
        # Parent the bridge to the workspace widget so it is destroyed with
        # it — an orphaned QObject collected at interpreter exit races Qt
        # teardown and segfaults short pytest runs (see conftest_qt notes).
        parent = workspace if isinstance(workspace, QObject) else None
        self._bridge = _PlanBridge(parent)
        self._bridge.plan_ready.connect(self._on_plan_ready)
        self._inflight: set[tuple[int, int]] = set()  # (id(state), index)
        self._inflight_lock = threading.Lock()
        self._warm_lock = threading.Lock()
        self._warm_queue: deque[tuple[Any, int]] = deque()
        self._warm_sweep_active = 0
        self._executor_busy = False
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
        widget.plan_edited.connect(lambda plan, s=state, i=index: self._on_plan_edited(s, i, plan))
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
        prepared = self._begin_probe(state, index)
        if prepared is None:
            return
        mkvmerge, source_root, settings, ffprobe = prepared
        _submit_bg(lambda: self._run_probe(state, index, mkvmerge, source_root, settings, ffprobe))

    def _begin_probe(
        self, state, index: int
    ) -> tuple[Path, Path, automux_service.MuxSettings, Path | None] | None:
        """Validate settings and reserve the (state, index) slot in
        ``_inflight``. Returns the resolved (mkvmerge, source_root,
        settings, ffprobe) for the caller to hand to :meth:`_run_probe`, or
        ``None`` when the probe should not proceed (already in flight, or
        AutoMux isn't configured). Check-and-reserve is atomic: concurrent
        sweep workers racing the same slot must not both win it."""
        key = (id(state), index)
        svc = self._workspace._settings
        source_root = self._source_root()
        mkvmerge = automux_service.resolve_mkvmerge(svc)
        if svc is None or source_root is None or mkvmerge is None:
            return None
        ffprobe = automux_service.resolve_ffprobe(svc)
        settings = automux_service.mux_settings_from_service(svc)
        with self._inflight_lock:
            if key in self._inflight:
                return None
            self._inflight.add(key)
        return mkvmerge, source_root, settings, ffprobe

    def _run_probe(self, state, index: int, mkvmerge, source_root, settings, ffprobe=None) -> None:
        """The actual probe→plan work for one item. Safe to call either as
        a standalone pool task (``_request``) or inline from within a pool
        worker that is already fanning out sequentially over several items
        (the "warm the rest" task in :meth:`warm_plans_for_states`) --
        callers just need to have reserved the slot via ``_begin_probe``
        first."""
        key = (id(state), index)
        bridge = self._bridge
        try:
            # Re-check bounds at execution time: a rematch/rescan can rebuild
            # state.preview_items shorter (same state object, new list) while
            # this probe waits in the pool -- and the lookup must sit inside
            # the try so the finally always releases the _inflight slot (a
            # leaked key would dedup-skip this row's probes forever, wedging
            # its tracks widget on "Reading tracks...").
            if not (0 <= index < len(state.preview_items)):
                return
            item = state.preview_items[index]
            probe = automux_service.probe_file(mkvmerge, item.original, ffprobe_path=ffprobe)
            if not probe.ok:
                bridge.plan_ready.emit(state, index, None, probe.error or "Unreadable file")
                return
            plan = automux_service.plan_for_item(
                state,
                index,
                probe=probe,
                settings=settings,
                mkvmerge_path=str(mkvmerge),
                source_root=source_root,
            )
            bridge.plan_ready.emit(state, index, plan, "")
        except RuntimeError:
            pass  # bridge deleted during shutdown
        finally:
            with self._inflight_lock:
                self._inflight.discard(key)

    def _on_plan_ready(self, state, index: int, plan, error: str) -> None:
        if state not in self._workspace._current_states():
            return  # stale: library was reloaded
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
            self._workspace._work_panel.model.refresh_row_data(state)

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
            self._widgets.pop(key, None)  # widget already deleted by Qt
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

    # ── Shutdown ──────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Stop feeding the warm sweep: clear the pending queue so each
        worker exits after at most its current probe. Called at app close
        BEFORE thread_pool.drain — without this the drain's bound is
        decorative, since workers keep popping entries and spawning
        120s-timeout mkvmerge probes long after the window is gone."""
        with self._warm_lock:
            self._warm_queue.clear()

    def _effective_cap(self) -> int:
        """Current sweep worker cap. Call only while holding _warm_lock."""
        return 1 if self._executor_busy else _WARM_SWEEP_WORKERS

    def set_executor_busy(self, busy: bool) -> None:
        """Executor running -> downshift the sweep to one probe worker so
        remux jobs get the NAS bandwidth; idle -> top back up to the full
        cap from the existing queue. Thread-safe (state under _warm_lock;
        submits outside it), though in practice the main window calls this
        on the GUI thread via the executor bridge."""
        with self._warm_lock:
            self._executor_busy = bool(busy)
            if busy:
                return  # workers shed themselves at their next loop check
            spawn = max(
                0,
                min(self._effective_cap(), len(self._warm_queue)) - self._warm_sweep_active,
            )
            self._warm_sweep_active += spawn
        submitted = 0
        try:
            for _ in range(spawn):
                _submit_bg(self._warm_sweep_worker)
                submitted += 1
        except Exception:
            with self._warm_lock:
                self._warm_sweep_active -= spawn - submitted
            raise

    # ── Proactive plan warming (Task 4) ──────────────────────────────

    def warm_plans_for_states(self, states) -> None:
        """Kick background probes for every preview item that has no cached
        plan/error yet, so roster chips and the toggle button appear without
        requiring an expansion. Cheap to call repeatedly: the queue is
        rebuilt from live state each call, and per-item skip checks at
        execution time plus _begin_probe's dedup make warmed items no-ops.

        Ordering: the selected state warms immediately (item-per-task, as
        before); everything else goes into a shared deque drained by up to
        _WARM_SWEEP_WORKERS pool workers, with CHECKED states first —
        a checked show is the one the user is about to queue, so its
        plans must be ready soonest.
        """
        if not self.available():
            return
        states = list(states)
        if not states:
            return
        selected = self._workspace._selected_state()
        if selected is not None and any(state is selected for state in states):
            self._warm_state_items(selected)
            rest = [state for state in states if state is not selected]
        else:
            rest = states
        rest.sort(key=lambda state: 0 if state.checked else 1)  # stable
        self._refill_warm_queue(rest)

    def _pending_items(self, state) -> list[tuple[Any, int]]:
        """(state, index) entries still needing a probe — same skip
        conditions the old sequential sweep applied at execution time."""
        return [
            (state, index)
            for index, item in enumerate(state.preview_items)
            if automux_service.item_mux_probe_eligible(item)
            and index not in state.mux_plans
            and index not in state.mux_probe_errors
        ]

    def _refill_warm_queue(self, states) -> None:
        """Replace the pending queue and top workers up to the cap.

        Replacing (not appending) keeps repeat refreshes from growing the
        queue unboundedly; entries already probing are deduped by
        _begin_probe at execution time.
        """
        entries = [entry for state in states for entry in self._pending_items(state)]
        with self._warm_lock:
            self._warm_queue = deque(entries)
            spawn = max(0, min(self._effective_cap(), len(entries)) - self._warm_sweep_active)
            self._warm_sweep_active += spawn
        # Submit OUTSIDE the lock: tests patch _submit_bg to run the worker
        # inline, and the worker takes the lock itself.
        submitted = 0
        try:
            for _ in range(spawn):
                _submit_bg(self._warm_sweep_worker)
                submitted += 1
        except Exception:
            with self._warm_lock:
                self._warm_sweep_active -= spawn - submitted
            raise

    def _warm_sweep_worker(self) -> None:
        """Drain the shared queue one (state, index) at a time. Several of
        these run concurrently (capped by _WARM_SWEEP_WORKERS); the deque
        pop under _warm_lock is the only coordination they need. Re-checks
        each item's skip conditions at execution time so entries warmed or
        invalidated since enqueueing (rescan shrank preview_items, a
        repeat refresh already probed it) are skipped, and one item's
        failure never aborts the sweep. The empty-queue exit decrements
        _warm_sweep_active under the SAME lock hold that observed empty —
        a separately-acquired decrement let a refill see dying workers as
        active and strand a freshly filled queue with no drainer. Workers
        also shed themselves when the effective cap drops below the active
        count (executor busy)."""
        exited = False
        try:
            while True:
                with self._warm_lock:
                    if self._warm_sweep_active > self._effective_cap():
                        self._warm_sweep_active -= 1
                        exited = True
                        return
                    if not self._warm_queue:
                        self._warm_sweep_active -= 1
                        exited = True
                        return
                    state, index = self._warm_queue.popleft()
                try:
                    if not (0 <= index < len(state.preview_items)):
                        continue
                    item = state.preview_items[index]
                    if not automux_service.item_mux_probe_eligible(item):
                        continue
                    if index in state.mux_plans or index in state.mux_probe_errors:
                        continue
                    prepared = self._begin_probe(state, index)
                    if prepared is None:
                        continue
                    mkvmerge, source_root, settings, ffprobe = prepared
                    self._run_probe(state, index, mkvmerge, source_root, settings, ffprobe)
                except Exception:
                    continue
        finally:
            if not exited:
                with self._warm_lock:
                    self._warm_sweep_active -= 1

    def _warm_state_items(self, state) -> None:
        for index, item in enumerate(state.preview_items):
            if not automux_service.item_mux_probe_eligible(item):
                continue
            if index in state.mux_plans or index in state.mux_probe_errors:
                continue
            self._request(state, index)

    def prioritize_state(self, state) -> None:
        """Move *state*'s unwarmed items to the FRONT of the warm queue —
        called when the user checks a show (queue intent), so its plans
        are ready by the time they click Add to Queue. No-op when AutoMux
        is off or the state has nothing left to warm; tops workers back
        up to the cap in case the sweep already drained and exited."""
        if state is None or not self.available():
            return
        entries = self._pending_items(state)
        if not entries:
            return
        with self._warm_lock:
            remaining = [entry for entry in self._warm_queue if entry[0] is not state]
            self._warm_queue = deque(entries + remaining)
            spawn = max(
                0,
                min(self._effective_cap(), len(self._warm_queue)) - self._warm_sweep_active,
            )
            self._warm_sweep_active += spawn
        submitted = 0
        try:
            for _ in range(spawn):
                _submit_bg(self._warm_sweep_worker)
                submitted += 1
        except Exception:
            with self._warm_lock:
                self._warm_sweep_active -= spawn - submitted
            raise

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
        if state is None or not self.available() or not automux_service.state_mux_eligible(state):
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
            button.setToolTip("Unqueue this item to change its AutoMux configuration.")
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
