# tests/test_episode_expansion.py
"""Expansion card content, actions, copy behavior."""
from __future__ import annotations

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class EpisodeExpansionCardTests(QtSmokeBase):
    def test_episode_content_and_actions(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard, episode_row_actions,
        )

        state, guide = _guide_state()
        review_row = guide.rows[1]
        card = EpisodeExpansionCard()
        card.show_episode(state, review_row)
        texts = [label.text() for label in card.findChildren(type(card._target_label))]
        self.assertTrue(any("s01e02.mkv" in text for text in texts))
        self.assertTrue(any("Show - S01E02 - Two.mkv" in text for text in texts))
        action_ids = [action_id for action_id, _label in episode_row_actions(review_row)]
        self.assertEqual(action_ids, ["approve", "reassign", "assign_to_more", "unassign"])
        from PySide6.QtWidgets import QPushButton

        merge_buttons = [b for b in card.findChildren(QPushButton) if b.text() == "Merge…"]
        self.assertEqual(len(merge_buttons), 1)
        self.assertFalse(merge_buttons[0].isEnabled())

    def test_action_button_emits_id(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[1])
        fired: list[str] = []
        card.action_requested.connect(fired.append)
        approve = next(b for b in card._action_buttons if b.property("actionId") == "approve")
        approve.click()
        self.assertEqual(fired, ["approve"])

    def test_copy_button_sets_clipboard(self):
        from PySide6.QtWidgets import QApplication
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        card._copy_buttons[0].click()
        self.assertIn("s01e01.mkv", QApplication.clipboard().text())

    def test_missing_file_row_offers_assign(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import episode_row_actions

        _state, guide = _guide_state()
        ghost = guide.rows[2]
        self.assertEqual(episode_row_actions(ghost), [("assign_file", "Assign file...")])
