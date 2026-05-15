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

        self.assertEqual(roster_group(duplicate_state, media_type="tv"), "review")
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
        )
        widget.resize(780, widget.sizeHint().height())
        widget.show()
        self._app.processEvents()

        buttons = widget.findChildren(QPushButton)
        button_bottom = max(button.geometry().bottom() for button in buttons if button.isVisible())
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
