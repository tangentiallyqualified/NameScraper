# tests/test_workspace_expansion.py
"""Header description follows the expanded episode (M10): the work panel's
header overview swaps to the expanded episode's overview/air-date and
reverts to the remembered series overview on collapse."""
from __future__ import annotations

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
