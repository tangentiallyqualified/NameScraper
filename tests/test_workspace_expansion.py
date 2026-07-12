# tests/test_workspace_expansion.py
"""Header description follows the expanded episode (M10): the work panel's
header overview swaps to the expanded episode's overview/air-date and
reverts to the remembered series overview on collapse."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.engine import CompletenessReport, ScanState, SeasonCompleteness

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class HeaderFollowsEpisodeTests(QtSmokeBase):
    def _panel(self, media_type="tv", tmdb_provider=None):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type=media_type, tmdb_provider=tmdb_provider)
        panel.resize(760, 640)
        return panel

    def test_episode_overview_swaps_and_restores(self):
        panel = self._panel(media_type="tv")
        panel._apply_overview_text("Series overview.", "tok")
        panel.set_episode_overview("Episode plot.", "2023-05-01")
        self.assertEqual(panel._overview_label.text(), "Episode plot.\nAir date: 2023-05-01")
        panel.clear_episode_overview()
        self.assertEqual(panel._overview_label.text(), "Series overview.")

    def test_async_series_overview_remembered_not_shown_while_episode_active(self):
        """(B) An async series overview arriving while an episode is expanded
        must not overwrite the visible episode text, but must be remembered
        so a later collapse restores the *new* series text (not stale text
        captured before the async response landed)."""
        panel = self._panel(media_type="tv")
        panel._apply_overview_text("Old series overview.", panel._current_token)
        panel.set_episode_overview("Ep plot.", "2023-01-01")
        self.assertEqual(panel._overview_label.text(), "Ep plot.\nAir date: 2023-01-01")

        # Simulate the async TMDB series overview arriving for the current
        # token while the episode row is still expanded.
        panel._apply_overview_text("NEW series overview", panel._current_token)

        # Still showing the episode text -- the async arrival must not clobber it.
        self.assertEqual(panel._overview_label.text(), "Ep plot.\nAir date: 2023-01-01")

        panel.clear_episode_overview()
        # Restores the *remembered* (updated) series text, not the stale one
        # captured when the episode was expanded.
        self.assertEqual(panel._overview_label.text(), "NEW series overview")

    def test_repopulate_resets_episode_overview_active(self):
        """(A) Any re-populate of the table (filter change, checkbox toggle,
        roster reselect) goes through MediaWorkPanel.show_state() directly,
        which always collapses the expanded row in the model. The header
        flag must follow: after show_state() runs, the panel must be back
        in series mode, not stuck showing episode text with the flag still
        set."""
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state, guide = _guide_state()
        panel = MediaWorkPanel(media_type="tv", guide_provider=lambda _s: guide)
        panel.resize(760, 640)
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)

        panel.set_episode_overview("Ep plot.", "2023-01-01")
        self.assertTrue(panel._episode_overview_active)

        # Re-populate path (e.g. filter change / checkbox toggle / reselect).
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)

        self.assertFalse(panel._episode_overview_active)
        self.assertNotEqual(
            panel._overview_label.text(), "Ep plot.\nAir date: 2023-01-01"
        )

    def test_no_tmdb_overview_uses_single_display_path(self):
        """When no TMDB provider is available, _request_overview must use
        the same display path as async/cached branches to avoid leaving
        stale episode overview active -- collapsing an expanded episode
        with no TMDB should clear the series overview state, not restore
        previously-captured text."""
        panel = self._panel(media_type="tv", tmdb_provider=lambda: None)
        state, guide = _guide_state()
        panel.set_episode_overview("Episode text", "2024-01-01")
        self.assertTrue(panel._episode_overview_active)

        # Refresh with no TMDB provider.
        panel.refresh_header(state)

        # Must clear both the active flag and the series overview state.
        self.assertFalse(panel._episode_overview_active)
        self.assertEqual(panel._series_overview_text, "")
        self.assertFalse(panel._overview_label.isVisible())
        self.assertFalse(panel._overview_toggle.isVisible())


class MissingFileRowExpansionTests(QtSmokeBase):
    """Missing-file (ghost) episode rows must never expand (R2 M5): the
    chevron is already unpainted for them, but the expansion entry points
    (chevron click, Enter key, second-click, and the workspace-level
    on_table_expand_requested/on_table_row_clicked handlers) must all
    refuse to open a persistent editor for them."""

    @staticmethod
    def _make_episode_table_state():
        """One auto-assigned file at S01E01; S01E02 is left unassigned so the
        guide projects a "Missing File" ghost row for it."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        table.add_slot(EpisodeSlot(season=1, episode=2, title="Sequel"))
        entry = table.add_file(folder / "Season 01" / "Example.S01E01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )
        state.completeness = CompletenessReport(
            seasons={1: SeasonCompleteness(season=1, expected=2, matched=1, missing=[(2, "Sequel")])},
            specials=None,
            total_expected=2,
            total_matched=1,
            total_missing=[(1, 2, "Sequel")],
        )
        return state

    @staticmethod
    def _make_fake_media_ctrl(state):
        class _FakeMediaController:
            def __init__(self, s):
                self.command_gating = CommandGatingService()
                self.batch_states = [s]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        return _FakeMediaController(state)

    def _workspace_with_missing_file_row(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        return workspace, model, view

    @staticmethod
    def _first_row_with_status(model, status_text):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        for row in range(model.rowCount()):
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            if data is not None and data.status_text == status_text:
                return row
        raise AssertionError(f"no row with status_text={status_text!r}")

    def test_missing_file_row_never_expands(self):
        workspace, model, view = self._workspace_with_missing_file_row()
        row = self._first_row_with_status(model, "Missing File")
        workspace._on_table_expand_requested(model.index(row, 0))
        self.assertIsNone(model.expanded_row())
        workspace.close()


class AsyncPlanReflowTests(QtSmokeBase):
    """Task 8: the async plan_ready -> _refresh_widget repopulation of an
    expanded row's tracks widget must tell the view to re-measure the row
    (notify_expanded_row_changed), or a many-track plan landing after the
    editor's initial sizeHint() clips/overlaps."""

    @staticmethod
    def _make_state():
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        folder = Path("C:/library/tv/Reflow")
        show_info = {"id": 202, "name": "Reflow Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        entry = table.add_file(folder / "Season 01" / "Reflow.S01E01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 202, "media_name": "Reflow Show"},
        )
        return state

    def _make_settings(self):
        from plex_renamer.app.services.settings_service import SettingsService

        base = Path(self._main_window_tmp.name)
        svc = SettingsService(base / "automux_reflow.json")
        svc.automux_merge_subs = True
        svc.automux_merge_sub_languages = ["eng"]
        exe = base / "mkvmerge.exe"
        exe.write_bytes(b"")
        svc.mkvmerge_path = str(exe)
        return svc

    @staticmethod
    def _make_fake_media_ctrl(state):
        class _FakeMediaController:
            def __init__(self, s):
                self.command_gating = CommandGatingService()
                self.batch_states = [s]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = state.folder.parent
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        return _FakeMediaController(state)

    @staticmethod
    def _first_expandable_row(model):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        for row in range(model.rowCount()):
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            if data is not None and data.kind == "episode" and data.status_text != "Missing File":
                return row
        raise AssertionError("no expandable episode row found")

    def _expanded_episode_workspace(self):
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets import _media_workspace_automux as automux_mod
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state = self._make_state()
        settings = self._make_settings()
        ctrl = self._make_fake_media_ctrl(state)
        # The real background probe is irrelevant to this test -- the plan
        # arrival is driven directly through the bridge -- and letting it run
        # for real would race a live worker thread against test teardown.
        no_probe = patch.object(automux_mod, "_submit_bg", side_effect=lambda fn: None)
        no_probe.start()
        self.addCleanup(no_probe.stop)

        workspace = MediaWorkspace(
            media_type="tv", media_controller=ctrl, settings_service=settings,
        )
        workspace.resize(760, 640)
        workspace.show()
        workspace.show_ready()
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        row = self._first_expandable_row(model)
        workspace._on_table_expand_requested(model.index(row, 0))
        # The persistent editor (and its nested track-list QScrollArea) only
        # gets a real layout pass once posted LayoutRequest/Resize events are
        # pumped -- required for the "before" sizeHintForRow() to reflect the
        # editor's actual initial content rather than a stale default.
        self._app.processEvents()
        return workspace, state, view, model

    @staticmethod
    def _deliver_plan(workspace, state, *, tracks: int):
        decisions = [
            {"track_id": i, "track_type": "audio", "codec": "aac",
             "language": "eng", "name": f"Track {i}", "keep": True,
             "make_default": i == 0, "reason": "retained"}
            for i in range(tracks)
        ]
        plan = {
            "output_name": "Reflow.mkv",
            "track_decisions": decisions,
            "subtitle_merges": [],
            "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
            "warnings": [], "user_modified": False,
        }
        workspace._automux._bridge.plan_ready.emit(state, 0, plan, "")

    def test_async_plan_arrival_reflows_expanded_row(self):
        workspace, state, view, model = self._expanded_episode_workspace()
        before = view.sizeHintForRow(model.expanded_row())
        self._deliver_plan(workspace, state, tracks=30)
        self._app.processEvents()
        after = view.sizeHintForRow(model.expanded_row())
        self.assertNotEqual(before, after)
        workspace.close()


class PerEpisodeMuxOptOutTests(QtSmokeBase):
    """Round5 §4b: the expansion card's per-episode AutoMux opt-out button
    records the exclusion on ScanState.mux_opt_outs and refreshes every
    surface (collapsed row MUX pill, roster AutoMux chip)."""

    @staticmethod
    def _make_state():
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        folder = Path("C:/library/tv/OptOut")
        show_info = {"id": 303, "name": "OptOut Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        entry = table.add_file(folder / "Season 01" / "OptOut.S01E01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 303, "media_name": "OptOut Show"},
        )
        return state

    def _make_settings(self):
        from plex_renamer.app.services.settings_service import SettingsService

        base = Path(self._main_window_tmp.name)
        svc = SettingsService(base / "automux_optout.json")
        svc.automux_merge_subs = True
        svc.automux_merge_sub_languages = ["eng"]
        exe = base / "mkvmerge.exe"
        exe.write_bytes(b"")
        svc.mkvmerge_path = str(exe)
        return svc

    @staticmethod
    def _make_fake_media_ctrl(state):
        class _FakeMediaController:
            def __init__(self, s):
                self.command_gating = CommandGatingService()
                self.batch_states = [s]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = state.folder.parent
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        return _FakeMediaController(state)

    @staticmethod
    def _first_expandable_row(model):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        for row in range(model.rowCount()):
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            if data is not None and data.kind == "episode" and data.status_text != "Missing File":
                return row
        raise AssertionError("no expandable episode row found")

    @staticmethod
    def _action_plan():
        # One stripped audio track -> plan_has_actions() is True.
        return {
            "output_name": "OptOut.S01E01.mkv",
            "track_decisions": [
                {"track_id": 0, "track_type": "video", "codec": "h264",
                 "language": "und", "name": "", "keep": True,
                 "make_default": True, "reason": "kept"},
                {"track_id": 1, "track_type": "audio", "codec": "aac",
                 "language": "jpn", "name": "", "keep": False,
                 "make_default": False, "reason": "stripped"},
            ],
            "subtitle_merges": [],
            "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
            "warnings": [], "user_modified": False,
        }

    @staticmethod
    def _roster_has_automux_chip(workspace, state):
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE as RRD

        model = workspace._roster_panel.model
        state_index = workspace._current_states().index(state)
        row = model.row_for_state_index(state_index)
        data = model.index(row, 0).data(RRD)
        return any(chip.text == "AutoMux" for chip in data.chips)

    def _expanded_workspace(self):
        """Build a workspace whose selected show already has an action-bearing
        AutoMux plan cached for preview index 0, then expand that row (so the
        card is created with the plan present -- the normal warmed flow)."""
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets import _media_workspace_automux as automux_mod
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state = self._make_state()
        settings = self._make_settings()
        ctrl = self._make_fake_media_ctrl(state)
        # Drive the plan through the bridge directly; the real background probe
        # would race a live worker against teardown.
        no_probe = patch.object(automux_mod, "_submit_bg", side_effect=lambda fn: None)
        no_probe.start()
        self.addCleanup(no_probe.stop)

        workspace = MediaWorkspace(
            media_type="tv", media_controller=ctrl, settings_service=settings,
        )
        workspace.resize(760, 640)
        workspace.show()
        workspace.show_ready()
        # Warmed plan lands before the user expands the row.
        workspace._automux._bridge.plan_ready.emit(state, 0, self._action_plan(), "")
        self._app.processEvents()
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view
        row = self._first_expandable_row(model)
        workspace._on_table_expand_requested(model.index(row, 0))
        self._app.processEvents()
        return workspace, state, view, model

    def test_optout_button_excludes_file_and_drops_chips(self):
        from plex_renamer.app.services import automux_service

        workspace, state, view, model = self._expanded_workspace()

        row = model.expanded_row()
        self.assertTrue(automux_service.state_has_mux_actions(state))
        self.assertTrue(model.row_data_at(row).mux_active)
        self.assertTrue(self._roster_has_automux_chip(workspace, state))

        card = view.indexWidget(model.index(row, 0))
        button = card.mux_optout_button()
        self.assertIsNotNone(button)
        self.assertIn("Disable AutoMux", button.text())

        button.click()
        self._app.processEvents()

        # The exclusion is recorded and every surface follows it.
        self.assertEqual(state.mux_opt_outs, {0})
        self.assertFalse(model.row_data_at(row).mux_active)
        self.assertFalse(automux_service.state_has_mux_actions(state))
        self.assertFalse(self._roster_has_automux_chip(workspace, state))
        # The re-shown card now offers to re-enable AutoMux for this episode.
        card = view.indexWidget(model.index(row, 0))
        self.assertIn("Enable AutoMux", card.mux_optout_button().text())
        workspace.close()


