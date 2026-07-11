"""Workspace AutoMux coordinator: plan application, card integration."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from conftest_qt import QtSmokeBase

PLAN = {
    "output_name": "Show - S01E01 - Pilot.mkv",
    "track_decisions": [
        {"track_id": 1, "track_type": "audio", "codec": "aac",
         "language": "eng", "name": "", "keep": True,
         "make_default": True, "reason": "retained"},
    ],
    "subtitle_merges": [
        {"source_relative": "Show/a.eng.srt", "action": "merge",
         "language": "eng", "set_default": False},
    ],
    "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
    "warnings": [], "user_modified": False,
}

# A plan that carries no actionable decision (all tracks kept as-is, no
# subtitle merge) -- plan_has_actions()/state_mux_eligible() must treat this
# the same as "no plan at all" for eligibility purposes (Task 4).
NO_ACTION_PLAN = {
    "output_name": "Show - S01E01 - Pilot.mkv",
    "track_decisions": [
        {"track_id": 1, "track_type": "audio", "codec": "aac",
         "language": "eng", "name": "", "keep": True,
         "make_default": True, "reason": "retained"},
    ],
    "subtitle_merges": [],
    "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
    "warnings": [], "user_modified": False,
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
    try:
        coordinator._bridge.plan_ready.disconnect()
    except RuntimeError:
        pass
    coordinator._widgets.clear()


class WorkspaceAutoMuxTests(QtSmokeBase):
    def _state(self):
        from plex_renamer.engine.models import PreviewItem, ScanState

        base = Path(self._main_window_tmp.name)
        item = PreviewItem(
            original=base / "lib" / "Show" / "a.mkv",
            new_name="Show - S01E01 - Pilot.mkv",
            target_dir=base / "out" / "Show (2020)" / "Season 01",
            season=1, episodes=[1], status="OK", media_type="tv",
            file_id=1,
        )
        return ScanState(
            folder=base / "lib" / "Show",
            media_info={"id": 7, "name": "Show", "year": "2020"},
            preview_items=[item], scanned=True,
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
        coordinator, roster = self._coordinator(state, self._settings())
        widget = coordinator.tracks_widget_for(state, 0)
        from PySide6.QtWidgets import QCheckBox

        merge_box = widget._rows_host.findChildren(QCheckBox)[1]
        merge_box.setChecked(False)
        self.assertTrue(state.mux_plans[0]["user_modified"])
        self.assertEqual(
            state.mux_plans[0]["subtitle_merges"][0]["action"], "rename")

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
        coordinator, panel = self._button_fixture(
            settings=self._make_settings(), state=state)
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
        coordinator, panel = self._button_fixture(
            settings=self._make_settings(), state=state)
        coordinator.update_button(state)
        self.assertEqual(panel.automux_button.property("cssClass"), "danger")
        coordinator.toggle_selected()
        self.assertEqual(panel.automux_button.property("cssClass"), "caution")

    def test_button_locked_while_queued(self):
        state = self._make_eligible_state()
        state.queued = True
        coordinator, panel = self._button_fixture(
            settings=self._make_settings(), state=state)
        coordinator.update_button(state)
        self.assertFalse(panel.automux_button.isEnabled())
        self.assertIn("Unqueue", panel.automux_button.toolTip())
        coordinator.toggle_selected()
        self.assertFalse(state.automux_disabled)   # locked: no toggle

    # ── Task 4: proactive warming + eligibility gate ─────────────────

    def _workspace_with_states(self):
        """(workspace, states) wired with a real coordinator at
        workspace._automux and no cached plans yet, so
        warm_plans_for_states must probe every item from scratch."""
        from plex_renamer.gui_qt.widgets._media_workspace_automux import (
            MediaWorkspaceAutoMuxCoordinator,
        )

        states = [self._make_state(), self._make_state()]
        workspace = SimpleNamespace(
            _settings=self._make_settings(),
            _media_type="tv",
            _media_ctrl=SimpleNamespace(
                tv_root_folder=Path(self._main_window_tmp.name) / "lib",
                movie_folder=None,
            ),
            _current_states=lambda: states,
            _selected_state=lambda: None,
            _roster_panel=SimpleNamespace(model=_RosterModelStub()),
        )
        coordinator = MediaWorkspaceAutoMuxCoordinator(workspace)
        workspace._automux = coordinator
        self.addCleanup(_dispose_coordinator, coordinator)
        return workspace, states

    def _workspace_with_selected_state(self, *, plan_actions: bool):
        """(workspace, state) via _button_fixture, with a cached plan
        already applied (no background probe involved) so
        state_mux_eligible reflects `plan_actions`."""
        state = self._make_state()
        state.mux_plans[0] = dict(PLAN if plan_actions else NO_ACTION_PLAN)
        coordinator, panel = self._button_fixture(
            settings=self._make_settings(), state=state)
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
        sync_patch = patch.object(
            automux_mod, "_submit_bg", side_effect=lambda fn: fn())
        sync_patch.start()
        self.addCleanup(sync_patch.stop)
        probe_patch = patch.object(
            svc_mod, "probe_file",
            side_effect=lambda mkv, path: ProbeResult(
                path=str(path), ok=True, tracks=[]))
        probe_patch.start()
        self.addCleanup(probe_patch.stop)
        plan_patch = patch.object(
            svc_mod, "plan_for_item", side_effect=lambda *a, **k: dict(PLAN))
        plan_patch.start()
        self.addCleanup(plan_patch.stop)

        workspace._automux.warm_plans_for_states(states)
        self._drain_thread_pool()

        for state in states:
            self.assertTrue(state.mux_plans, "plans must be warmed proactively")

    def test_button_hidden_when_no_plan_has_actions(self):
        workspace, state = self._workspace_with_selected_state(plan_actions=False)
        workspace._automux.update_button(state)
        self.assertFalse(workspace._work_panel.automux_button.isVisible())

    def test_button_shown_when_disabled_but_eligible(self):
        workspace, state = self._workspace_with_selected_state(plan_actions=True)
        state.automux_disabled = True
        workspace._automux.update_button(state)
        self.assertTrue(workspace._work_panel.automux_button.isVisible())
        self.assertEqual(
            workspace._work_panel.automux_button.text(), "Enable AutoMux")

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
