# tests/test_episode_expansion.py
"""Expansion card content, actions, copy behavior."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class EpisodeExpansionCardTests(QtSmokeBase):
    def _card(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard
        return EpisodeExpansionCard()

    def _card_with_episode(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard
        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        return card

    def test_title_is_regular_weight(self):
        card = self._card_with_episode()
        self.assertNotEqual(card._title_label.property("cssClass"), "row-title")

    def test_click_anywhere_on_header_collapses(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        card = self._card_with_episode()
        card.resize(600, 300)
        card.show()
        QTest.qWaitForWindowExposed(card)
        fired = []
        card.collapse_requested.connect(lambda: fired.append(True))
        header = card._header_widget
        QTest.mouseClick(header, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(header.width() - 10, header.height() // 2))
        self.assertTrue(fired)

    def test_right_click_on_header_does_not_collapse(self):
        # Final-review fix: mousePressEvent used to collapse on ANY button,
        # so a right-click (which normally opens a context menu elsewhere)
        # would also collapse the card.
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        card = self._card_with_episode()
        card.resize(600, 300)
        card.show()
        QTest.qWaitForWindowExposed(card)
        fired = []
        card.collapse_requested.connect(lambda: fired.append(True))
        header = card._header_widget
        QTest.mouseClick(header, Qt.MouseButton.RightButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(header.width() - 10, header.height() // 2))
        self.assertFalse(fired)

    def test_episode_content_and_actions(self):
        from PySide6.QtWidgets import QLabel
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard, episode_row_actions,
        )

        state, guide = _guide_state()
        review_row = guide.rows[1]
        card = EpisodeExpansionCard()
        card.show_episode(state, review_row)
        texts = [label.text() for label in card.findChildren(QLabel)]
        self.assertTrue(any("s01e02.mkv" in text for text in texts))
        self.assertTrue(any("Show - S01E02 - Two.mkv" in text for text in texts))
        action_ids = [action_id for action_id, _label in episode_row_actions(review_row)]
        self.assertEqual(action_ids, ["approve", "reassign", "assign_to_more", "unassign"])
        from PySide6.QtWidgets import QPushButton

        # The old disabled "Merge…" stub is gone — AutoMux tracks sections
        # (added via add_tracks_widget) supersede it.
        merge_buttons = [b for b in card.findChildren(QPushButton) if b.text() == "Merge…"]
        self.assertEqual(merge_buttons, [])

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

    def test_open_dir_signal_exists(self):
        card = self._card()
        self.assertTrue(hasattr(card, "open_dir_requested"))

    def test_labels_present_for_source_and_output(self):
        from PySide6.QtWidgets import QLabel

        card = self._card()
        card._build_labeled_path("Episode Source", r"C:\lib\show\ep.mkv", open_dir=True)
        card._build_labeled_path("Episode Output", r"C:\out\show\S01E01.mkv", open_dir=False)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertTrue(any("Episode Source" in t for t in texts))
        self.assertTrue(any("Episode Output" in t for t in texts))

    def test_collapse_button_left_aligned(self):
        card = self._card()
        card.show()
        self.assertLess(card._collapse_button.x(), card.width() // 2)

    def test_show_episode_renders_source_and_output_rows_no_copy_button(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]
        card = self._card()
        card.show_episode(state, row)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertTrue(any("Episode Source" in t and "s01e01.mkv" in t for t in texts))
        self.assertTrue(any("Episode Output" in t and "Show - S01E01 - One.mkv" in t for t in texts))
        # No copy button should remain on the source row.
        self.assertEqual(card._copy_buttons, [])

    def test_show_episode_renders_subtitle_rows_when_companion_present(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]  # has a subtitle companion in the fixture
        card = self._card()
        card.show_episode(state, row)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertTrue(any("Subtitle Source" in t and "s01e01.en.srt" in t for t in texts))
        self.assertTrue(
            any("Subtitle Output" in t and "Show - S01E01 - One.en.srt" in t for t in texts)
        )

    def test_show_episode_omits_subtitle_rows_when_no_companion(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[1]  # no companions in the fixture
        card = self._card()
        card.show_episode(state, row)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertFalse(any("Subtitle Source" in t for t in texts))
        self.assertFalse(any("Subtitle Output" in t for t in texts))

    def test_open_dir_button_emits_source_parent_directory(self):
        state, guide = _guide_state()
        row = guide.rows[0]
        card = self._card()
        card.show_episode(state, row)
        fired: list[str] = []
        card.open_dir_requested.connect(fired.append)
        card._open_dir_buttons[0].click()
        self.assertEqual(fired, [str(Path(row.primary_file.original).parent)])

    def test_missing_file_row_offers_assign(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import episode_row_actions

        _state, guide = _guide_state()
        ghost = guide.rows[2]
        self.assertEqual(episode_row_actions(ghost), [("assign_file", "Assign file...")])

    def test_companion_subtitle_rows_labeled_instead_of_badged(self):
        # M9: labeled Subtitle Source/Output rows replace the old badge+copy
        # per-file rows — the label text itself conveys the companion type.
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
        texts = [label.text() for label in card.findChildren(QLabel)]
        self.assertTrue(any("Subtitle Source" in t and "s01e01.eng.srt" in t for t in texts))
        self.assertTrue(
            any("Subtitle Output" in t and "Show - S01E01 - One.eng.srt" in t for t in texts)
        )

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

    def test_collapse_button_matches_row_chevron_family(self):
        from plex_renamer.gui_qt.widgets import _episode_expansion as exp

        self.assertEqual(exp._COLLAPSE_GLYPH, "▾")
        card = exp.EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        self.assertEqual(card._collapse_button.property("cssClass"), "expansion-collapse")

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

    def test_actions_row_is_above_files_section(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        card = EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        outer = card.layout()
        indexes = {outer.itemAt(i).layout(): i for i in range(outer.count())}
        self.assertLess(indexes[card._actions_row], indexes[card._files_section])

    def test_merged_subtitle_hides_output_row(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]  # has a subtitle companion in the fixture
        sub = next(c for c in row.companions if c.file_type == "subtitle")
        plan = {"subtitle_merges": [{
            "action": "merge",
            "source_relative": str(sub.original).replace("\\", "/"),
            "language": "eng",
        }]}
        card = self._card()
        card.show_episode(state, row, mux_plan=plan)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertFalse(any("Subtitle Output" in t for t in texts))
        self.assertTrue(any("Subtitle Source" in t for t in texts))
        self.assertTrue(any("merged into the video" in t for t in texts))

    def test_non_merged_subtitle_still_shows_output_row(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]  # has a subtitle companion in the fixture
        sub = next(c for c in row.companions if c.file_type == "subtitle")
        plan = {"subtitle_merges": [{
            "action": "rename",
            "source_relative": str(sub.original).replace("\\", "/"),
            "language": "eng",
        }]}
        card = self._card()
        card.show_episode(state, row, mux_plan=plan)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertTrue(any("Subtitle Output" in t for t in texts))

    def test_no_mux_plan_still_shows_output_row(self):
        from PySide6.QtWidgets import QLabel

        state, guide = _guide_state()
        row = guide.rows[0]  # has a subtitle companion in the fixture
        card = self._card()
        card.show_episode(state, row)
        texts = [w.text() for w in card.findChildren(QLabel)]
        self.assertTrue(any("Subtitle Output" in t for t in texts))

    def test_path_rows_bold_their_labels(self):
        from PySide6.QtWidgets import QLabel

        card = self._card()
        self.addCleanup(card.deleteLater)
        card._build_labeled_path("Episode Source", r"C:\media\a<b>.mkv", open_dir=False)
        row = card._files_section.itemAt(card._files_section.count() - 1).widget()
        label = row.layout().itemAt(0).widget()
        self.assertIn("<b>Episode Source:</b>", label.text())
        self.assertIn("&lt;b&gt;", label.text())   # path is HTML-escaped
