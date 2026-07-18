"""Workspace AutoMux coordinator: plan application, card integration."""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

from conftest_qt import QtSmokeBase

PLAN = {
    "output_name": "Show - S01E01 - Pilot.mkv",
    "track_decisions": [
        {
            "track_id": 1,
            "track_type": "audio",
            "codec": "aac",
            "language": "eng",
            "name": "",
            "keep": True,
            "make_default": True,
            "reason": "retained",
        },
    ],
    "subtitle_merges": [
        {
            "source_relative": "Show/a.eng.srt",
            "action": "merge",
            "language": "eng",
            "set_default": False,
        },
    ],
    "strip_track_names": False,
    "no_fear": False,
    "mkvmerge_path": "",
    "warnings": [],
    "user_modified": False,
}

# A plan that carries no actionable decision (all tracks kept as-is, no
# subtitle merge) -- plan_has_actions()/state_mux_eligible() must treat this
# the same as "no plan at all" for eligibility purposes (Task 4).
NO_ACTION_PLAN = {
    "output_name": "Show - S01E01 - Pilot.mkv",
    "track_decisions": [
        {
            "track_id": 1,
            "track_type": "audio",
            "codec": "aac",
            "language": "eng",
            "name": "",
            "keep": True,
            "make_default": True,
            "reason": "retained",
        },
    ],
    "subtitle_merges": [],
    "strip_track_names": False,
    "no_fear": False,
    "mkvmerge_path": "",
    "warnings": [],
    "user_modified": False,
}


class _RosterModelStub:
    def __init__(self):
        self.refreshed = []

    def refresh_state(self, index):
        self.refreshed.append(index)


def _dispose_coordinator(coordinator):
    """Deterministically break the bridge↔coordinator signal cycle while the
    QApplication is still alive. Passing the coordinator as a cleanup arg
    pins it until this runs — otherwise Python 3.14's incremental GC can
    collect the cycle at an arbitrary later point (even mid-event-loop in a
    later test), racing Qt teardown (conftest_qt segfault note)."""
    with contextlib.suppress(RuntimeError):
        coordinator._bridge.plan_ready.disconnect()
    coordinator._widgets.clear()


class WorkspaceAutoMuxTests(QtSmokeBase):
    def _state(self):
        from plex_renamer.engine.models import PreviewItem, ScanState

        base = Path(self._main_window_tmp.name)
        item = PreviewItem(
            original=base / "lib" / "Show" / "a.mkv",
            new_name="Show - S01E01 - Pilot.mkv",
            target_dir=base / "out" / "Show (2020)" / "Season 01",
            season=1,
            episodes=[1],
            status="OK",
            media_type="tv",
            file_id=1,
        )
        return ScanState(
            folder=base / "lib" / "Show",
            media_info={"id": 7, "name": "Show", "year": "2020"},
            preview_items=[item],
            scanned=True,
        )

    def _settings(self):
        from plex_renamer.app.services.settings_service import SettingsService

        base = Path(self._main_window_tmp.name)
        svc = SettingsService(base / "automux_ws.json")
        svc.automux_merge_subs = True
        svc.automux_merge_sub_languages = ["eng"]
        exe = base / "mkvmerge.exe"
        exe.write_bytes(b"")
        svc.mkvmerge_path = str(exe)
        return svc

    def _coordinator(self, state, settings):
        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )

        roster_model = _RosterModelStub()
        workspace = SimpleNamespace(
            _settings=settings,
            _media_type="tv",
            _media_ctrl=SimpleNamespace(
                tv_root_folder=Path(self._main_window_tmp.name) / "lib",
                movie_folder=None,
            ),
            _current_states=lambda: [state],
            _selected_state=lambda: None,
            _roster_panel=SimpleNamespace(model=roster_model),
        )
        coordinator = MediaWorkspaceAutoMuxCoordinator(workspace)
        self.addCleanup(_dispose_coordinator, coordinator)
        return coordinator, roster_model

    def test_unavailable_without_settings(self):
        state = self._state()
        coordinator, _ = self._coordinator(state, settings=None)
        self.assertFalse(coordinator.available())
        self.assertIsNone(coordinator.tracks_widget_for(state, 0))

    def test_cached_plan_renders_synchronously(self):
        from PySide6.QtWidgets import QCheckBox

        state = self._state()
        state.mux_plans[0] = dict(PLAN)
        coordinator, _ = self._coordinator(state, self._settings())
        widget = coordinator.tracks_widget_for(state, 0)
        self.assertIsNotNone(widget)
        self.assertEqual(len(widget._rows_host.findChildren(QCheckBox)), 2)

    def test_disabled_state_gets_no_widget(self):
        state = self._state()
        state.automux_disabled = True
        coordinator, _ = self._coordinator(state, self._settings())
        self.assertIsNone(coordinator.tracks_widget_for(state, 0))

    def test_plan_ready_applies_and_refreshes(self):
        state = self._state()
        coordinator, roster = self._coordinator(state, self._settings())
        coordinator._on_plan_ready(state, 0, dict(PLAN), "")
        self.assertEqual(state.mux_plans[0], PLAN)
        self.assertEqual(roster.refreshed, [0])
        coordinator._on_plan_ready(state, 0, None, "boom")
        self.assertNotIn(0, state.mux_plans)
        self.assertEqual(state.mux_probe_errors[0], "boom")

    def test_plan_edited_stores_on_state(self):
        state = self._state()
        state.mux_plans[0] = dict(PLAN)
        coordinator, _roster = self._coordinator(state, self._settings())
        widget = coordinator.tracks_widget_for(state, 0)
        from PySide6.QtWidgets import QCheckBox

        merge_box = widget._rows_host.findChildren(QCheckBox)[1]
        merge_box.setChecked(False)
        self.assertTrue(state.mux_plans[0]["user_modified"])
        self.assertEqual(state.mux_plans[0]["subtitle_merges"][0]["action"], "rename")

    def test_expansion_card_hosts_tracks_widget(self):
        from plex_renamer.gui_qt.widgets._automux_tracks import (
            AutoMuxTracksWidget,
        )
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard,
        )

        card = EpisodeExpansionCard()
        before = card._files_section.count()
        card.add_tracks_widget(AutoMuxTracksWidget())
        self.assertEqual(card._files_section.count(), before + 1)


