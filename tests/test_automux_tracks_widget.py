"""Tracks section widget: rendering, editing, safety floor, locking."""
from __future__ import annotations

from conftest_qt import QtSmokeBase

PLAN = {
    "output_name": "X.mkv",
    "track_decisions": [
        {"track_id": 0, "track_type": "video", "codec": "h264",
         "language": "und", "name": "", "keep": True,
         "make_default": True, "reason": "video"},
        {"track_id": 1, "track_type": "audio", "codec": "aac",
         "language": "eng", "name": "", "keep": True,
         "make_default": True, "reason": "retained"},
        {"track_id": 2, "track_type": "subtitles", "codec": "srt",
         "language": "fre", "name": "", "keep": False,
         "make_default": False, "reason": "not in retain list"},
    ],
    "subtitle_merges": [
        {"source_relative": "Show/a.eng.srt", "action": "merge",
         "language": "eng", "set_default": False},
    ],
    "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
    "warnings": [], "user_modified": False,
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
            {"track_id": i, "track_type": "audio", "codec": "aac",
             "language": "eng", "name": f"Track {i}", "keep": True,
             "make_default": i == 0, "reason": "retained"}
            for i in range(count)
        ]
        return {
            "output_name": "Many.mkv",
            "track_decisions": decisions,
            "subtitle_merges": [],
            "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
            "warnings": [], "user_modified": False,
        }

    def test_show_plan_renders_rows(self):
        widget = self._widget()
        widget.show_plan(PLAN)
        boxes = self._boxes(widget)
        self.assertEqual(len(boxes), 4)          # 3 embedded + 1 merge
        video_box = boxes[0]
        self.assertFalse(video_box.isEnabled())  # video is never editable
        self.assertFalse(boxes[2].isChecked())   # stripped sub unchecked
        self.assertTrue(boxes[3].isChecked())    # merge checked

    def test_edit_emits_user_modified_plan(self):
        widget = self._widget()
        widget.show_plan(PLAN)
        emitted = []
        widget.plan_edited.connect(emitted.append)
        self._boxes(widget)[3].setChecked(False)     # merge → rename
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
        self.assertTrue(audio_box.isChecked())       # snapped back
        self.assertEqual(emitted, [])                # no edit emitted

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
        self.assertLessEqual(widget.sizeHint().height(), _scale.px(8 * 24 + 80))
        # QScrollArea only recomputes its scrollbar range once its viewport
        # is actually shown/polished -- pump the queue after show() so the
        # offscreen platform delivers the pending layout/resize events.
        widget.show()
        self._app.processEvents()
        self._app.processEvents()
        # With 30 tracks and no warnings the scroll area must get its FULL
        # 8-row viewport, not just "something under the cap": an exact
        # equality catches sizeHint() under-reporting (e.g. forgetting the
        # always-present notice label's reserved space), which squeezes
        # the viewport below 8 visible rows.
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
