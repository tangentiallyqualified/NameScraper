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
    def _panel(self, media_type="tv"):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type=media_type)
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
