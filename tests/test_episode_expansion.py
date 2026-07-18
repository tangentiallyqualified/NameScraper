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
        QTest.mouseClick(
            header,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(header.width() - 10, header.height() // 2),
        )
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
        QTest.mouseClick(
            header,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(header.width() - 10, header.height() // 2),
        )
        self.assertFalse(fired)

    def test_episode_content_and_actions(self):
        from PySide6.QtWidgets import QLabel

        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard,
            episode_row_actions,
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
        self.assertTrue(
            any("Episode Output" in t and "Show - S01E01 - One.mkv" in t for t in texts)
        )
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
                        Assignment(
                            file_id=1, season=1, episodes=(1,), origin="manual", confidence=1.0
                        ),
                        Assignment(
                            file_id=2, season=1, episodes=(1,), origin="manual", confidence=1.0
                        ),
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
                        Assignment(
                            file_id=1, season=1, episodes=(1,), origin="auto", confidence=0.9
                        ),
                        Assignment(
                            file_id=2, season=1, episodes=(1,), origin="auto", confidence=0.8
                        ),
                    ]
                return []

            def conflicted_file_ids(self):
                return {1, 2}  # today's real policy: both claimants conflicted

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
        plan = {
            "subtitle_merges": [
                {
                    "action": "merge",
                    "source_relative": str(sub.original).replace("\\", "/"),
                    "language": "eng",
                }
            ]
        }
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
        plan = {
            "subtitle_merges": [
                {
                    "action": "rename",
                    "source_relative": str(sub.original).replace("\\", "/"),
                    "language": "eng",
                }
            ]
        }
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

    # -- Round5 §4a header parity + §4b per-episode opt-out ---------------

    def test_header_hosts_above_fold_actions_and_right_aligned_pill(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        review_row = guide.rows[1]  # Review, confidence 61%
        card = EpisodeExpansionCard()
        card.show_episode(
            state,
            review_row,
            mux_plan=None,
            preview_index=0,
            above_fold_ids=("approve", "reassign", "unassign"),
        )
        header_buttons = [b.property("actionId") for b in card.header_action_buttons()]
        self.assertEqual(header_buttons, ["approve", "reassign", "unassign"])
        below = [b.property("actionId") for b in card.action_buttons()]
        self.assertNotIn("approve", below)
        self.assertNotIn("reassign", below)
        self.assertNotIn("unassign", below)
        self.assertIn("assign_to_more", below)
        # Pill mirrors the collapsed row's text and is the LAST widget in the
        # header row (far right, after the above-fold buttons).
        self.assertEqual(card.status_pill_text(), "REVIEW 61%")
        header_row = card._header_row
        self.assertIs(header_row.itemAt(header_row.count() - 1).widget(), card._status_pill)

    def test_header_pill_uses_review_confidence_band_tone(self):
        # Delegate parity: a 61% Review row lands in the mid band -> warning,
        # not the flat Review tone (round5 §4a mirrors pill_tone bands).
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[1], above_fold_ids=("approve",))
        self.assertEqual(card._status_pill.property("tone"), "warning")

    # -- Round6 Task 6: header column parity + capsule pill ----------------

    def test_header_actions_stack_under_pill(self):
        # Geometry contract v2 mirrored on the card (Task 6): above-fold
        # buttons form a right-aligned vertical column directly under the
        # pill, not siblings in the header row -- "the row grew in place."
        from PySide6.QtTest import QTest

        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        review_row = guide.rows[1]  # Review, confidence 61%
        card = EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        card.show_episode(
            state,
            review_row,
            mux_plan=None,
            preview_index=0,
            above_fold_ids=("approve", "reassign", "unassign"),
        )
        buttons = card.header_action_buttons()
        self.assertEqual(
            [b.property("actionId") for b in buttons],
            ["approve", "reassign", "unassign"],
        )
        self.assertTrue(all(b.property("cssClass") == "row-action" for b in buttons))
        card.resize(600, 300)
        card.show()
        QTest.qWaitForWindowExposed(card)
        self._app.processEvents()
        pill = card._status_pill
        # Buttons live directly under `card`; the pill lives under
        # `_header_widget` -- map both right edges into card-local
        # coordinates before comparing (mapTo, not raw .geometry(), since
        # the two widgets sit in different parent frames).
        pill_right = pill.mapTo(card, pill.rect().topRight()).x()
        pill_bottom = pill.mapTo(card, pill.rect().bottomLeft()).y()
        for button in buttons:
            button_right = button.mapTo(card, button.rect().topRight()).x()
            self.assertLessEqual(abs(button_right - pill_right), 2)
        ys = [button.geometry().y() for button in buttons]
        self.assertEqual(ys, sorted(ys))
        self.assertGreater(ys[0], pill_bottom)

    def test_status_pill_is_a_capsule(self):
        # Root-cause fix: theme radius_pill=10 exceeds half of a ~16px label
        # height, so Qt silently drops the QSS border-radius and the pill
        # paints as a rectangle. The new class fixes the height to the
        # delegate's pill height and uses a radius <= half of it.
        from PySide6.QtTest import QTest

        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard
        from plex_renamer.gui_qt.widgets._episode_table_delegate import _PILL_H_U

        state, guide = _guide_state()
        mapped_row = guide.rows[0]
        card = EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        card.show_episode(state, mapped_row, preview_index=0)
        card.resize(600, 300)
        card.show()
        QTest.qWaitForWindowExposed(card)
        self._app.processEvents()
        pill = card._status_pill
        self.assertEqual(pill.height(), _scale.px(_PILL_H_U))
        self.assertEqual(pill.property("cssClass"), "expansion-pill")

    def test_mux_optout_button_toggles_and_reflects_state(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        mapped_row = guide.rows[0]
        plan = {
            "track_decisions": [],
            "subtitle_merges": [{"action": "merge", "source_relative": "x.srt", "language": "eng"}],
        }
        state.mux_plans[0] = plan
        card = EpisodeExpansionCard()
        card.show_episode(state, mapped_row, mux_plan=state.mux_plans[0], preview_index=0)
        button = card.mux_optout_button()
        self.assertIsNotNone(button)
        self.assertIn("Disable AutoMux", button.text())
        state.mux_opt_outs.add(0)
        card.show_episode(state, mapped_row, mux_plan=state.mux_plans[0], preview_index=0)
        self.assertIn("Enable AutoMux", card.mux_optout_button().text())

    def test_mux_optout_button_absent_without_plan(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0], mux_plan=None, preview_index=0)
        self.assertIsNone(card.mux_optout_button())

    def test_mux_optout_button_click_emits_toggle_signal(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        plan = {
            "subtitle_merges": [{"action": "merge", "source_relative": "x.srt", "language": "eng"}]
        }
        state.mux_plans[0] = plan
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0], mux_plan=plan, preview_index=0)
        fired: list[bool] = []
        card.mux_optout_toggled.connect(lambda: fired.append(True))
        card.mux_optout_button().click()
        self.assertEqual(fired, [True])

    def test_episode_row_actions_vocabulary_is_frozen(self):
        # The frozen contract: ids/order for every status must not change.
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets._episode_expansion import episode_row_actions

        def ids(status):
            row = EpisodeGuideRow(season=1, episode=1, title="X", status=status)
            return [aid for aid, _ in episode_row_actions(row)]

        self.assertEqual(ids("Missing File"), ["assign_file"])
        self.assertEqual(
            ids("Conflict"),
            ["keep_this", "reassign", "assign_to_more", "unassign"],
        )
        self.assertEqual(ids("Review"), ["approve", "reassign", "assign_to_more", "unassign"])
        self.assertEqual(ids("Mapped"), ["reassign", "assign_to_more", "unassign"])

    # -- Task 7 (spec §4): tracks-widget whitespace diagnosis -------------

    def _expected_card_height(self, card, tracks):
        """margins + header row + one spacing gap + the tracks widget's OWN
        sizeHint() -- deliberately NOT card._files_section.sizeHint() or
        card.layout().sizeHint(), which share the exact
        widget.sizeHint().expandedTo(widget.minimumSizeHint()) path under
        test (see test_card_height_matches_tracks_content_no_extra_whitespace)
        and would silently agree with a still-inflated card total instead of
        catching it."""
        outer = card.layout()
        margins = outer.contentsMargins()
        header_height = card._header_widget.sizeHint().height()
        return (
            margins.top()
            + margins.bottom()
            + header_height
            + outer.spacing()
            + tracks.sizeHint().height()
        )

    def test_card_height_matches_tracks_content_no_extra_whitespace(self):
        # Step 2 diagnosis (task-7-report.md): AutoMuxTracksWidget only
        # overrode sizeHint(), not minimumSizeHint() -- Qt's
        # QWidgetItem.sizeHint() (used by ANY parent layout measuring the
        # widget as a layout item, e.g. this card's _files_section) computes
        # widget.sizeHint().expandedTo(widget.minimumSizeHint()), and the
        # un-overridden default minimumSizeHint() walks the tracks widget's
        # OWN internal layout -- including _rows_scroll, a QScrollArea whose
        # default minimumSizeHint() is a roughly-constant, content-blind
        # floor (~frame + scrollbar chrome) -- so whenever real content is
        # smaller than that floor (probing/error/no-actions placeholder,
        # or few tracks) the card silently reserves the floor's height
        # instead of the content's -- extra whitespace.
        #
        # A card populated directly via a 3-track show_plan() (the brief's
        # literal recipe) does NOT reliably discriminate this bug offscreen:
        # 3 checkbox rows happen to land close enough to the QScrollArea's
        # content-blind floor (~108px here) that the gap is only ~4px,
        # under most reasonable tolerances. The placeholder/probing state is
        # the discriminating snapshot -- its content (~40px) sits ~68px
        # below that same floor. Verified per Step 2's instructions:
        # reproduced with the async re-measure sequence in the test below
        # once the direct-populate snapshot alone proved inconclusive.
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._automux_tracks import AutoMuxTracksWidget
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        card = EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        tracks = AutoMuxTracksWidget()
        tracks.show_probing()
        card.add_tracks_widget(tracks)
        card.show()
        self._app.processEvents()
        self._app.processEvents()

        expected = self._expected_card_height(card, tracks)
        actual = card.sizeHint().height()
        self.assertLessEqual(
            abs(actual - expected),
            _scale.px(8),
            f"card.sizeHint() reports {actual}px but the visible sections "
            f"(header + tracks {tracks.sizeHint().height()}px + "
            f"margins/spacing) only need {expected}px "
            f"({actual - expected}px of extra whitespace)",
        )

    def test_card_height_tracks_late_plan_arrival_no_stale_floor(self):
        # Reproduces the async re-measure sequence per Step 2's instructions
        # (populate probing -> show_plan later) so the fix is verified under
        # the same real bridge-style arrival pattern Task 4 investigated --
        # both immediately after the synchronous show_plan() call returns
        # (no processEvents() gap, Task 4-style) and once real 3-track
        # content has landed (the brief's literal plan size).
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._automux_tracks import AutoMuxTracksWidget
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        plan = {
            "output_name": "X.mkv",
            "track_decisions": [
                {
                    "track_id": i,
                    "track_type": "audio",
                    "codec": "aac",
                    "language": "eng",
                    "name": "",
                    "keep": True,
                    "make_default": i == 0,
                    "reason": "retained",
                }
                for i in range(3)
            ],
            "subtitle_merges": [],
            "strip_track_names": False,
            "no_fear": False,
            "mkvmerge_path": "",
            "warnings": [],
            "user_modified": False,
        }
        card = EpisodeExpansionCard()
        self.addCleanup(card.deleteLater)
        tracks = AutoMuxTracksWidget()
        tracks.show_probing()
        card.add_tracks_widget(tracks)
        card.show()
        self._app.processEvents()
        self._app.processEvents()

        tracks.show_plan(plan)
        immediate = card.sizeHint().height()
        self._app.processEvents()
        self._app.processEvents()
        settled = card.sizeHint().height()

        # The card must reflect the real plan's content immediately -- not
        # stay pinned at a stale/floor height across the async arrival.
        self.assertEqual(
            immediate,
            settled,
            "card.sizeHint() changed after processEvents() -- the plan's "
            "arrival was not reflected immediately",
        )
        expected = self._expected_card_height(card, tracks)
        self.assertLessEqual(
            abs(settled - expected),
            _scale.px(8),
            f"card.sizeHint() reports {settled}px but the visible sections "
            f"only need {expected}px ({settled - expected}px of extra "
            "whitespace)",
        )

    def test_path_rows_bold_their_labels(self):

        card = self._card()
        self.addCleanup(card.deleteLater)
        card._build_labeled_path("Episode Source", r"C:\media\a<b>.mkv", open_dir=False)
        row = card._files_section.itemAt(card._files_section.count() - 1).widget()
        label = row.layout().itemAt(0).widget()
        self.assertIn("<b>Episode Source:</b>", label.text())
        self.assertIn("&lt;b&gt;", label.text())  # path is HTML-escaped
