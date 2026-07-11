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
