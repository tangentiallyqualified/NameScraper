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


class _RosterModelStub:
    def __init__(self):
        self.refreshed = []

    def refresh_state(self, index):
        self.refreshed.append(index)


class WorkspaceAutoMuxTests(QtSmokeBase):
    def _state(self):
        from plex_renamer.engine.models import PreviewItem, ScanState

        base = Path(self._main_window_tmp.name)
        item = PreviewItem(
            original=base / "lib" / "Show" / "a.mkv",
            new_name="Show - S01E01 - Pilot.mkv",
            target_dir=base / "out" / "Show (2020)" / "Season 01",
            season=1, episodes=[1], status="OK", media_type="tv",
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
            _roster_panel=SimpleNamespace(model=roster_model),
        )
        return MediaWorkspaceAutoMuxCoordinator(workspace), roster_model

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
