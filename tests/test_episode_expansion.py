# tests/test_episode_expansion.py
"""Expansion card content, actions, copy behavior."""
from __future__ import annotations

from pathlib import Path

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

    def test_companion_rows_carry_type_badges(self):
        from PySide6.QtWidgets import QLabel
        from plex_renamer.engine import CompanionFile
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        row = guide.rows[0]
        row.companions = [
            CompanionFile(
                original=Path("C:/lib/Show/s01e01.eng.srt"),
                new_name="Show - S01E01 - One.eng.srt",
                file_type="subtitle",
            )
        ]
        card = EpisodeExpansionCard()
        card.show_episode(state, row)
        badges = [
            label.text()
            for label in card.findChildren(QLabel)
            if label.property("cssClass") == "badge"
        ]
        self.assertEqual(badges, ["SUB"])

    def test_multi_part_claims_render_part_chips(self):
        # §13 seam: today's engine marks every multi-claimed slot a conflict,
        # so this exercises the view contract under the future ROLE_VERSION
        # policy (2 claims, neither conflicted) via a stub table.
        from plex_renamer.engine.episode_assignments import Assignment
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard,
            _ChipStrip,
        )

        state, guide = _guide_state()

        class _VersionPolicyTable:
            def claims(self, season, episode):
                if (season, episode) == (1, 1):
                    return [
                        Assignment(file_id=1, season=1, episodes=(1,),
                                   origin="manual", confidence=1.0),
                        Assignment(file_id=2, season=1, episodes=(1,),
                                   origin="manual", confidence=1.0),
                    ]
                return []

            def conflicted_file_ids(self):
                return set()

        state.assignments = _VersionPolicyTable()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        strips = card.findChildren(_ChipStrip)
        self.assertEqual(len(strips), 1)
        self.assertEqual([spec.text for spec in strips[0]._specs], ["Part 1", "Part 2"])
        self.assertEqual({spec.tone for spec in strips[0]._specs}, {"muted"})

    def test_conflicted_claims_do_not_render_part_chips(self):
        from plex_renamer.engine.episode_assignments import Assignment
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard,
            _ChipStrip,
        )

        state, guide = _guide_state()

        class _ConflictTable:
            def claims(self, season, episode):
                if (season, episode) == (1, 1):
                    return [
                        Assignment(file_id=1, season=1, episodes=(1,),
                                   origin="auto", confidence=0.9),
                        Assignment(file_id=2, season=1, episodes=(1,),
                                   origin="auto", confidence=0.8),
                    ]
                return []

            def conflicted_file_ids(self):
                return {1, 2}   # today's real policy: both claimants conflicted

        state.assignments = _ConflictTable()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        self.assertEqual(card.findChildren(_ChipStrip), [])