class AutoMuxButtonAndChipTests(QtSmokeBase):
    def _button_fixture(self, *, settings, state):
        from types import SimpleNamespace

        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="tv")
        workspace = SimpleNamespace(
            _settings=settings,
            _media_type="tv",
            _media_ctrl=None,
            _work_panel=panel,
            _current_states=lambda: [state],
            _selected_state=lambda: state,
            _roster_panel=SimpleNamespace(model=_RosterModelStub()),
        )
        coordinator = MediaWorkspaceAutoMuxCoordinator(workspace)
        workspace._automux = coordinator
        self.addCleanup(_dispose_coordinator, coordinator)
        return coordinator, panel

    def _make_state(self):
        return WorkspaceAutoMuxTests._state(self)

    def _make_eligible_state(self):
        """A state whose cached plan has actions -- Task 4's eligibility
        gate (state_mux_eligible) requires this for the button to show."""
        state = self._make_state()
        state.mux_plans[0] = dict(PLAN)
        return state

    def _make_settings(self):
        return WorkspaceAutoMuxTests._settings(self)

    def test_button_hidden_when_unavailable(self):
        state = self._make_state()
        coordinator, panel = self._button_fixture(settings=None, state=state)
        coordinator.update_button(state)
        self.assertTrue(panel.automux_button.isHidden())

    def test_button_toggles_disable(self):
        state = self._make_eligible_state()
        coordinator, panel = self._button_fixture(settings=self._make_settings(), state=state)
        coordinator.update_button(state)
        self.assertFalse(panel.automux_button.isHidden())
        self.assertEqual(panel.automux_button.text(), "Disable AutoMux")
        coordinator.toggle_selected()
        self.assertTrue(state.automux_disabled)
        self.assertEqual(panel.automux_button.text(), "Enable AutoMux")

    def test_button_tone_matches_disable_vs_enable(self):
        # Task 10: filled danger while it says Disable AutoMux (AutoMux is
        # currently active), filled caution while it says Enable AutoMux
        # (AutoMux is currently disabled -- re-enabling is the caution action).
        state = self._make_eligible_state()
        coordinator, panel = self._button_fixture(settings=self._make_settings(), state=state)
        coordinator.update_button(state)
        self.assertEqual(panel.automux_button.property("cssClass"), "danger")
        coordinator.toggle_selected()
        self.assertEqual(panel.automux_button.property("cssClass"), "caution")

    def test_button_locked_while_queued(self):
        state = self._make_eligible_state()
        state.queued = True
        coordinator, panel = self._button_fixture(settings=self._make_settings(), state=state)
        coordinator.update_button(state)
        self.assertFalse(panel.automux_button.isEnabled())
        self.assertIn("Unqueue", panel.automux_button.toolTip())
        coordinator.toggle_selected()
        self.assertFalse(state.automux_disabled)  # locked: no toggle

    # ── Task 4: proactive warming + eligibility gate ─────────────────

    def _workspace_with_states(self, *, states=None, selected_index: int | None = None):
        """(workspace, states) wired with a real coordinator at
        workspace._automux and no cached plans yet, so
        warm_plans_for_states must probe every item from scratch.

        ``selected_index`` (final-review fix) lets a test pin which state
        ``workspace._selected_state()`` reports as currently selected, so
        warm-order assertions can be made against it."""
        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )

        if states is None:
            states = [self._make_state(), self._make_state()]
        selected = states[selected_index] if selected_index is not None else None
        workspace = SimpleNamespace(
            _settings=self._make_settings(),
            _media_type="tv",
            _media_ctrl=SimpleNamespace(
                tv_root_folder=Path(self._main_window_tmp.name) / "lib",
                movie_folder=None,
            ),
            _current_states=lambda: states,
            _selected_state=lambda: selected,
            _roster_panel=SimpleNamespace(model=_RosterModelStub()),
        )
        coordinator = MediaWorkspaceAutoMuxCoordinator(workspace)
        workspace._automux = coordinator
        self.addCleanup(_dispose_coordinator, coordinator)
        return workspace, states

    def _make_named_state(self, name: str):
        """A state whose preview item's path is distinguishable from other
        states' -- for probe-order assertions where every state built from
        ``_make_state`` would otherwise share the same fixed "a.mkv" path."""
        state = self._make_state()
        state.preview_items[0].original = Path(self._main_window_tmp.name) / "lib" / "Show" / name
        return state

    def _workspace_with_selected_state(self, *, plan_actions: bool):
        """(workspace, state) via _button_fixture, with a cached plan
        already applied (no background probe involved) so
        state_mux_eligible reflects `plan_actions`."""
        state = self._make_state()
        state.mux_plans[0] = dict(PLAN if plan_actions else NO_ACTION_PLAN)
        coordinator, panel = self._button_fixture(settings=self._make_settings(), state=state)
        panel.show()
        return coordinator._workspace, state

    def _drain_thread_pool(self):
        # _submit_bg is patched (in test_warm_plans_probes_without_expansion)
        # to run work synchronously, mirroring
        # test_workspace_poster_warmup.py's _drain_background -- nothing is
        # left in flight to drain.
        pass

    def test_warm_plans_probes_without_expansion(self):
        from unittest.mock import patch

        from plex_renamer._mkv_probe import ProbeResult
        from plex_renamer.app.services import automux_service as svc_mod
        from plex_renamer.gui_qt.widgets import (
            _media_workspace_automux as automux_mod,
        )

        workspace, states = self._workspace_with_states()
        sync_patch = patch.object(automux_mod, "_submit_bg", side_effect=lambda fn: fn())
        sync_patch.start()
        self.addCleanup(sync_patch.stop)
        probe_patch = patch.object(
            svc_mod,
            "probe_file",
            side_effect=lambda mkv, path: ProbeResult(path=str(path), ok=True, tracks=[]),
        )
        probe_patch.start()
        self.addCleanup(probe_patch.stop)
        plan_patch = patch.object(svc_mod, "plan_for_item", side_effect=lambda *a, **k: dict(PLAN))
        plan_patch.start()
        self.addCleanup(plan_patch.stop)

        workspace._automux.warm_plans_for_states(states)
        self._drain_thread_pool()

        for state in states:
            self.assertTrue(state.mux_plans, "plans must be warmed proactively")

    def test_warm_plans_probes_selected_state_before_others(self):
        # Final-review fix: warming every state's items through _request
        # dumped one pool task per preview item across the whole library
        # into the shared 8-worker pool before the selected show's guide
        # build was even submitted. warm_plans_for_states must now probe
        # the SELECTED state's items first and only then fan out (via a
        # single deferred task) over the rest.
        from unittest.mock import patch

        from plex_renamer._mkv_probe import ProbeResult
        from plex_renamer.app.services import automux_service as svc_mod
        from plex_renamer.gui_qt.widgets import (
            _media_workspace_automux as automux_mod,
        )

        states = [self._make_named_state("a.mkv"), self._make_named_state("b.mkv")]
        # Select the SECOND state -- if warming still went in list order,
        # this test would see "a.mkv" probed first and fail.
        workspace, states = self._workspace_with_states(states=states, selected_index=1)
        sync_patch = patch.object(automux_mod, "_submit_bg", side_effect=lambda fn: fn())
        sync_patch.start()
        self.addCleanup(sync_patch.stop)

        probed_names: list[str] = []

        def _fake_probe(mkv, path):
            probed_names.append(Path(path).name)
            return ProbeResult(path=str(path), ok=True, tracks=[])

        probe_patch = patch.object(svc_mod, "probe_file", side_effect=_fake_probe)
        probe_patch.start()
        self.addCleanup(probe_patch.stop)
        plan_patch = patch.object(svc_mod, "plan_for_item", side_effect=lambda *a, **k: dict(PLAN))
        plan_patch.start()
        self.addCleanup(plan_patch.stop)

        workspace._automux.warm_plans_for_states(states)
        self._drain_thread_pool()

        self.assertEqual(
            probed_names,
            ["b.mkv", "a.mkv"],
            "the selected state (b.mkv) must be probed before the other state",
        )

    def test_warm_plans_covers_movie_items_without_file_id(self):
        # Task 1 (spec 1a): the movie scanner never sets file_id, so the old
        # `item.file_id is None` skip condition excluded every movie preview
        # item from background warming -- roster badges only appeared after
        # the user clicked the row. Movie items must warm via is_actionable
        # just like TV items do.
        from unittest.mock import patch

        from plex_renamer.engine.models import PreviewItem, ScanState
        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )

        base = Path(self._main_window_tmp.name)
        item = PreviewItem(
            original=base / "lib" / "Movie (2020).mkv",
            new_name="Movie (2020).mkv",
            target_dir=base / "out" / "Movie (2020)",
            season=None,
            episodes=[],
            status="OK",
            media_type="movie",
            file_id=None,
        )
        state = ScanState(
            folder=base / "lib",
            media_info={"id": 7, "name": "Movie", "year": "2020"},
            preview_items=[item],
            scanned=True,
        )
        workspace = SimpleNamespace(
            _settings=self._make_settings(),
            _media_type="movie",
            _media_ctrl=SimpleNamespace(
                tv_root_folder=None,
                movie_folder=base / "lib",
            ),
            _current_states=lambda: [state],
            _selected_state=lambda: None,
            _roster_panel=SimpleNamespace(model=_RosterModelStub()),
        )
        coordinator = MediaWorkspaceAutoMuxCoordinator(workspace)
        self.addCleanup(_dispose_coordinator, coordinator)

        requested: list[int] = []
        request_patch = patch.object(
            MediaWorkspaceAutoMuxCoordinator,
            "_request",
            side_effect=lambda state, index: requested.append(index),
        )
        request_patch.start()
        self.addCleanup(request_patch.stop)

        coordinator.warm_plans_for_states([state])

        self.assertEqual(requested, [0], "movie item with file_id=None must still be warmed")

    def test_warm_releases_inflight_when_preview_list_shrinks_midflight(self):
        # Round-4 hardening: _run_probe used to read preview_items[index]
        # OUTSIDE its try/finally. If a rematch/rescan rebuilt the list
        # shorter while a warm probe waited in the pool, the IndexError
        # skipped the finally and leaked the _inflight key -- a later
        # expansion of that row then dedup-skipped forever, wedging its
        # tracks widget on "Reading tracks...". One bad item also aborted
        # _warm_rest's whole sweep. Both must now be survivable.
        from unittest.mock import patch

        from plex_renamer._mkv_probe import ProbeResult
        from plex_renamer.app.services import automux_service as svc_mod
        from plex_renamer.gui_qt.widgets import (
            _media_workspace_automux as automux_mod,
        )

        states = [self._make_named_state("a.mkv"), self._make_named_state("b.mkv")]
        workspace, states = self._workspace_with_states(states=states, selected_index=0)

        # Capture pool submissions instead of running them, so the preview
        # list can be rebuilt between enqueue and execution.
        deferred: list = []
        submit_patch = patch.object(
            automux_mod, "_submit_bg", side_effect=lambda fn: deferred.append(fn)
        )
        submit_patch.start()
        self.addCleanup(submit_patch.stop)
        probe_patch = patch.object(
            svc_mod,
            "probe_file",
            side_effect=lambda mkv, path: ProbeResult(path=str(path), ok=True, tracks=[]),
        )
        probe_patch.start()
        self.addCleanup(probe_patch.stop)
        plan_patch = patch.object(svc_mod, "plan_for_item", side_effect=lambda *a, **k: dict(PLAN))
        plan_patch.start()
        self.addCleanup(plan_patch.stop)

        workspace._automux.warm_plans_for_states(states)
        # selected state's item probe + the single warm-the-rest task
        self.assertEqual(len(deferred), 2)
        self.assertTrue(
            workspace._automux._inflight,
            "the selected item's slot must be reserved at enqueue time",
        )

        states[0].preview_items = []  # rescan rebuilt the list shorter

        for fn in deferred:
            fn()  # must not raise

        self.assertEqual(
            workspace._automux._inflight,
            set(),
            "the out-of-range probe must still release its _inflight slot",
        )
        self.assertFalse(states[0].mux_plans)
        self.assertTrue(
            states[1].mux_plans, "warming must continue to the next state despite the shrink"
        )

    def test_warm_plans_covers_correctly_named_tv_items(self):
        # Task 1 (round6 spec §1): a matched show whose file is already
        # correctly named has is_actionable=False (no rename needed), but
        # it must still be warmed so AutoMux badges/labels appear without
        # requiring an on-demand expansion probe.
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )

        state = self._make_state()
        item = state.preview_items[0]
        item.new_name = item.original.name
        item.target_dir = item.original.parent
        self.assertFalse(item.is_actionable)

        workspace, states = self._workspace_with_states(states=[state])

        requested: list[int] = []
        request_patch = patch.object(
            MediaWorkspaceAutoMuxCoordinator,
            "_request",
            side_effect=lambda state, index: requested.append(index),
        )
        request_patch.start()
        self.addCleanup(request_patch.stop)

        workspace._automux.warm_plans_for_states(states)

        self.assertEqual(requested, [0], "correctly-named TV item must still be probe-warmed")

    def test_button_hidden_when_no_plan_has_actions(self):
        workspace, state = self._workspace_with_selected_state(plan_actions=False)
        workspace._automux.update_button(state)
        self.assertFalse(workspace._work_panel.automux_button.isVisible())

    def test_button_shown_when_disabled_but_eligible(self):
        workspace, state = self._workspace_with_selected_state(plan_actions=True)
        state.automux_disabled = True
        workspace._automux.update_button(state)
        self.assertTrue(workspace._work_panel.automux_button.isVisible())
        self.assertEqual(workspace._work_panel.automux_button.text(), "Enable AutoMux")

    def test_roster_chip_reflects_mux_actions(self):
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        state = self._make_state()
        state.mux_plans[0] = dict(PLAN)
        model = RosterModel(media_type="tv")
        row = model._build_row_data(state)
        self.assertIn("AutoMux", [chip.text for chip in row.chips])
        state.automux_disabled = True
        row = model._build_row_data(state)
        self.assertNotIn("AutoMux", [chip.text for chip in row.chips])

    # ── Task 3 (round5 §1b): warm-time work-panel refresh wiring ─────

    def test_plan_ready_refreshes_work_panel_model_when_selected(self):
        """_on_plan_ready must tell the work-panel's episode table model to
        rebuild its row_data for the selected state, so a collapsed row's
        MUX chip appears the moment a background plan lands -- no reselect
        needed."""
        from unittest.mock import patch

        state = self._make_eligible_state()
        coordinator, panel = self._button_fixture(settings=self._make_settings(), state=state)
        with patch.object(panel.model, "refresh_row_data") as mock_refresh:
            coordinator._on_plan_ready(state, 0, dict(PLAN), "")
        mock_refresh.assert_called_once_with(state)

    def test_plan_ready_skips_work_panel_refresh_when_not_selected(self):
        """A background plan can land for any warmed state, not just the
        one currently shown -- refreshing the (unrelated) visible table
        would be wasted work, so the refresh call is gated on selection,
        same as update_button just above it."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = self._make_eligible_state()
        other_state = self._make_state()
        panel = MediaWorkPanel(media_type="tv")
        workspace = SimpleNamespace(
            _settings=self._make_settings(),
            _media_type="tv",
            _media_ctrl=None,
            _work_panel=panel,
            _current_states=lambda: [state, other_state],
            _selected_state=lambda: other_state,
            _roster_panel=SimpleNamespace(model=_RosterModelStub()),
        )
        coordinator = MediaWorkspaceAutoMuxCoordinator(workspace)
        self.addCleanup(_dispose_coordinator, coordinator)
        with patch.object(panel.model, "refresh_row_data") as mock_refresh:
            coordinator._on_plan_ready(state, 0, dict(PLAN), "")
        mock_refresh.assert_not_called()


class MoviePanelAutoMuxTests(QtSmokeBase):
    def test_set_automux_tracks_inserts_and_clears(self):
        from plex_renamer.gui_qt.widgets._automux_tracks import (
            AutoMuxTracksWidget,
        )
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="movie")
        self.assertEqual(panel._automux_tracks_host.count(), 0)
        widget = AutoMuxTracksWidget()
        panel.set_automux_tracks(widget)
        self.assertEqual(panel._automux_tracks_host.count(), 1)
        panel.set_automux_tracks(None)
        self.assertEqual(panel._automux_tracks_host.count(), 0)
