from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QPushButton, QWidget

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

    def test_folder_preview_row_preserves_full_target_tooltip(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import FolderPreviewRowWidget

        widget = FolderPreviewRowWidget(
            "Some Extremely Long Source Folder Name",
            "Some Extremely Long Target Folder Name",
        )

        self.assertEqual(widget._target.toolTip(), "Some Extremely Long Target Folder Name")
        widget.close()

    def test_episode_review_row_reserves_moderate_space_for_actions_and_review_pill(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        original_stylesheet = self._app.styleSheet()
        theme = Path("plex_renamer/gui_qt/resources/theme.qss").read_text(encoding="utf-8")
        self._app.setStyleSheet(theme)
        self.addCleanup(lambda: self._app.setStyleSheet(original_stylesheet))

        widget = EpisodeGuideRowWidget(
            title="S01E01 - Bartender",
            status="Review",
            original="[Kawaiika-Raws] Bartender 01 [BDRip 1920x1080 HEVC FLAC].mkv",
            target="Bartender (2006) - S01E01 - Bartender.mkv",
            confidence="50%",
            companions=["[Kawaiika-Raws] Bartender 01 [BDRip 1920x1080 HEVC FLAC].eng[BD].sup.mks"],
            actions=[("approve", "Approve"), ("reassign", "Reassign...")],
        )
        widget.resize(780, widget.sizeHint().height())
        widget.show()
        self._app.processEvents()

        buttons = [b for b in widget.findChildren(QPushButton) if b.isVisible()]
        button_bottom = max(b.geometry().bottom() for b in buttons)
        button_bottom_clearance = widget.contentsRect().bottom() - button_bottom

        self.assertGreaterEqual(widget.sizeHint().height(), 96)
        self.assertGreaterEqual(button_bottom_clearance, 8)
        self.assertLessEqual(button_bottom_clearance, 10)
        self.assertGreaterEqual(
            widget._status.minimumWidth(),
            widget._status.fontMetrics().horizontalAdvance("Review") + 16,
        )
        widget.close()

    def test_episode_rows_without_actions_do_not_reserve_action_space(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        original_stylesheet = self._app.styleSheet()
        theme = Path("plex_renamer/gui_qt/resources/theme.qss").read_text(encoding="utf-8")
        self._app.setStyleSheet(theme)
        self.addCleanup(lambda: self._app.setStyleSheet(original_stylesheet))

        compact = EpisodeGuideRowWidget(
            title="S01E01 - Pilot",
            status="Mapped",
            original="Pilot.mkv",
        )
        detailed = EpisodeGuideRowWidget(
            title="S01E02 - Heart of the Menu",
            status="Mapped",
            original="[Kawaiika-Raws] Bartender 02 [BDRip 1920x1080 HEVC FLAC].mkv",
            target="Bartender (2006) - S01E02 - Heart of the Menu.mkv",
            confidence="100%",
            companions=["[Kawaiika-Raws] Bartender 02 [BDRip 1920x1080 HEVC FLAC].eng[BD].sup.mks"],
        )
        review = EpisodeGuideRowWidget(
            title="S01E03 - Glass of Regret",
            status="Review",
            original="[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].mkv",
            target="Bartender (2006) - S01E03 - Glass of Regret.mkv",
            confidence="50%",
            companions=["[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].eng[BD].sup.mks"],
            actions=[("approve", "Approve"), ("reassign", "Reassign...")],
        )

        self.assertLess(compact.sizeHint().height(), detailed.sizeHint().height())
        self.assertLess(detailed.sizeHint().height(), review.sizeHint().height())
        self.assertLessEqual(compact.sizeHint().height(), 76)
        self.assertLessEqual(detailed.sizeHint().height(), 96)

        compact.close()
        detailed.close()
        review.close()

    def test_episode_confidence_rows_show_percentage_to_right_of_meter(self):
        from plex_renamer.engine import PreviewItem
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget, PreviewRowWidget

        preview = PreviewItem(
            original=Path("C:/library/tv/Bartender/Season 01/Bartender.01.mkv"),
            new_name="Bartender (2006) - S01E01 - Bartender.mkv",
            target_dir=Path("C:/library/tv/Bartender (2006)/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
            episode_confidence=0.8,
        )
        preview_row = PreviewRowWidget(
            preview,
            compact=False,
            show_confidence=True,
            show_companions=False,
            checked=False,
            checkable=True,
        )
        guide_row = EpisodeGuideRowWidget(
            title="S01E01 - Bartender",
            status="Mapped",
            original="Bartender.01.mkv",
            target="Bartender (2006) - S01E01 - Bartender.mkv",
            confidence="80%",
        )

        for row in (preview_row, guide_row):
            row.resize(640, row.sizeHint().height())
            row.show()
        self._app.processEvents()

        try:
            self.assertEqual(preview_row._confidence_percent.text(), "80%")
            self.assertEqual(guide_row._confidence_percent.text(), "80%")
            self.assertTrue(preview_row._confidence_percent.isVisible())
            self.assertTrue(guide_row._confidence_percent.isVisible())
            self.assertGreater(
                preview_row._confidence_percent.mapTo(preview_row, QPoint(0, 0)).x(),
                preview_row._confidence.mapTo(preview_row, QPoint(0, 0)).x(),
            )
            self.assertGreater(
                guide_row._confidence_percent.mapTo(guide_row, QPoint(0, 0)).x(),
                guide_row._confidence.mapTo(guide_row, QPoint(0, 0)).x(),
            )
        finally:
            preview_row.close()
            guide_row.close()

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
        widget.update_progress(
            lifecycle=ScanLifecycle.PREPARING_REVIEW,
            phase="Preparing review list...",
            message="Preparing review list...",
        )

        self.assertEqual(
            widget._phase_rows[ScanLifecycle.DISCOVERING].property("phaseState"),
            "done",
        )
        self.assertEqual(
            widget._phase_rows[ScanLifecycle.MATCHING].property("phaseState"),
            "done",
        )
        self.assertEqual(
            widget._phase_rows[ScanLifecycle.BUILDING_PREVIEWS].property("phaseState"),
            "done",
        )
        self.assertEqual(
            widget._phase_rows[ScanLifecycle.PREPARING_REVIEW].property("phaseState"),
            "active",
        )
        self.assertEqual(widget._progress_bar.value(), 0)
        self.assertEqual(widget._count_label.text(), "Working")
        widget.close()

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
        self.assertEqual(widget._current_label.text(), "Current: Show A")
        widget.close()

    def test_scan_progress_checklist_matches_media_type(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        tv_widget = ScanProgressWidget(media_type="tv")
        movie_widget = ScanProgressWidget(media_type="movie")

        self.assertIn(ScanLifecycle.RECONCILING, tv_widget._phase_rows)
        self.assertNotIn(ScanLifecycle.RECONCILING, movie_widget._phase_rows)
        self.assertIn(ScanLifecycle.PREPARING_REVIEW, movie_widget._phase_rows)

        tv_widget.close()
        movie_widget.close()

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

    def test_workspace_widgets_use_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/_workspace_widgets.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        for literal in (
            "QSize(34, 50)",
            "QSize(48, 70)",
            "setFixedWidth(92 if compact else 110)",
            "setFixedWidth(96)",
            "setFixedHeight(24)",
            "_COMPACT_ROW_MIN_HEIGHT = 72",
        ):
            self.assertNotIn(literal, source)
        self.assertIn("row_height(rows=1, padding=10)", source)

    def test_media_workspace_lifecycle_and_ui_use_scale_helper(self):
        from pathlib import Path

        lifecycle = Path(
            "plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", lifecycle)
        self.assertNotIn("QSize(32, 46)", lifecycle)
        self.assertNotIn("QSize(42, 60)", lifecycle)

        ui = Path(
            "plex_renamer/gui_qt/widgets/_media_workspace_ui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", ui)
        self.assertNotIn("setMinimumWidth(340)", ui)

    def test_match_picker_dialog_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/match_picker_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("resize(520, 520)", source)

    def test_media_workspace_preview_sticky_header_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/_media_workspace_preview.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("setFixedHeight(30)", source)


class MoviePreviewRowCheckboxTests(QtSmokeBase):
    def _make_movie_preview(self):
        from pathlib import Path
        from plex_renamer.constants import MediaType
        from plex_renamer.engine import PreviewItem
        return PreviewItem(
            original=Path("/movies/Inception.mkv"),
            new_name="Inception (2010).mkv",
            target_dir=Path("/movies/Inception (2010)"),
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=27205,
            media_name="Inception",
        )

    def test_movie_mode_hides_checkbox(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import PreviewRowWidget
        widget = PreviewRowWidget(
            self._make_movie_preview(),
            compact=False,
            show_confidence=True,
            show_companions=False,
            checked=False,
            checkable=True,
            media_type="movie",
        )
        self.assertFalse(widget._check.isVisibleTo(widget))

    def test_tv_mode_shows_checkbox_when_actionable(self):
        from pathlib import Path
        from plex_renamer.constants import MediaType
        from plex_renamer.engine import PreviewItem
        from plex_renamer.gui_qt.widgets._workspace_widgets import PreviewRowWidget
        tv_preview = PreviewItem(
            original=Path("/tv/show/s01e01.mkv"),
            new_name="Show - S01E01.mkv",
            target_dir=Path("/tv/show/Show (2020)/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
            media_type=MediaType.TV,
        )
        widget = PreviewRowWidget(
            tv_preview,
            compact=False,
            show_confidence=True,
            show_companions=False,
            checked=False,
            checkable=True,
            media_type="tv",
        )
        self.assertTrue(widget._check.isVisibleTo(widget))


class EpisodeGuideRowActionsTests(QtSmokeBase):
    def test_actions_menu_button_present(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        widget = EpisodeGuideRowWidget(
            title="S01E01 - Pilot",
            status="Mapped",
            actions=[("reassign", "Reassign..."), ("unassign", "Unassign")],
        )
        self.assertIsNotNone(widget.actions_button())
        labels = [action.text() for action in widget.actions_menu().actions()]
        self.assertEqual(labels, ["Reassign...", "Unassign"])
        widget.close()

    def test_action_signal_carries_action_id(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        widget = EpisodeGuideRowWidget(
            title="S01E01 - Pilot",
            status="Mapped",
            actions=[("unassign", "Unassign")],
        )
        fired: list[str] = []
        widget.action_requested.connect(fired.append)
        widget.actions_menu().actions()[0].trigger()
        self.assertEqual(fired, ["unassign"])
        widget.close()

    def test_no_actions_hides_button(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        widget = EpisodeGuideRowWidget(
            title="S01E02 - Missing",
            status="Missing File",
            actions=[],
        )
        self.assertIsNone(widget.actions_button())
        widget.close()

    def test_approve_quick_button_only_for_review(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        review = EpisodeGuideRowWidget(
            title="S01E01",
            status="Review",
            actions=[("approve", "Approve"), ("reassign", "Reassign...")],
        )
        mapped = EpisodeGuideRowWidget(
            title="S01E01",
            status="Mapped",
            actions=[("reassign", "Reassign...")],
        )
        self.assertTrue(review.approve_button().isVisibleTo(review))
        self.assertFalse(mapped.approve_button().isVisibleTo(mapped))
        review.close()
        mapped.close()
