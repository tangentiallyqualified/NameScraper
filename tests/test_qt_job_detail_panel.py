from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobStatus
from plex_renamer.engine import CompanionFile, PreviewItem, RenameResult, ScanState
from plex_renamer.job_store import JobStore

from conftest_qt import QtSmokeBase


class QtJobDetailPanelTests(QtSmokeBase):
    def test_job_detail_panel_uses_persisted_job_poster_path_before_tmdb_lookup(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob

        tmdb = MagicMock()
        tmdb.fetch_image = MagicMock(return_value=None)
        tmdb.fetch_poster = MagicMock(side_effect=AssertionError("fetch_poster should not be used when poster_path is persisted"))

        panel = JobDetailPanel(tmdb_provider=lambda: tmdb)
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            tmdb_id=123,
            media_name="Example Show",
            poster_path="/poster.jpg",
        )

        panel.set_job(job)
        self._app.processEvents()
        QTest.qWait(10)
        self._app.processEvents()

        tmdb.fetch_image.assert_called_once()
        call_args = tmdb.fetch_image.call_args
        self.assertEqual(call_args.args, ("/poster.jpg",))
        self.assertGreaterEqual(call_args.kwargs["target_width"], 200)
        panel.close()

    def test_job_detail_panel_backfills_poster_path_from_cached_tmdb_metadata(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob

        persisted: list[tuple[str, str | None]] = []
        tmdb = MagicMock()
        tmdb.get_cached_poster_path = MagicMock(return_value="/poster.jpg")
        tmdb.fetch_image = MagicMock(return_value=None)
        tmdb.fetch_poster = MagicMock(side_effect=AssertionError("fetch_poster should not be needed when cached metadata has poster_path"))

        panel = JobDetailPanel(
            tmdb_provider=lambda: tmdb,
            persist_poster_path=lambda job_id, poster_path: persisted.append((job_id, poster_path)),
        )
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            tmdb_id=123,
            media_name="Example Show",
            poster_path=None,
        )

        panel.set_job(job)
        self._app.processEvents()
        QTest.qWait(10)
        self._app.processEvents()

        tmdb.get_cached_poster_path.assert_called_once_with(123, media_type=job.media_type)
        tmdb.fetch_image.assert_called_once()
        call_args = tmdb.fetch_image.call_args
        self.assertEqual(call_args.args, ("/poster.jpg",))
        self.assertGreaterEqual(call_args.kwargs["target_width"], 200)
        self.assertEqual(job.poster_path, "/poster.jpg")
        self.assertEqual(persisted, [(job.job_id, "/poster.jpg")])
        panel.close()

    def test_job_detail_panel_shows_folder_plan_and_preview_lines(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp)
            (library_root / "Bleach").mkdir()
            (library_root / "Bleach (2004)").mkdir()

            panel = JobDetailPanel()
            panel.set_history_mode(True)
            job = RenameJob(
                library_root=str(library_root),
                source_folder="Bleach",
                media_name="Bleach",
                show_folder_rename="Bleach (2004)",
                rename_ops=[
                    RenameOp(
                        original_relative="Bleach/Disc 01/Bleach - 001.mkv",
                        new_name="Bleach (2004) - S01E01.mkv",
                        target_dir_relative="Bleach/Season 01",
                        status="OK",
                        selected=True,
                    )
                ],
            )

            panel.set_job(job)

            self.assertEqual(panel._preview_tree.topLevelItemCount(), 2)
            folder_item = panel._preview_tree.topLevelItem(0)
            folder_row = folder_item.child(0)
            rename_item = panel._preview_tree.topLevelItem(1)
            folder_widget = panel._preview_tree.itemWidget(folder_row, 0)
            rename_widget = panel._preview_tree.itemWidget(rename_item, 0)
            self.assertEqual(folder_item.text(0), "▾ Folder Rename")
            self.assertTrue(folder_item.isExpanded())
            self.assertEqual(folder_item.toolTip(0), "")
            self.assertEqual(folder_widget._before_key.text(), "Source")
            self.assertEqual(folder_widget._after_key.text(), "Target")
            self.assertEqual(folder_widget._before.text(), "Bleach")
            self.assertEqual(folder_widget._after.text(), "Bleach (2004)")
            self.assertEqual(rename_item.text(0), "")
            self.assertEqual(rename_widget._before.text(), "Bleach - 001.mkv")
            self.assertEqual(rename_widget._after.text(), "Bleach (2004) - S01E01.mkv")
            self.assertTrue(panel._open_source_btn.isEnabled())
            self.assertTrue(panel._open_target_btn.isEnabled())
            panel.close()

    def test_job_detail_panel_shows_movie_folder_only_preview_with_source_target_labels(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob

        panel = JobDetailPanel()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Alien",
            media_type="movie",
            media_name="Alien",
            show_folder_rename="Alien (1979)",
            rename_ops=[],
        )

        panel.set_job(job)

        self.assertEqual(panel._preview_tree.topLevelItemCount(), 1)
        folder_item = panel._preview_tree.topLevelItem(0)
        folder_row = folder_item.child(0)
        folder_widget = panel._preview_tree.itemWidget(folder_row, 0)
        self.assertEqual(folder_item.text(0), "▾ Folder Rename")
        self.assertEqual(folder_item.toolTip(0), "")
        self.assertTrue(folder_item.isExpanded())
        self.assertEqual(folder_widget._before_key.text(), "Source")
        self.assertEqual(folder_widget._after_key.text(), "Target")
        self.assertEqual(folder_widget._before.text(), "Alien")
        self.assertEqual(folder_widget._after.text(), "Alien (1979)")
        panel.close()

    def test_job_detail_panel_groups_movie_file_renames_under_file_rename_header(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Alien",
            media_type="movie",
            media_name="Alien",
            show_folder_rename="Alien (1979)",
            rename_ops=[
                RenameOp(
                    original_relative="Alien/Alien.mkv",
                    new_name="Alien (1979).mkv",
                    target_dir_relative="Alien (1979)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        self.assertEqual(panel._preview_tree.topLevelItemCount(), 2)
        file_header = panel._preview_tree.topLevelItem(1)
        file_row = file_header.child(0)
        file_widget = panel._preview_tree.itemWidget(file_row, 0)
        self.assertEqual(file_header.text(0), "▾ File Rename")
        self.assertEqual(file_header.toolTip(0), "")
        self.assertTrue(file_header.isExpanded())
        self.assertEqual(file_widget._before.text(), "Alien.mkv")
        self.assertEqual(file_widget._after.text(), "Alien (1979).mkv")
        panel.close()

    def test_job_detail_panel_shows_placeholder_when_no_job_selected(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel

        panel = JobDetailPanel()

        self.assertIs(panel._stack.currentWidget(), panel._empty_page)
        self.assertEqual(panel._empty_title.text(), "No Job Selected!")
        self.assertIn("Queued jobs will appear here.", panel._empty_message.text())

        panel.set_history_mode(True)

        self.assertIn("History entries will appear here.", panel._empty_message.text())
        panel.close()

    def test_job_detail_panel_hides_target_button_in_queue_mode(self):
        from PySide6.QtWidgets import QSizePolicy
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob

        panel = JobDetailPanel()
        panel.set_history_mode(False)
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            rename_ops=[],
        )

        panel.set_job(job)

        self.assertEqual(panel._open_source_btn.text(), "Open Source")
        self.assertEqual(panel._open_target_btn.text(), "Open Target")
        self.assertFalse(panel._open_source_btn.isHidden())
        self.assertFalse(panel._open_target_btn.isHidden())
        self.assertFalse(panel._open_target_btn.isEnabled())
        self.assertEqual(
            panel._open_source_btn.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Expanding,
        )
        self.assertEqual(
            panel._open_target_btn.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Expanding,
        )
        panel.close()

    def test_job_detail_panel_populates_compact_facts_card_without_duplicate_summary(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.set_history_mode(True)
        job = RenameJob(
            library_root="C:/library",
            source_folder="Alien",
            media_type="movie",
            media_name="Alien",
            show_folder_rename="Alien (1979)",
            rename_ops=[
                RenameOp(
                    original_relative="Alien/Alien.mkv",
                    new_name="Alien (1979).mkv",
                    target_dir_relative="Alien (1979)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        self.assertEqual(panel._fact_values["media"].text(), "Movie")
        self.assertEqual(panel._fact_values["action"].text(), "Rename")
        self.assertEqual(panel._fact_values["files"].text(), "1 selected")
        self.assertEqual(panel._fact_values["companions"].text(), "None")
        self.assertEqual(set(panel._fact_values), {"media", "action", "files", "companions"})
        self.assertFalse(panel._summary.isVisible())
        self.assertTrue(panel._meta.text().startswith("Updated "))
        panel.close()

    def test_job_detail_panel_uses_local_non_hover_poster_style(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel

        panel = JobDetailPanel()

        self.assertEqual(panel._poster.property("cssClass"), "job-poster-card")
        panel.close()

    def test_job_detail_panel_recovers_movie_folder_source_name_when_source_folder_is_dot(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.set_history_mode(True)
        job = RenameJob(
            library_root="C:/library",
            source_folder=".",
            media_type="movie",
            media_name="Alien",
            status=JobStatus.COMPLETED,
            show_folder_rename="Alien (1979)",
            rename_ops=[
                RenameOp(
                    original_relative="Alien/Alien.mkv",
                    new_name="Alien (1979).mkv",
                    target_dir_relative="Alien (1979)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        folder_item = panel._preview_tree.topLevelItem(0)
        folder_row = folder_item.child(0)
        folder_widget = panel._preview_tree.itemWidget(folder_row, 0)
        self.assertEqual(folder_item.text(0), "▾ Folder Rename")
        self.assertEqual(folder_widget._before_key.text(), "Source")
        self.assertEqual(folder_widget._after_key.text(), "Target")
        self.assertEqual(folder_widget._before.text(), "Alien")
        self.assertEqual(folder_widget._after.text(), "Alien (1979)")
        panel.close()

    def test_job_detail_panel_inferrs_movie_history_folder_preview_without_show_folder_rename(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.set_history_mode(True)
        job = RenameJob(
            library_root="C:/library",
            source_folder=".",
            media_type="movie",
            media_name="Alien",
            status=JobStatus.COMPLETED,
            show_folder_rename=None,
            rename_ops=[
                RenameOp(
                    original_relative="Alien/Alien.mkv",
                    new_name="Alien (1979).mkv",
                    target_dir_relative="Alien (1979)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        self.assertEqual(panel._preview_tree.topLevelItemCount(), 2)
        folder_item = panel._preview_tree.topLevelItem(0)
        folder_row = folder_item.child(0)
        folder_widget = panel._preview_tree.itemWidget(folder_row, 0)
        self.assertEqual(folder_item.text(0), "▾ Folder Rename")
        self.assertEqual(folder_widget._before_key.text(), "Source")
        self.assertEqual(folder_widget._after_key.text(), "Target")
        self.assertEqual(folder_widget._before.text(), "Alien")
        self.assertEqual(folder_widget._after.text(), "Alien (1979)")
        panel.close()

    def test_job_detail_panel_inferrs_movie_history_folder_preview_from_library_root_files(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.set_history_mode(True)
        job = RenameJob(
            library_root="C:/library/Movies",
            source_folder=".",
            media_type="movie",
            media_name="Legend of the Galactic Heroes: Overture to a New War (1993)",
            status=JobStatus.COMPLETED,
            show_folder_rename=None,
            rename_ops=[
                RenameOp(
                    original_relative="Legend of the Galactic Heroes - Overture to a New War (1993) (BD 1080p HEVC FLAC).mkv",
                    new_name="Legend of the Galactic Heroes - Overture to a New War (1993).mkv",
                    target_dir_relative="Legend of the Galactic Heroes - Overture to a New War (1993)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        self.assertEqual(panel._preview_tree.topLevelItemCount(), 2)
        folder_item = panel._preview_tree.topLevelItem(0)
        folder_row = folder_item.child(0)
        folder_widget = panel._preview_tree.itemWidget(folder_row, 0)
        self.assertEqual(folder_item.text(0), "▾ Folder Rename")
        self.assertEqual(folder_widget._before_key.text(), "Source")
        self.assertEqual(folder_widget._after_key.text(), "Target")
        self.assertEqual(folder_widget._before.text(), "Movies")
        self.assertEqual(folder_widget._after.text(), "Legend of the Galactic Heroes - Overture to a New War (1993)")
        panel.close()

    def test_job_detail_panel_preview_rows_use_compact_labeled_fields(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.resize(720, 640)
        long_original = "Legend of the Galactic Heroes - Overture to a New War [Extremely Long Source Name].mkv"
        long_new = "Legend of the Galactic Heroes - Overture to a New War (1993) - Director's Cut Restoration Edition.mkv"
        job = RenameJob(
            library_root="C:/library",
            source_folder="LOGH",
            media_name="Legend of the Galactic Heroes - Overture to a New War (1993)",
            rename_ops=[
                RenameOp(
                    original_relative=f"LOGH/{long_original}",
                    new_name=long_new,
                    target_dir_relative="LOGH",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        item = panel._preview_tree.topLevelItem(0)
        widget = panel._preview_tree.itemWidget(item, 0)
        self.assertEqual(item.text(0), "")
        self.assertEqual(widget._after_key.text(), "New")
        self.assertEqual(widget._before_key.text(), "Original")
        self.assertEqual(widget._before.text(), long_original)
        self.assertEqual(widget._after.text(), long_new)
        self.assertFalse(widget._before.wordWrap())
        self.assertFalse(widget._after.wordWrap())
        expected_tooltip = f"New: {long_new}\nOriginal: {long_original}"
        self.assertEqual(widget.toolTip(), expected_tooltip)
        self.assertEqual(widget._before.toolTip(), expected_tooltip)
        self.assertEqual(widget._after.toolTip(), expected_tooltip)
        panel.close()

    def test_job_detail_panel_short_preview_rows_do_not_show_tooltips(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.resize(900, 640)
        job = RenameJob(
            library_root="C:/library",
            source_folder="Alien",
            media_name="Alien",
            rename_ops=[
                RenameOp(
                    original_relative="Alien/Alien.mkv",
                    new_name="Alien (1979).mkv",
                    target_dir_relative="Alien",
                    status="OK",
                    selected=True,
                )
            ],
        )

        panel.set_job(job)

        item = panel._preview_tree.topLevelItem(0)
        widget = panel._preview_tree.itemWidget(item, 0)
        self.assertEqual(widget.toolTip(), "")
        self.assertEqual(widget._before.toolTip(), "")
        self.assertEqual(widget._after.toolTip(), "")
        panel.close()

    def test_job_detail_panel_starts_season_groups_collapsed(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Bleach",
            media_name="Bleach",
            media_type="tv",
            rename_ops=[
                RenameOp(
                    original_relative="Bleach/Bleach - 001.mkv",
                    new_name="Bleach - S01E01.mkv",
                    target_dir_relative="Bleach/Season 01",
                    status="OK",
                    selected=True,
                    season=1,
                ),
                RenameOp(
                    original_relative="Bleach/Bleach - 002.mkv",
                    new_name="Bleach - S01E02.mkv",
                    target_dir_relative="Bleach/Season 01",
                    status="OK",
                    selected=True,
                    season=1,
                ),
            ],
        )

        panel.set_job(job)

        self.assertFalse(panel._preview_tree.rootIsDecorated())
        season_header = panel._preview_tree.topLevelItem(0)
        self.assertEqual(season_header.text(0), "▸ Season 01 (2 files)")
        self.assertEqual(season_header.toolTip(0), "")
        self.assertFalse(season_header.isExpanded())
        panel.close()

    def test_job_detail_panel_preview_headers_toggle_on_single_click(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Bleach",
            media_name="Bleach",
            media_type="tv",
            rename_ops=[
                RenameOp(
                    original_relative="Bleach/Bleach - 001.mkv",
                    new_name="Bleach - S01E01.mkv",
                    target_dir_relative="Bleach/Season 01",
                    status="OK",
                    selected=True,
                    season=1,
                )
            ],
        )

        panel.set_job(job)

        season_header = panel._preview_tree.topLevelItem(0)
        self.assertFalse(season_header.isExpanded())
        panel._on_preview_item_clicked(season_header, 0)
        self.assertTrue(season_header.isExpanded())
        self.assertEqual(season_header.text(0), "▾ Season 01 (1 files)")
        panel._on_preview_item_clicked(season_header, 0)
        self.assertFalse(season_header.isExpanded())
        self.assertEqual(season_header.text(0), "▸ Season 01 (1 files)")
        panel.close()

    def test_job_detail_panel_open_target_folder_uses_existing_parent(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp)
            (library_root / "Bleach").mkdir()
            target_parent = library_root / "Bleach (2004)"
            target_parent.mkdir()

            panel = JobDetailPanel()
            job = RenameJob(
                library_root=str(library_root),
                source_folder="Bleach",
                media_name="Bleach",
                show_folder_rename="Bleach (2004)",
                rename_ops=[
                    RenameOp(
                        original_relative="Bleach/Disc 01/Bleach - 001.mkv",
                        new_name="Bleach (2004) - S01E01.mkv",
                        target_dir_relative="Bleach/Season 01",
                        status="OK",
                        selected=True,
                    )
                ],
            )

            panel.set_job(job)

            with patch(
                "plex_renamer.gui_qt.widgets.job_detail_panel.QDesktopServices.openUrl",
                return_value=True,
            ) as open_mock:
                self.assertTrue(panel.open_target_folder())

            self.assertEqual(open_mock.call_count, 1)
            self.assertEqual(
                Path(open_mock.call_args.args[0].toLocalFile()),
                target_parent,
            )
            panel.close()