class ExpansionCardHeaderTests(QtSmokeBase):
    """The expansion card must keep the episode title and status visible
    (R2 M3): the delegate stops painting the row when it expands, so the
    card's header row is the only place the title/status can show, and it
    must match the flat, square styling of a selected table row rather than
    the rounded "card" look."""

    def test_expansion_card_shows_episode_title_and_status(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        guide_row = guide.rows[0]  # season=1, episode=1, title="One", status="Mapped", "96%"

        card = EpisodeExpansionCard()
        card.show_episode(state, guide_row)

        assert f"S{guide_row.season:02d}E{guide_row.episode:02d}" in card._title_label.text()
        assert guide_row.title in card._title_label.text()
        assert card._status_pill.text().startswith(guide_row.status.upper())


class ExpansionViewportStabilityTests(QtSmokeBase):
    """Task 9: expanding an episode row mid-scroll must not lurch the
    viewport.

    Root cause (found by instrumenting the row-below-target's
    ``view.visualRect().top()`` across the expand call): ``set_expanded_row``
    fires ``dataChanged``/``sizeHintChanged`` for the target row *before*
    ``openPersistentEditor`` has created the editor widget, so
    ``EpisodeTableDelegate.sizeHint`` falls back to
    ``_FALLBACK_EXPANDED_HEIGHT_U`` (220px) for that first, synchronous
    relayout -- laying out every row below the expanded one at the wrong
    offset. The correct height (driven by the real editor's ``sizeHint()``,
    e.g. 430px with a populated AutoMux tracks list) only lands on a *later*,
    separately-triggered relayout (observed here: one extra
    ``QApplication.processEvents()`` pass), which is exactly the "expands,
    then after a delay snaps" symptom from the round5 feedback backlog.

    The target row's own on-screen top and the scrollbar value never move
    (growing a row cannot move its own top, and growth alone never forces a
    downward scrollbar clamp) -- those are asserted here as a stability
    belt-and-suspenders, but the row-below check is what actually pins the
    bug: it must already reflect the *real* editor height immediately after
    the expand call returns, with no extra event-loop pass required to
    settle."""

    _EPISODE_COUNT = 40
    _TARGET_EPISODE = 20

    @staticmethod
    def _make_state():
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        folder = Path("C:/library/tv/Lurch")
        show_info = {"id": 404, "name": "Lurch Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        for ep in range(1, ExpansionViewportStabilityTests._EPISODE_COUNT + 1):
            table.add_slot(EpisodeSlot(season=1, episode=ep, title=f"Episode {ep}"))
            entry = table.add_file(folder / "Season 01" / f"Lurch.S01E{ep:02d}.mkv")
            table.assign(entry.file_id, 1, [ep], origin=ORIGIN_AUTO, confidence=1.0)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 404, "media_name": "Lurch Show"},
        )
        return state

    def _make_settings(self):
        from plex_renamer.app.services.settings_service import SettingsService

        base = Path(self._main_window_tmp.name)
        svc = SettingsService(base / "automux_lurch.json")
        svc.automux_merge_subs = True
        svc.automux_merge_sub_languages = ["eng"]
        exe = base / "mkvmerge.exe"
        exe.write_bytes(b"")
        svc.mkvmerge_path = str(exe)
        return svc

    @staticmethod
    def _make_fake_media_ctrl(state):
        class _FakeMediaController:
            def __init__(self, s):
                self.command_gating = CommandGatingService()
                self.batch_states = [s]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = state.folder.parent
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        return _FakeMediaController(state)

    def _workspace(self):
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets import _media_workspace_automux as automux_mod
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state = self._make_state()
        settings = self._make_settings()
        ctrl = self._make_fake_media_ctrl(state)
        # Drive the AutoMux plan through the bridge directly -- the real
        # background probe would race a live worker thread against test
        # teardown (same rationale as AsyncPlanReflowTests above).
        no_probe = patch.object(automux_mod, "_submit_bg", side_effect=lambda fn: None)
        no_probe.start()
        self.addCleanup(no_probe.stop)

        workspace = MediaWorkspace(
            media_type="tv", media_controller=ctrl, settings_service=settings,
        )
        # A small viewport relative to 40 rows guarantees the list is
        # scrollable and a mid-list row can sit mid-viewport.
        workspace.resize(760, 480)
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()
        return workspace, state

    @staticmethod
    def _row_for_episode(model, episode: int):
        # Same lookup the expand path itself uses (model.guide_row_at).
        for row in range(model.rowCount()):
            guide_row = model.guide_row_at(row)
            if guide_row is not None and guide_row.episode == episode:
                return row
        raise AssertionError(f"no row found for episode {episode}")

    @staticmethod
    def _warm_plan(workspace, state, preview_index: int, *, tracks: int) -> None:
        """Land a many-track AutoMux plan for *preview_index* before the row
        is ever expanded -- the normal "warmed" flow (Task 4) -- so the
        expansion card is built with a fully populated tracks widget from
        the start (a large, real jump in editor height: ~52px collapsed to
        several hundred px expanded), matching the real-world conditions
        where the fallback-vs-actual height gap is large enough to matter."""
        decisions = [
            {"track_id": i, "track_type": "audio", "codec": "aac",
             "language": "eng", "name": f"Track {i}", "keep": True,
             "make_default": i == 0, "reason": "retained"}
            for i in range(tracks)
        ]
        plan = {
            "output_name": "Lurch.mkv",
            "track_decisions": decisions,
            "subtitle_merges": [],
            "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
            "warnings": [], "user_modified": False,
        }
        workspace._automux._bridge.plan_ready.emit(state, preview_index, plan, "")

    def test_expanding_row_keeps_viewport_framing_stable(self):
        from PySide6.QtWidgets import QAbstractItemView

        workspace, state = self._workspace()
        model = workspace._work_panel.model
        view = workspace._work_panel.table_view

        target_row = self._row_for_episode(model, self._TARGET_EPISODE)
        target_index = model.index(target_row, 0)
        below_index = model.index(target_row + 1, 0)

        preview_index = next(
            i for i, item in enumerate(state.preview_items)
            if item.episodes == [self._TARGET_EPISODE]
        )
        self._warm_plan(workspace, state, preview_index, tracks=30)
        self._app.processEvents()

        # Position the target row mid-viewport before expanding.
        view.setCurrentIndex(target_index)
        view.scrollTo(target_index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._app.processEvents()

        before_top = view.visualRect(target_index).top()
        before_scroll = view.verticalScrollBar().value()

        workspace._on_table_expand_requested(target_index)

        # No processEvents yet: this is what a single synchronous click
        # handler leaves behind before Qt's event loop runs again. The row
        # below the expanded one must already reflect the *real* editor
        # height here -- not a placeholder later corrected by some
        # unrelated, indirectly-triggered relayout.
        expected_below_top = before_top + view.sizeHintForRow(target_row)
        self.assertEqual(
            view.visualRect(below_index).top(), expected_below_top,
            "the row below the expanded one used a stale/fallback height "
            "immediately after expansion -- the real correction landed "
            "later (the delayed 'snap' this test guards against)",
        )

        for _ in range(5):
            self._app.processEvents()

        after_top = view.visualRect(target_index).top()
        after_scroll = view.verticalScrollBar().value()

        self.assertEqual(
            before_top, after_top,
            "expanding the row moved its on-screen top position",
        )
        self.assertEqual(
            before_scroll, after_scroll,
            "expanding the row changed the scrollbar value",
        )
        self.assertEqual(
            view.visualRect(below_index).top(), expected_below_top,
            "the row below the expanded one moved after settling -- a "
            "delayed relayout changed the layout further",
        )
        workspace.close()


class OptedOutMuxPlanNotFedToCardTests(QtSmokeBase):
    """Final whole-branch review Finding 1 (round5): once an episode is
    opted out of AutoMux (state.mux_opt_outs), MediaWorkspaceStateCoordinator
    ._feed_card must stop handing the card that episode's stale mux_plan --
    otherwise the card still thinks the subtitle got merged by AutoMux and
    hides the Subtitle Output row / prints the "merged into the video" note,
    even though the opted-out file gets a standalone rename op in the real
    bake."""

    class _FakeAutoMux:
        def tracks_widget_for(self, state, preview_index):
            return None

    class _FakeWorkspace:
        def __init__(self):
            self._automux = OptedOutMuxPlanNotFedToCardTests._FakeAutoMux()

    def _feed_card(self, state, guide_row):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard
        from plex_renamer.gui_qt.widgets._media_workspace_state import (
            MediaWorkspaceStateCoordinator,
        )

        coordinator = MediaWorkspaceStateCoordinator(self._FakeWorkspace())
        card = EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        coordinator._feed_card(card, state, guide_row, ())
        return card

    def test_optout_suppresses_merged_note_and_keeps_output_row(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]  # "One" -> preview_items[0], has a subtitle companion
        sub = next(c for c in row.companions if c.file_type == "subtitle")
        state.mux_plans[0] = {
            "track_decisions": [],
            "subtitle_merges": [{
                "action": "merge",
                "source_relative": str(sub.original).replace("\\", "/"),
                "language": "eng",
            }],
        }
        state.mux_opt_outs.add(0)

        card = self._feed_card(state, row)

        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertFalse(
            any("merged into the video" in t for t in texts),
            "card still claims an opted-out subtitle was merged by AutoMux",
        )
        self.assertTrue(any("Subtitle Output" in t for t in texts))
        button = card.mux_optout_button()
        self.assertIsNotNone(button)
        self.assertIn("Enable AutoMux", button.text())

    def test_non_optout_still_shows_merged_note(self):
        """Control: without the opt-out, the same plan still suppresses the
        Subtitle Output row and shows the merged note -- confirms the fix is
        gated on mux_opt_outs, not a blanket change to mux_plan feeding."""
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]
        sub = next(c for c in row.companions if c.file_type == "subtitle")
        state.mux_plans[0] = {
            "track_decisions": [],
            "subtitle_merges": [{
                "action": "merge",
                "source_relative": str(sub.original).replace("\\", "/"),
                "language": "eng",
            }],
        }

        card = self._feed_card(state, row)

        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertTrue(any("merged into the video" in t for t in texts))
        self.assertFalse(any("Subtitle Output" in t for t in texts))
        button = card.mux_optout_button()
        self.assertIsNotNone(button)
        self.assertIn("Disable AutoMux", button.text())
