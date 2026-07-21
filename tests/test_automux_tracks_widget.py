"""Tracks section widget: rendering, editing, safety floor, locking."""

from __future__ import annotations

from conftest_qt import QtSmokeBase

PLAN = {
    "output_name": "X.mkv",
    "track_decisions": [
        {
            "track_id": 0,
            "track_type": "video",
            "codec": "h264",
            "language": "und",
            "name": "",
            "keep": True,
            "make_default": True,
            "reason": "video",
        },
        {
            "track_id": 1,
            "track_type": "audio",
            "codec": "aac",
            "language": "eng",
            "name": "",
            "keep": True,
            "make_default": True,
            "reason": "retained",
        },
        {
            "track_id": 2,
            "track_type": "subtitles",
            "codec": "srt",
            "language": "fre",
            "name": "",
            "keep": False,
            "make_default": False,
            "reason": "not in retain list",
        },
    ],
    "subtitle_merges": [
        {
            "source_relative": "Show/a.eng.srt",
            "action": "merge",
            "language": "eng",
            "set_default": False,
        },
    ],
    "strip_track_names": False,
    "no_fear": False,
    "mkvmerge_path": "",
    "warnings": [],
    "user_modified": False,
}


class AutoMuxTracksWidgetTests(QtSmokeBase):
    def _widget(self):
        from plex_renamer.gui_qt.widgets._automux_tracks import (
            AutoMuxTracksWidget,
        )

        return AutoMuxTracksWidget()

    def _boxes(self, widget):
        from PySide6.QtWidgets import QCheckBox

        return widget._rows_host.findChildren(QCheckBox)

    def _plan_with_tracks(self, count=30):
        decisions = [
            {
                "track_id": i,
                "track_type": "audio",
                "codec": "aac",
                "language": "eng",
                "name": f"Track {i}",
                "keep": True,
                "make_default": i == 0,
                "reason": "retained",
            }
            for i in range(count)
        ]
        return {
            "output_name": "Many.mkv",
            "track_decisions": decisions,
            "subtitle_merges": [],
            "strip_track_names": False,
            "no_fear": False,
            "mkvmerge_path": "",
            "warnings": [],
            "user_modified": False,
        }

    def test_show_plan_renders_rows(self):
        widget = self._widget()
        widget.show_plan(PLAN)
        boxes = self._boxes(widget)
        self.assertEqual(len(boxes), 4)  # 3 embedded + 1 merge
        video_box = boxes[0]
        self.assertFalse(video_box.isEnabled())  # video is never editable
        self.assertFalse(boxes[2].isChecked())  # stripped sub unchecked
        self.assertTrue(boxes[3].isChecked())  # merge checked

    def test_edit_emits_user_modified_plan(self):
        widget = self._widget()
        widget.show_plan(PLAN)
        emitted = []
        widget.plan_edited.connect(emitted.append)
        self._boxes(widget)[3].setChecked(False)  # merge → rename
        self.assertEqual(len(emitted), 1)
        plan = emitted[0]
        self.assertTrue(plan["user_modified"])
        self.assertEqual(plan["subtitle_merges"][0]["action"], "rename")
        # Original input dict is never mutated.
        self.assertEqual(PLAN["subtitle_merges"][0]["action"], "merge")
        self.assertFalse(PLAN["user_modified"])

    def test_last_audio_track_cannot_be_stripped(self):
        widget = self._widget()
        widget.show_plan(PLAN)
        emitted = []
        widget.plan_edited.connect(emitted.append)
        audio_box = self._boxes(widget)[1]
        audio_box.setChecked(False)
        self.assertTrue(audio_box.isChecked())  # snapped back
        self.assertEqual(emitted, [])  # no edit emitted

    def test_locked_disables_all_controls(self):
        widget = self._widget()
        widget.show_plan(PLAN, locked=True)
        self.assertTrue(all(not b.isEnabled() for b in self._boxes(widget)))

    def test_many_tracks_height_is_capped_and_scrollable(self):
        widget = self._widget()
        plan = self._plan_with_tracks(count=30)
        widget.show_plan(plan)
        widget.adjustSize()
        from plex_renamer.gui_qt import _scale

        # Task 7: the notice moved inline onto the heading row (no separate
        # bottom row), so the cap-plus-slack tolerance dropped from the
        # pre-Task-7 formula's +80 (heading row + row cap + a standalone
        # notice row) to +40 (heading row, now inline with the notice, +
        # the row cap).
        self.assertLessEqual(widget.sizeHint().height(), _scale.px(8 * 24 + 40))
        # QScrollArea only recomputes its scrollbar range once its viewport
        # is actually shown/polished -- pump the queue after show() so the
        # offscreen platform delivers the pending layout/resize events.
        widget.show()
        self._app.processEvents()
        self._app.processEvents()
        # With 30 tracks and no warnings the scroll area must get its FULL
        # 8-row viewport, not just "something under the cap": an exact
        # equality catches sizeHint() under-reporting (e.g. forgetting the
        # heading row's reserved space), which squeezes the viewport below
        # 8 visible rows.
        self.assertEqual(widget._rows_scroll.height(), _scale.px(8 * 24))
        self.assertTrue(widget._rows_scroll.verticalScrollBar().maximum() > 0)

    def test_placeholder_and_error_states(self):
        widget = self._widget()
        widget.show_probing()
        self.assertIn("Reading tracks", widget._notice.text())
        self.assertEqual(self._boxes(widget), [])
        widget.show_error("boom")
        self.assertIn("boom", widget._notice.text())
        widget.show_no_actions()
        self.assertIn("No AutoMux actions", widget._notice.text())

    # ── Task 7: inline notice, fill mode, whitespace fix ─────────────────

    def test_notice_sits_on_the_heading_line(self):
        # spec §4: the notice is no longer its own bottom row -- it renders
        # inline, right of the "Tracks" heading, in the same header row.
        widget = self._widget()
        widget.show_no_actions()
        widget.show()
        self._app.processEvents()
        self._app.processEvents()
        self.assertIs(widget._notice.parent(), widget._heading_row)
        self.assertIs(widget._heading.parent(), widget._heading_row)
        self.assertLess(widget._notice.geometry().y(), widget._rows_scroll.geometry().y())

    def test_fill_mode_lifts_the_row_cap(self):
        from plex_renamer.gui_qt import _scale

        widget = self._widget()
        widget.set_fill_mode(True)
        self.assertEqual(widget._rows_scroll.maximumHeight(), 16777215)
        widget.set_fill_mode(False)
        self.assertEqual(widget._rows_scroll.maximumHeight(), _scale.px(8 * 24))

    def test_fill_mode_keeps_minimum_height_bounded_with_large_plan(self):
        # Review finding (Task 7): in fill mode sizeHint() may grow with
        # content (that is the point -- the movie host's layout hands the
        # widget the panel's free space), but minimumSizeHint() must NOT:
        # MediaWorkPanel sits directly in a non-collapsible QSplitter,
        # which floors pane sizes at minimumSizeHint(), so a 20+-track
        # plan would otherwise force an unshrinkable, oversized pane on a
        # short window. Rows are scrollable in every mode, so shrinking
        # below content height is always safe.
        from plex_renamer.gui_qt import _scale

        widget = self._widget()
        widget.set_fill_mode(True)
        widget.show_plan(self._plan_with_tracks(count=20))
        cap_plus_chrome = _scale.px(8 * 24 + 40)  # row cap + heading row slack
        self.assertLessEqual(
            widget.minimumSizeHint().height(),
            cap_plus_chrome,
            f"fill-mode minimumSizeHint {widget.minimumSizeHint().height()}px "
            f"scales with track count -- it must stay bounded at the 8-row "
            f"cap (+chrome) so the splitter pane can shrink",
        )
        # The preferred size still grows with content in fill mode -- the
        # bounded minimum must not accidentally re-cap it.
        self.assertGreater(widget.sizeHint().height(), cap_plus_chrome)

    def test_notice_elides_long_text_and_sets_full_tooltip(self):
        # Long notice text (e.g. a long mkvmerge error) must not blow out the
        # heading row's width -- it elides, with the FULL text available as
        # a tooltip, in every display state that sets notice text.
        widget = self._widget()
        # Resize the notice label itself (not just its container) to force
        # a narrow measuring width -- _ElidedNoticeLabel re-elides from its
        # own resizeEvent, and without a live layout pass a container resize
        # alone does not cascade down to an unshown child.
        widget._notice.resize(60, 20)
        long_error = (
            "a very long probe failure message that should not fit on the "
            "heading line at all, no matter how narrow the card gets"
        )
        widget.show_error(long_error)
        self.assertIn(long_error, widget._notice.toolTip())
        self.assertLess(len(widget._notice.text()), len(long_error))

        widget.show_probing()
        self.assertEqual(widget._notice.toolTip(), "Reading tracks…")

        widget.show_no_actions()
        self.assertEqual(widget._notice.toolTip(), "No AutoMux actions apply to this file.")

        plan = dict(PLAN)
        plan["warnings"] = [long_error]
        widget.show_plan(plan)
        self.assertIn(long_error, widget._notice.toolTip())

    def test_embedded_label_marks_forced_and_commentary(self):
        from plex_renamer.gui_qt.widgets._automux_tracks import (
            AutoMuxTracksWidget,
        )

        forced = AutoMuxTracksWidget._embedded_label(
            {
                "track_type": "subtitles",
                "language": "eng",
                "codec": "srt",
                "name": "Signs",
                "is_forced": True,
                "is_commentary": False,
            }
        )
        self.assertIn("forced", forced)
        commentary = AutoMuxTracksWidget._embedded_label(
            {
                "track_type": "audio",
                "language": "eng",
                "codec": "aac",
                "name": "Director Commentary",
                "is_forced": False,
                "is_commentary": True,
            }
        )
        self.assertIn("commentary", commentary)
        plain = AutoMuxTracksWidget._embedded_label(
            {
                "track_type": "audio",
                "language": "eng",
                "codec": "aac",
                "name": "",
                "is_forced": False,
                "is_commentary": False,
            }
        )
        self.assertNotIn("forced", plain)

    def test_show_plan_renders_conversion_row(self):
        widget = self._widget()
        plan = {
            "output_name": "X.mkv",
            "track_decisions": [],
            "subtitle_merges": [],
            "strip_track_names": False,
            "no_fear": False,
            "mkvmerge_path": "",
            "warnings": [],
            "container_conversion": True,
        }
        widget.show_plan(plan)
        self.assertIsNotNone(widget._conversion_label)
        self.assertIn("Convert container to MKV", widget._conversion_label.text())

        widget.show_plan({**plan, "container_conversion": False})
        self.assertIsNone(widget._conversion_label)
