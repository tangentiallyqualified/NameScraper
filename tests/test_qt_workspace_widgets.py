from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from conftest_qt import QtSmokeBase


class WorkspaceWidgetPrimitiveTests(QtSmokeBase):
    def test_roster_group_keeps_movie_duplicates_but_reviews_tv_duplicates(self):
        from plex_renamer.engine import ScanState
        from plex_renamer.gui_qt.widgets._media_helpers import roster_group

        duplicate_state = ScanState(
            folder=Path("C:/library/Duplicate"),
            media_info={"id": 101, "name": "Duplicate", "year": "2024"},
            duplicate_of="Duplicate (2024)",
            checked=False,
        )

        self.assertEqual(roster_group(duplicate_state, media_type="tv"), "review-match")
        self.assertEqual(roster_group(duplicate_state, media_type="movie"), "duplicate")

    def test_master_checkbox_toggles_like_binary_control(self):
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import MasterCheckBox

        widget = MasterCheckBox("Select All")
        widget.setCheckState(Qt.CheckState.PartiallyChecked)

        widget.nextCheckState()
        self.assertEqual(widget.checkState(), Qt.CheckState.Checked)

        widget.nextCheckState()
        self.assertEqual(widget.checkState(), Qt.CheckState.Unchecked)
        widget.close()

    def test_elided_label_sets_tooltip_only_when_elided(self):
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import ElidedLabel

        full_text = "A very long movie title that should be truncated"
        host = QWidget()
        host.resize(240, 60)
        label = ElidedLabel(full_text, parent=host)
        label.resize(60, 20)
        host.show()
        label.show()
        self._app.processEvents()

        self.assertTrue(label.toolTip())

        host.resize(800, 60)
        label.resize(label.fontMetrics().horizontalAdvance(full_text) + 20, 20)
        self._app.processEvents()

        self.assertEqual(label.toolTip(), "")
        host.close()

    def test_empty_state_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/empty_state.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("setFixedSize(360, 220)", source)
        self.assertNotIn("QSize(48, 48)", source)

    def test_scan_progress_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/scan_progress.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        for literal in (
            "setFixedWidth(480)",
            "setFixedHeight(8)",
            "setFixedWidth(56)",
            "setFixedHeight(1)",
            "setFixedWidth(16)",
            "setFixedWidth(100)",
        ):
            self.assertNotIn(literal, source)

    def test_scan_progress_resets_phase_local_progress_between_lifecycles(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.update_progress(
            lifecycle=ScanLifecycle.MATCHING,
            phase="Matching shows...",
            done=5,
            total=5,
            message="Matching shows... 5/5",
        )
        self.assertEqual(widget._progress_bar.value(), 100)

        widget.update_progress(
            lifecycle=ScanLifecycle.BUILDING_PREVIEWS,
            phase="Building episode previews...",
            done=0,
            total=3,
            message="Building episode previews... 0/3",
        )

        self.assertEqual(widget._progress_bar.value(), 0)
        self.assertEqual(widget._count_label.text(), "0/3")
        widget.close()

    def test_scan_progress_terminal_state_stops_animation(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="movie")
        widget.start()
        self.assertTrue(widget._animation_timer.isActive())

        widget.update_progress(
            lifecycle=ScanLifecycle.READY,
            phase="Movie scan complete",
            message="Movie scan complete",
        )

        self.assertFalse(widget._animation_timer.isActive())
        widget.close()

    def test_scan_progress_completes_prior_phases_when_lifecycle_skips_ahead(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="movie")
        widget.start()
        widget.update_progress(lifecycle=ScanLifecycle.PREPARING_REVIEW.value, phase="Preparing")
        self.assertEqual(widget._count_label.text(), "Working")
        # movie checklist: DISCOVERING, MATCHING, BUILDING_PREVIEWS, PREPARING_REVIEW
        self.assertEqual(widget._stepper._active_index, 3)
        self.assertEqual(widget._stepper._done, {0, 1, 2})
        widget.stop()

    def test_scan_progress_throttles_fast_text_updates_but_keeps_count_current(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.update_progress(
            lifecycle=ScanLifecycle.BUILDING_PREVIEWS,
            phase="Building episode previews...",
            done=1,
            total=5,
            current_item="Show A",
            message="Building episode previews... 1/5 - Show A",
        )
        widget.update_progress(
            lifecycle=ScanLifecycle.BUILDING_PREVIEWS,
            phase="Building episode previews...",
            done=2,
            total=5,
            current_item="Show B",
            message="Building episode previews... 2/5 - Show B",
        )

        self.assertEqual(widget._count_label.text(), "2/5")
        self.assertEqual(widget._item_label.text(), "Show A")
        widget.close()

    def test_scan_progress_single_secondary_line_elides_middle_with_tooltip(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.resize(700, 500)
        widget.start()
        long_item = "S01E01 - " + ("x" * 200) + ".mkv"
        widget.update_progress(
            lifecycle="matching", phase="Matching", done=1, total=10, current_item=long_item
        )
        self.assertEqual(widget._item_label.text(), long_item)     # ElidedLabel.text() returns full text
        self.assertEqual(widget._item_label.toolTip(), long_item)
        widget.stop()

    def test_scan_progress_filler_quip_rotates_and_item_update_resets(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.update_progress(lifecycle="matching", phase="Matching", current_item="a.mkv")
        self.assertEqual(widget._filler_timer.interval(), 4000)
        self.assertTrue(widget._filler_timer.isActive())
        widget._rotate_filler()
        first_quip = widget._item_label.text()
        self.assertNotEqual(first_quip, "a.mkv")
        widget._rotate_filler()
        self.assertNotEqual(widget._item_label.text(), first_quip)   # rotates through the list
        widget.update_progress(lifecycle="matching", phase="Matching", current_item="b.mkv")
        self.assertEqual(widget._item_label.text(), "b.mkv")         # honest item resets the line
        widget.stop()
        self.assertFalse(widget._filler_timer.isActive())

    def test_scan_progress_primary_line_always_shows_phase_not_quips(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.update_progress(lifecycle="matching", phase="Matching on TMDB", current_item="a.mkv")
        widget._rotate_filler()
        self.assertEqual(widget._phase_label.text(), "Matching on TMDB")
        widget.stop()

    def test_scan_progress_checklist_matches_media_type(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        tv_widget = ScanProgressWidget(media_type="tv")
        movie_widget = ScanProgressWidget(media_type="movie")
        self.assertEqual(len(tv_widget._stepper._labels), 5)
        self.assertEqual(len(movie_widget._stepper._labels), 4)

    def test_scan_progress_conveyor_advances_only_while_active(self):
        from plex_renamer.gui_qt.widgets.scan_progress import _ConveyorAnimation

        animation = _ConveyorAnimation()
        animation.resize(600, 200)
        animation.set_active(True)
        for _ in range(10):
            animation.advance()
        self.assertEqual(animation._tick, 10)
        animation.set_active(False)
        animation.advance()
        self.assertEqual(animation._tick, 10)   # inactive: no motion

    def test_workspace_widget_primitives_use_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        # No bare integer class constants for pixel sizes
        self.assertNotIn("_INDICATOR_SIZE = 18", source)
        self.assertNotIn("_SIZE = 20", source)
        # No bare literals on the MiniProgressBar
        self.assertNotIn("setFixedHeight(4)", source)
        self.assertNotIn("QSize(120, 4)", source)

    def test_media_workspace_lifecycle_and_ui_use_scale_helper(self):
        # GUI V4 roster cutover (Plan 2 Task 6): compact-mode icon sizing
        # moved from a hardcoded QSize(...) built in apply_settings() to
        # RosterModel/RosterDelegate.set_compact(). GUI V4 Plan 3 Task 5
        # (2-panel cutover) then removed the last _scale use from the ui
        # coordinator along with the deleted detail panel's minimum width, so
        # only the DPI-unaware literal negative assertions remain here.
        from pathlib import Path

        lifecycle = Path(
            "plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("QSize(32, 46)", lifecycle)
        self.assertNotIn("QSize(42, 60)", lifecycle)

        delegate = Path(
            "plex_renamer/gui_qt/widgets/_roster_delegate.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", delegate)

        ui = Path(
            "plex_renamer/gui_qt/widgets/_media_workspace_ui.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("setMinimumWidth(340)", ui)

    def test_match_picker_dialog_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/match_picker_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("resize(520, 520)", source)

    def test_paint_statics_render_without_error(self):
        from PySide6.QtCore import QRect, QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from plex_renamer.gui_qt import theme
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import (
            paint_check_indicator,
            paint_mini_progress,
        )

        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        for state in (Qt.CheckState.Unchecked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Checked):
            paint_check_indicator(painter, QRectF(2, 2, 20, 20), state)
        paint_mini_progress(painter, QRect(2, 40, 60, 4), value=55, color=theme.qcolor("success"))
        painter.end()
        self.assertFalse(image.isNull())

    def test_straggler_update_after_stop_does_not_restart_filler_timer(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.stop()
        widget.update_progress(
            lifecycle=ScanLifecycle.BUILDING_PREVIEWS,
            phase="straggler",
            current_item="Show Z",
            message="straggler",
        )
        self.assertFalse(widget._filler_timer.isActive())
        widget.close()


class EpisodeRowActionVocabularyTests(QtSmokeBase):
    """The expansion card's ``episode_row_actions`` inherits the exact action-id
    vocabulary the deleted preview panel exposed (consumed unchanged by
    ``handle_episode_row_action``)."""

    def test_matched_row_offers_assign_to_more(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import episode_row_actions

        class _Row:
            status = "Mapped"

        ids = [a for a, _label in episode_row_actions(_Row())]
        self.assertIn("assign_to_more", ids)
        self.assertIn("reassign", ids)

    def test_missing_file_row_only_offers_assign_file(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import episode_row_actions

        class _MissingRow:
            status = "Missing File"

        missing_ids = [a for a, _label in episode_row_actions(_MissingRow())]
        self.assertNotIn("assign_to_more", missing_ids)
        self.assertEqual(missing_ids, ["assign_file"])
