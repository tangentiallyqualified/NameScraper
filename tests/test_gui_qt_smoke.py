from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobStatus
from plex_renamer.engine import CompanionFile, PreviewItem, RenameResult, ScanState
from plex_renamer.job_store import JobStore


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class QtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._main_window_stack = ExitStack()
        self.addCleanup(self._main_window_stack.close)
        self._main_window_tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._main_window_tmp.cleanup)
        base = Path(self._main_window_tmp.name)
        isolated_settings = SettingsService(path=base / "settings.json")
        isolated_cache = PersistentCacheService(db_path=base / "cache.db")
        isolated_store = JobStore(db_path=base / "jobs.db")
        self.addCleanup(isolated_store.close)
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.SettingsService", return_value=isolated_settings)
        )
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.PersistentCacheService", return_value=isolated_cache)
        )
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.JobStore", return_value=isolated_store)
        )

    def _reset_main_window_queue(self, window) -> None:
        queued_ids = [job.job_id for job in window.queue_ctrl.get_queue()]
        if queued_ids:
            window.queue_ctrl.remove_jobs(queued_ids)
        if window.queue_ctrl.get_history():
            window.queue_ctrl.clear_history()
        window._on_queue_changed()
        self._app.processEvents()

    def _roster_widget_for_index(self, workspace, index: int):
        for row in range(workspace._roster_list.count()):
            item = workspace._roster_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == index:
                return workspace._roster_list.itemWidget(item)
        return None

    def _preview_widget_for_index(self, workspace, index: int):
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == index:
                return workspace._preview_list.itemWidget(item)
        return None

    def _preview_header_texts(self, workspace) -> list[str]:
        headers: list[str] = []
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            text = item.text().strip()
            if text:
                headers.append(text)
        return headers

    def _assert_roster_section_title(self, workspace, row: int, expected: str) -> None:
        text = workspace._roster_list.item(row).text().strip()
        normalized = text.removeprefix("▼").removeprefix("▶").strip()
        if " (" in normalized:
            normalized = normalized.split(" (", 1)[0]
        self.assertEqual(normalized, expected)

    def test_main_window_instantiates(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self.assertEqual(window.windowTitle(), "Plex Renamer")
        self.assertEqual(window.centralWidget().__class__.__name__, "QTabWidget")
        window.close()

    def test_transient_popup_filter_hides_tool_windows(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QWidget
        from plex_renamer.gui_qt.app import _SuppressTransientPopups

        popup_filter = _SuppressTransientPopups(self._app)
        widget = QWidget()
        widget.setWindowFlags(Qt.WindowType.Tool)
        widget.setWindowOpacity(1.0)

        popup_filter.eventFilter(widget, QEvent(QEvent.Type.Show))

        self.assertEqual(widget.windowOpacity(), 0.0)
        widget.close()

    def test_transient_popup_filter_keeps_real_menus_visible(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QMenu
        from plex_renamer.gui_qt.app import _SuppressTransientPopups

        popup_filter = _SuppressTransientPopups(self._app)
        menu = QMenu()
        menu.setWindowOpacity(1.0)

        popup_filter.eventFilter(menu, QEvent(QEvent.Type.Show))

        self.assertEqual(menu.windowOpacity(), 1.0)
        menu.close()

    def test_transient_popup_filter_allows_tooltip_events_and_windows(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QWidget
        from plex_renamer.gui_qt.app import _SuppressTransientPopups

        popup_filter = _SuppressTransientPopups(self._app)
        tooltip_window = QWidget()
        tooltip_window.setWindowFlags(Qt.WindowType.ToolTip)
        tooltip_window.setWindowOpacity(1.0)

        self.assertFalse(popup_filter.eventFilter(tooltip_window, QEvent(QEvent.Type.ToolTip)))
        popup_filter.eventFilter(tooltip_window, QEvent(QEvent.Type.Show))

        self.assertEqual(tooltip_window.windowOpacity(), 1.0)
        tooltip_window.close()

    def test_main_window_undo_reverts_latest_job_and_switches_to_history(self):
        from PySide6.QtWidgets import QMessageBox
        from plex_renamer.constants import JobStatus
        from plex_renamer.engine import RenameResult
        from plex_renamer.gui_qt.main_window import MainWindow
        from plex_renamer.job_store import RenameJob

        window = MainWindow()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            status=JobStatus.COMPLETED,
            undo_data={"renames": [{"old": "a", "new": "b"}]},
        )
        window.queue_ctrl.get_latest_revertible_job = MagicMock(return_value=job)
        window.queue_ctrl.revert_job = MagicMock(return_value=(True, []))
        window._history_tab.select_job = MagicMock()

        with patch(
            "plex_renamer.gui_qt.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_undo()

        window.queue_ctrl.revert_job.assert_called_once_with(job.job_id)
        window._history_tab.select_job.assert_called_once_with(job.job_id)
        self.assertEqual(window.centralWidget().currentIndex(), 3)
        window.close()

    def test_main_window_queue_events_create_toasts(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.engine import RenameResult
        from plex_renamer.gui_qt.main_window import MainWindow
        from plex_renamer.job_store import RenameJob

        window = MainWindow()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            status=JobStatus.RUNNING,
        )

        window._on_job_started(job)
        window._on_job_completed(job, RenameResult(renamed_count=12))
        self.assertEqual(window._toast_manager.toast_count(), 0)

        window._history_tab.select_job = MagicMock()
        window._on_job_failed(job, "permission denied")
        self.assertEqual(window._toast_manager.toast_count(), 1)

        window._show_history_job(job.job_id)
        window._history_tab.select_job.assert_called_once_with(job.job_id)
        self.assertEqual(window.centralWidget().currentIndex(), 3)

        window._on_queue_finished()
        self.assertGreaterEqual(window._toast_manager.toast_count(), 2)
        window.close()

    def test_main_window_batches_quick_success_toasts(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.engine import RenameResult
        from plex_renamer.gui_qt.main_window import MainWindow
        from plex_renamer.job_store import RenameJob

        window = MainWindow()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            status=JobStatus.RUNNING,
        )

        window._on_job_started(job)
        window._on_job_completed(job, RenameResult(renamed_count=12))
        window._on_job_completed(job, RenameResult(renamed_count=8))
        self.assertEqual(window._toast_manager.toast_count(), 0)

        QTest.qWait(450)

        self.assertEqual(window._toast_manager.toast_count(), 1)
        toast = window._toast_manager._layout.itemAt(0).widget()
        self.assertEqual(toast._title_label.text(), "2 jobs completed")
        self.assertIn("20 files renamed", toast._message_label.text())
        window.close()

    def test_main_window_tab_badges_show_counts_and_failure_pip(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        window._queue_tab.refresh = MagicMock()
        window._history_tab.refresh = MagicMock()
        window.queue_ctrl.count_by_status = MagicMock(
            return_value={
                "pending": 1,
                "running": 0,
                "failed": 1,
                "completed": 1,
                "cancelled": 0,
                "reverted": 0,
            }
        )
        window._refresh_job_views()

        self.assertEqual(window._tabs.tabText(2), "Queue")
        self.assertEqual(window._tabs.tabText(3), "History")
        self.assertEqual(window._queue_badge.count_text(), "1")
        self.assertTrue(window._queue_badge.failure_visible())
        self.assertEqual(window._history_badge.count_text(), "2")
        window.close()

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

        tmdb.fetch_image.assert_called_once_with("/poster.jpg", target_width=200)
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
        tmdb.fetch_image.assert_called_once_with("/poster.jpg", target_width=200)
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

    def test_media_detail_panel_caps_metadata_cache_and_can_clear_it(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        max_entries = panel._MAX_METADATA_CACHE_ENTRIES

        for index in range(max_entries + 5):
            panel._apply_payload({"title": f"Item {index}"}, None, f"token-{index}")

        self.assertEqual(len(panel._metadata_cache), max_entries)
        self.assertNotIn("token-0", panel._metadata_cache)
        self.assertIn(f"token-{max_entries + 4}", panel._metadata_cache)

        panel.clear_metadata_cache()

        self.assertEqual(len(panel._metadata_cache), 0)
        self.assertEqual(len(panel._loading_tokens), 0)
        panel.close()

    def test_media_detail_panel_uses_episode_still_and_threshold_match_text(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            settings.auto_accept_threshold = 0.6
            tmdb = MagicMock()
            tmdb.get_tv_details.return_value = {"status": "Returning Series"}
            tmdb.fetch_poster.return_value = None

            preview = PreviewItem(
                original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
                new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                season=1,
                episodes=[1],
                status="REVIEW",
            )
            state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 102, "name": "Review Show", "year": "2024"},
                preview_items=[preview],
                scanner=type(
                    "Scanner",
                    (),
                    {
                        "episode_meta": {
                            (1, 1): {
                                "still_path": "/episode-still.jpg",
                                "overview": "Episode overview",
                                "air_date": "2024-01-01",
                                "directors": [],
                                "writers": [],
                                "guest_stars": [],
                            }
                        }
                    },
                )(),
                scanned=True,
                confidence=0.42,
            )

            panel = MediaDetailPanel(tmdb_provider=lambda: tmdb, settings_service=settings)
            payload, _image = panel._build_payload(tmdb, state, preview, "", "", 500)

            tmdb.fetch_poster.assert_called_once_with(
                102,
                media_type="tv",
                target_width=500,
            )
            self.assertEqual(payload["artwork_mode"], "poster")
            self.assertIn(("Confidence", "42%"), payload["rows"])
            self.assertIn(("Air Date", "2024-01-01"), payload["rows"])

            panel._current_token = "token"
            panel._apply_payload(payload, None, "token")
            self.assertEqual(panel._artwork_mode, "poster")
            self.assertEqual(panel._poster.height(), 222)
            panel.close()

    def test_media_detail_panel_uses_series_poster_placeholder_for_episode_selection_without_tmdb(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        preview = PreviewItem(
            original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
            new_name="Review Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Review.Show.2024"),
            media_info={"id": 102, "name": "Review Show", "year": "2024"},
            preview_items=[preview],
            scanned=True,
            confidence=0.42,
        )

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        panel.set_selection(state, preview=preview)

        self.assertEqual(panel._artwork_mode, "poster")
        self.assertEqual(panel._poster.height(), 222)
        self.assertIsNotNone(panel._poster.pixmap())
        self.assertEqual(panel._poster.text(), "")
        panel.close()

    def test_media_detail_panel_places_facts_card_in_summary_column(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        body_layout = panel._body.layout()
        summary_row = body_layout.itemAt(2).layout()
        summary_body = summary_row.itemAt(1).layout()

        self.assertGreater(body_layout.contentsMargins().left(), 0)
        self.assertIs(body_layout.itemAt(0).widget(), panel._title)
        self.assertIs(body_layout.itemAt(1).widget(), panel._subtitle)
        self.assertIsNotNone(summary_row)
        self.assertIs(summary_body.itemAt(0).widget(), panel._facts_card)
        self.assertEqual(panel._facts_card.height(), panel._poster.height())

        panel.close()

    def test_media_detail_panel_omits_movie_queue_row(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        state = ScanState(
            folder=Path("C:/library/movies/Arrival.2016"),
            media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                    new_name="Arrival (2016).mkv",
                    target_dir=Path("C:/library/movies/Arrival (2016)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=22,
                    media_name="Arrival",
                )
            ],
            scanned=True,
            confidence=0.91,
        )

        rows = panel._fallback_rows(state, state.preview_items[0], "Already queued", "Folder rename plan: Arrival.2016 -> Arrival (2016)")

        self.assertNotIn(("Queue", "Already queued"), rows)
        self.assertNotIn(("Folder", "Folder rename plan: Arrival.2016 -> Arrival (2016)"), rows)
        self.assertIn(("Confidence", "91%"), rows)

        panel.close()

    def test_media_detail_panel_facts_values_add_wrap_padding(self):
        from PySide6.QtWidgets import QLabel
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        _key_label, value_label = panel._meta_rows[0]
        text = "Science Fiction, Adventure, Mystery, Thriller"
        value_label.setText(text)

        base_label = QLabel("")
        base_label.setFont(value_label.font())
        base_label.setWordWrap(True)
        base_label.setMargin(value_label.margin())
        base_label.setText(text)

        self.assertGreater(value_label.heightForWidth(120), base_label.heightForWidth(120))

        panel.close()

    def test_media_detail_panel_long_title_does_not_widen_panel_minimum(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        short_payload = {
            "title": "Arrival (2016)",
            "subtitle": "Movie",
            "overview": "First contact changes everything.",
            "extra": "",
            "rows": [("Confidence", "97%")],
            "artwork_mode": "poster",
        }
        long_payload = {
            **short_payload,
            "title": "Indiana Jones and the Kingdom of the Crystal Skull (2008)",
        }

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        panel.resize(520, 640)
        panel.show()
        self._app.processEvents()

        panel._current_token = "short"
        panel._apply_payload(short_payload, None, "short")
        self._app.processEvents()
        baseline_width = panel.sizeHint().width()

        panel._current_token = "long"
        panel._apply_payload(long_payload, None, "long")
        self._app.processEvents()

        self.assertLessEqual(panel.sizeHint().width(), baseline_width)
        self.assertLessEqual(panel.minimumSizeHint().width(), 520)
        self.assertEqual(panel._body.width(), panel._scroll.viewport().width())
        self.assertLessEqual(panel._title.geometry().right(), panel._body.contentsRect().right())
        self.assertGreater(panel._title.height(), panel._title.fontMetrics().lineSpacing())

        panel.close()

    def test_settings_tab_async_api_key_test_updates_ui_via_bridge(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab()
        tab._api_key_input.setText("test-key")

        with patch("requests.get", return_value=MagicMock(ok=True, status_code=200)) as get_mock:
            tab._on_test_key()
            for _ in range(20):
                self._app.processEvents()
                if get_mock.call_count:
                    break
                QTest.qWait(10)
            self._app.processEvents()

        get_mock.assert_called_once()
        self.assertTrue(tab._test_key_btn.isEnabled())
        self.assertEqual(tab._key_status.text(), "TMDB connection successful.")
        self.assertEqual(tab._clear_cache_btn.text(), "Clear TMDB Cache")
        self.assertFalse(tab._clear_all_btn.isVisible())
        self.assertFalse(tab._advanced_group.isVisible())
        tab.close()

    def test_media_workspace_queue_buttons_use_distinct_labels(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def add_tv_batch(self, states, root, gating):
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=True,
            confidence=1.0,
        )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=_FakeQueueController(),
                settings_service=settings,
            )
            workspace.resize(1200, 700)
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
            self.assertEqual(workspace._roster_queue_btn.text(), "Queue 1 Checked")
            roster_top = workspace._roster_queue_btn.mapTo(workspace, QPoint(0, 0)).y()
            preview_top = workspace._queue_inline_btn.mapTo(workspace, QPoint(0, 0)).y()
            self.assertLessEqual(abs(roster_top - preview_top), 6)
            self.assertLess(
                workspace._roster_queue_btn.minimumWidth(),
                workspace._queue_inline_btn.sizeHint().width() + 20,
            )
            roster_panel_right = workspace._roster_panel.mapTo(workspace, QPoint(0, 0)).x() + workspace._roster_panel.width()
            queue_button_right = workspace._roster_queue_btn.mapTo(workspace, QPoint(0, 0)).x() + workspace._roster_queue_btn.width()
            self.assertLessEqual(queue_button_right, roster_panel_right)

            workspace.close()

    def test_media_workspace_uses_inline_approve_action_for_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Review.Show.2024"),
            media_info={"id": 101, "name": "Review Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsInstance(row_widget, _RosterRowWidget)
        self.assertIsNone(row_widget._approve_btn)
        self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

        workspace.close()

    def test_media_workspace_inline_approve_refreshes_group_and_swaps_to_queue_action(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def approve_match(self, state):
                state.match_origin = "manual"
                state.checked = True

        state = ScanState(
            folder=Path("C:/library/tv/Review.Show.2024"),
            media_info={"id": 101, "name": "Review Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

        workspace._activate_selected_primary_action()

        self.assertFalse(state.needs_review)
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self.assertTrue(state.checked)

        workspace.close()

    def test_media_workspace_uses_choose_match_labels_for_tied_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Tied.Show.2024"),
            media_info={"id": 101, "name": "Tied Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
            tie_detected=True,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        self.assertEqual(workspace._fix_match_btn.text(), "Choose Match")
        self.assertEqual(workspace._queue_inline_btn.text(), "Choose Match")

        workspace.close()

    def test_media_workspace_hides_single_season_badge_for_multi_season_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                ),
                PreviewItem(
                    original=Path("C:/library/tv/Example.Show.2024/Season 02/Example.Show.S02E01.mkv"),
                    new_name="Example Show (2024) - S02E01 - Return.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 02"),
                    season=2,
                    episodes=[1],
                    status="OK",
                ),
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
            season_assignment=1,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsInstance(row_widget, _RosterRowWidget)
        self.assertNotIn("Season 1", row_widget._meta.text())

        workspace.close()

    def test_media_workspace_roster_check_syncs_preview_file_checks(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _PreviewRowWidget

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        roster_item = workspace._find_roster_item_by_index(0)
        workspace._set_item_check_state(roster_item, True, preview=False)

        self.assertTrue(state.checked)
        self.assertTrue(state.check_vars["0"].get())
        preview_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(preview_widget, _PreviewRowWidget)
        self.assertTrue(preview_widget._check.isChecked())

        workspace.close()

    def test_media_workspace_approved_movie_auto_checks_preview_file(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

            def approve_match(self, state):
                state.match_origin = "manual"
                state.checked = True
                for binding in state.check_vars.values():
                    binding.set(True)

        state = ScanState(
            folder=Path("C:/library/movies/Example Movie"),
            media_info={"id": 101, "title": "Example Movie", "year": "2024", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Example Movie/Example.Movie.2024.mkv"),
                    new_name="Example Movie (2024).mkv",
                    target_dir=Path("C:/library/movies/Example Movie (2024)"),
                    season=None,
                    episodes=[],
                    status="REVIEW: verify",
                    media_type="movie",
                    media_id=101,
                    media_name="Example Movie",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.42,
        )
        workspace = MediaWorkspace(media_type="movie", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        workspace._approve_match(state)

        self.assertTrue(state.checked)
        self.assertTrue(state.check_vars["0"].get())

        workspace.close()

    def test_media_workspace_uses_inline_assign_season_for_duplicate_tv_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Duplicate.Show.2024"),
            media_info={"id": 101, "name": "Duplicate Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.95,
            duplicate_of="Duplicate Show (2024)",
            alternate_matches=[{"id": 202, "name": "Other Show", "year": "2023"}],
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsInstance(row_widget, _RosterRowWidget)
        self.assertIsNone(row_widget._season_btn)
        self.assertIsNone(row_widget._alternates_widget)
        self.assertEqual(workspace._queue_inline_btn.text(), "Assign Season")
        self.assertTrue(workspace._fix_match_btn.isEnabled())

        workspace.close()

    def test_media_workspace_inline_assign_season_swaps_to_queue_action(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def assign_season(self, state, season_num):
                state.season_assignment = season_num
                state.duplicate_of = None
                state.duplicate_of_relative_folder = None
                state.checked = True

        state = ScanState(
            folder=Path("C:/library/tv/Duplicate.Show.2024"),
            media_info={"id": 101, "name": "Duplicate Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.95,
            duplicate_of="Duplicate Show (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        self.assertEqual(workspace._queue_inline_btn.text(), "Assign Season")
        with patch("plex_renamer.gui_qt.widgets.media_workspace.QInputDialog.getInt", return_value=(2, True)):
            workspace._activate_selected_primary_action()

        self.assertEqual(state.season_assignment, 2)
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        workspace.close()

    def test_media_workspace_roster_deselect_all_persists_after_refresh(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        states = [
            ScanState(
                folder=Path("C:/library/tv/Example.Show.2024"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[],
                scanned=True,
                checked=True,
                confidence=1.0,
            ),
            ScanState(
                folder=Path("C:/library/tv/Second.Show.2024"),
                media_info={"id": 102, "name": "Second Show", "year": "2024"},
                preview_items=[],
                scanned=True,
                checked=True,
                confidence=1.0,
            ),
        ]
        media_ctrl = _FakeMediaController(states)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        workspace._roster_master_check.setCheckState(Qt.CheckState.Unchecked)
        workspace.refresh_from_controller()

        self.assertFalse(states[0].checked)
        self.assertFalse(states[1].checked)
        self.assertEqual(workspace._roster_queue_btn.text(), "Queue Checked")
        self.assertFalse(workspace._roster_queue_btn.isEnabled())

        workspace.close()

    def test_media_workspace_queue_checked_preserves_unchecked_matched_rows(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def add_tv_batch(self, states, root, gating):
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        first = ScanState(
            folder=Path("C:/library/tv/Matched.Show.2024"),
            media_info={"id": 101, "name": "Matched Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        second = ScanState(
            folder=Path("C:/library/tv/Unchecked.Show.2024"),
            media_info={"id": 102, "name": "Unchecked Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        media_ctrl = _FakeMediaController([first, second])
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=media_ctrl,
            queue_controller=_FakeQueueController(),
        )
        workspace.show_ready()

        workspace._queue_checked()

        self.assertTrue(first.queued)
        self.assertFalse(second.checked)
        self._assert_roster_section_title(workspace, 0, "QUEUED")
        self._assert_roster_section_title(workspace, 2, "MATCHED")

        workspace.close()

    def test_media_workspace_fix_match_refreshes_duplicate_tv_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _PreviewRowWidget

        class _FakeTMDB:
            def search_tv(self, *_args, **_kwargs):
                return []

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def rematch_tv_state(self, state, chosen, tmdb=None):
                state.media_info = chosen
                state.duplicate_of = None
                state.duplicate_of_relative_folder = None
                state.preview_items = []
                state.scanned = False
                state.checked = True
                return state

            def scan_show(self, state, _tmdb):
                state.preview_items = [
                    PreviewItem(
                        original=Path("C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"),
                        new_name="Replacement Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Replacement Show (2024)/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ]
                state.scanned = True
                state.selected_index = 0

        state = ScanState(
            folder=Path("C:/library/tv/Duplicate.Show.2024"),
            media_info={"id": 101, "name": "Original Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"),
                    new_name="Original Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Original Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.91,
            duplicate_of="Original Show (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=media_ctrl,
            tmdb_provider=_FakeTMDB,
        )
        workspace.show_ready()

        before_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(before_widget, _PreviewRowWidget)
        self.assertIn("Original Show (2024)", before_widget._target.text())

        chosen = {"id": 202, "name": "Replacement Show", "year": "2024"}
        with patch("plex_renamer.gui_qt.widgets.media_workspace.MatchPickerDialog.pick", return_value=chosen):
            workspace._fix_match()

        after_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(after_widget, _PreviewRowWidget)
        self.assertIn("Replacement Show (2024)", after_widget._target.text())
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        workspace.close()

    def test_media_workspace_blocks_duplicate_movie_approval(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.approved: list[ScanState] = []

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

            def approve_match(self, state):
                self.approved.append(state)

        state = ScanState(
            folder=Path("C:/library/movies/Example Movie"),
            media_info={"id": 101, "title": "Example Movie", "year": "2024", "_media_type": "movie"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
            duplicate_of="Primary Movie (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsNotNone(row_widget)
        self.assertIsNone(row_widget._approve_btn)

        with patch.object(workspace, "refresh_from_controller") as refresh_mock:
            workspace._approve_match(state)

        self.assertEqual(media_ctrl.approved, [])
        refresh_mock.assert_not_called()
        workspace.close()

    def test_media_workspace_groups_movie_review_duplicates_under_needs_review(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = states
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        matched_state = ScanState(
            folder=Path("C:/library/movies/Arrival.2016"),
            media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                    new_name="Arrival (2016).mkv",
                    target_dir=Path("C:/library/movies/Arrival (2016)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=22,
                    media_name="Arrival",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        review_duplicate = ScanState(
            folder=Path("C:/library/movies/Arrival.Source"),
            media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Arrival.Source/Arrival.2016.1080p.mkv"),
                    new_name="Arrival (2016).mkv",
                    target_dir=Path("C:/library/movies/Arrival (2016)"),
                    season=None,
                    episodes=[],
                    status="REVIEW: verify",
                    media_type="movie",
                    media_id=22,
                    media_name="Arrival",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.42,
            duplicate_of="Arrival (2016)",
            duplicate_of_relative_folder="Arrival (2016)",
        )
        media_ctrl = _FakeMediaController([matched_state, review_duplicate])
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()

        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self._assert_roster_section_title(workspace, 2, "NEEDS REVIEW")

        workspace.close()

    def test_media_workspace_labels_season_zero_preview_as_specials(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Yuru Camp Specials"),
            media_info={"id": 303, "name": "Yuru Camp", "year": "2018"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Yuru Camp Specials/Campfire Talk.mkv"),
                    new_name="Yuru Camp (2018) - S00E01 - Campfire Talk.mkv",
                    target_dir=Path("C:/library/tv/Yuru Camp (2018)/Season 00"),
                    season=0,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        self.assertTrue(any("SPECIALS" in text for text in self._preview_header_texts(workspace)))

        workspace.close()

    def test_build_placeholder_pixmap_scales_for_hidpi(self):
        from PySide6.QtCore import QSize
        from plex_renamer.gui_qt.widgets._image_utils import build_placeholder_pixmap

        pixmap = build_placeholder_pixmap(
            QSize(48, 70),
            title="EX",
            subtitle="Poster",
            device_pixel_ratio=3.0,
        )

        self.assertEqual(pixmap.width(), 144)
        self.assertEqual(pixmap.height(), 210)
        self.assertEqual(pixmap.devicePixelRatio(), 3.0)

    def test_main_window_queue_shortcuts_trigger_selected_and_checked_actions(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        def _find_action(window: MainWindow, shortcut: str):
            for action in window.actions():
                if action.shortcut().toString() == shortcut:
                    return action
            return None

        window = MainWindow()
        self._reset_main_window_queue(window)

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        window.media_ctrl._batch_states = [state]
        window.media_ctrl._tv_root_folder = Path("C:/library/tv")
        window.media_ctrl.library_selected_index = 0
        window._tv_workspace.show_ready()

        queue_selected = _find_action(window, "Ctrl+Q")
        queue_checked = _find_action(window, "Ctrl+Shift+Q")

        self.assertIsNotNone(queue_selected)
        self.assertIsNotNone(queue_checked)

        queue_selected.trigger()
        self._app.processEvents()
        self.assertEqual(window._queue_badge.count_text(), "1")

        window.queue_ctrl.remove_jobs([job.job_id for job in window.queue_ctrl.get_queue()])
        window._on_queue_changed()
        state.queued = False
        state.checked = True
        self._app.processEvents()

        queue_checked.trigger()
        self._app.processEvents()
        self.assertEqual(window._queue_badge.count_text(), "1")

        window.close()

    def test_main_window_shows_toast_when_cancelled_scan_ends_empty(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        window.media_ctrl.scan_progress.lifecycle = ScanLifecycle.CANCELLED
        window.media_ctrl._batch_states = []
        window.media_ctrl._movie_library_states = []

        window._on_scan_complete()
        self._app.processEvents()

        self.assertEqual(window._toast_manager.toast_count(), 1)
        toast = window._toast_manager._layout.itemAt(0).widget()
        self.assertEqual(toast._title_label.text(), "Scan cancelled")
        self.assertIn("cancelled", toast._message_label.text().lower())

        window.close()

    def test_main_window_keeps_tv_loading_workspace_until_bulk_scan_finishes(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        review_state = ScanState(
            folder=Path("C:/library/tv/Andor.2022"),
            media_info={"id": 10, "name": "Andor", "year": "2022"},
            confidence=0.42,
            alternate_matches=[
                {"id": 11, "name": "Andor", "year": "2022"},
            ],
            scanned=False,
            queued=False,
        )
        window.media_ctrl._active_content_mode = "tv"
        window.media_ctrl._active_library_mode = "tv"
        window.media_ctrl._batch_mode = True
        window.media_ctrl._batch_states = [review_state]
        window.media_ctrl._scan_progress = window.media_ctrl.scan_progress.__class__(
            lifecycle=ScanLifecycle.READY,
            phase="Discovery complete",
            message="Found 1 show",
        )
        window._tv_workspace.show_ready = MagicMock()
        window.media_ctrl.scan_all_shows = MagicMock()

        window._on_scan_complete()

        window._tv_workspace.show_ready.assert_not_called()
        window.media_ctrl.scan_all_shows.assert_called_once_with()
        window.close()

    def test_main_window_keeps_tv_loading_workspace_until_bulk_scan_finishes_for_queued_states(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        queued_state = ScanState(
            folder=Path("C:/library/tv/Queued.Show.2024"),
            media_info={"id": 10, "name": "Queued Show", "year": "2024"},
            scanned=False,
            queued=True,
        )
        window.media_ctrl._active_content_mode = "tv"
        window.media_ctrl._active_library_mode = "tv"
        window.media_ctrl._batch_mode = True
        window.media_ctrl._batch_states = [queued_state]
        window.media_ctrl._scan_progress = window.media_ctrl.scan_progress.__class__(
            lifecycle=ScanLifecycle.READY,
            phase="Discovery complete",
            message="Found 1 show",
        )
        window._tv_workspace.show_ready = MagicMock()
        window.media_ctrl.scan_all_shows = MagicMock()

        window._on_scan_complete()

        window._tv_workspace.show_ready.assert_not_called()
        window.media_ctrl.scan_all_shows.assert_called_once_with()
        window.close()

    def test_main_window_restores_tmdb_snapshot_when_client_is_created(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        with patch("plex_renamer.gui_qt.main_window.QTimer.singleShot"):
            window = MainWindow()
        self._reset_main_window_queue(window)
        window._tmdb = None
        snapshot = {"movie_cache": {"123": {"poster_path": "/poster.jpg"}}}
        lookup = type("Lookup", (), {"is_hit": True, "value": snapshot})()
        window._cache_service.get = MagicMock(return_value=lookup)

        with patch("plex_renamer.gui_qt.main_window.get_api_key", return_value="dummy-key"):
            with patch("plex_renamer.gui_qt.main_window.TMDBClient") as client_cls:
                client = MagicMock()
                client.export_cache_snapshot.return_value = {}
                client_cls.return_value = client

                window._ensure_tmdb()

        client.import_cache_snapshot.assert_called_once_with(snapshot, clear_existing=True)
        window.close()

    def test_main_window_persists_tmdb_snapshot_on_invalidate(self):
        from plex_renamer.gui_qt.main_window import MainWindow, TMDB_CACHE_NAMESPACE, TMDB_CACHE_SNAPSHOT_KEY

        window = MainWindow()
        tmdb = MagicMock()
        snapshot = {"movie_cache": {"123": {"poster_path": "/poster.jpg"}}}
        tmdb.export_cache_snapshot.return_value = snapshot
        window._tmdb = tmdb
        window._cache_service.put = MagicMock()

        window._invalidate_tmdb()

        window._cache_service.put.assert_called_once_with(
            TMDB_CACHE_NAMESPACE,
            TMDB_CACHE_SNAPSHOT_KEY,
            snapshot,
            metadata={"kind": "tmdb_cache_snapshot"},
        )
        self.assertIsNone(window._tmdb)
        window.close()

    def test_main_window_starts_startup_job_poster_backfill(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        with patch("plex_renamer.gui_qt.main_window.QTimer.singleShot") as single_shot:
            window = MainWindow()

        single_shot.assert_called()
        callback = single_shot.call_args.args[1]
        self.assertEqual(callback.__name__, "_start_job_poster_backfill")
        window.close()

    def test_main_window_startup_job_poster_backfill_uses_queue_controller(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        with patch("plex_renamer.gui_qt.main_window.QTimer.singleShot"):
            window = MainWindow()
        window.queue_ctrl.backfill_missing_job_poster_paths = MagicMock(return_value=2)
        window._refresh_job_views = MagicMock()

        with patch("plex_renamer.gui_qt.main_window.get_api_key", return_value="dummy-key"):
            tmdb = MagicMock()
            window._ensure_tmdb = MagicMock(return_value=tmdb)

            window._start_job_poster_backfill()
            QTest.qWait(20)
            self._app.processEvents()

        window.queue_ctrl.backfill_missing_job_poster_paths.assert_called_once_with(tmdb)
        window._refresh_job_views.assert_called_once()
        window.close()

    def test_history_tab_revert_uses_inline_confirmation_banner(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            queue_ctrl = QueueController(store)
            job = RenameJob(
                library_root="C:/library",
                source_folder="Show",
                media_name="Example Show",
                status=JobStatus.COMPLETED,
                undo_data={"renames": [{"old": "a", "new": "b"}, {"old": "c", "new": "d"}]},
            )
            store.add_job(job)
            queue_ctrl.revert_job = MagicMock(return_value=(True, []))

            history_tab = HistoryTab(queue_ctrl)
            history_tab.select_job(job.job_id)
            history_tab._model.set_checked_job_ids({job.job_id})

            history_tab._revert_selected()

            self.assertTrue(history_tab._revert_btn.isHidden())
            self.assertFalse(history_tab._confirm_revert_btn.isHidden())
            self.assertFalse(history_tab._cancel_revert_btn.isHidden())
            self.assertFalse(history_tab._revert_info.isHidden())
            self.assertIn("1 job, 2 files", history_tab._revert_info.text())

            history_tab._confirm_revert()

            queue_ctrl.revert_job.assert_called_once_with(job.job_id)
            self.assertTrue(history_tab._confirm_revert_btn.isHidden())
            self.assertTrue(history_tab._cancel_revert_btn.isHidden())
            self.assertTrue(history_tab._revert_info.isHidden())
            self.assertFalse(history_tab._revert_btn.isHidden())
            history_tab.close()
            queue_ctrl.close()

    def test_queue_and_history_tabs_refresh(self):
        from PySide6.QtWidgets import QHeaderView
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            controller.job_store.add_job(
                RenameJob(
                    library_root=tmp,
                    source_folder="Show",
                    media_type="tv",
                    media_name="Example Show",
                    tmdb_id=123,
                    status=JobStatus.PENDING,
                    rename_ops=[],
                )
            )
            controller.job_store.add_job(
                RenameJob(
                    library_root=tmp,
                    source_folder="Movie",
                    media_type="movie",
                    media_name="Example Movie",
                    tmdb_id=456,
                    status=JobStatus.COMPLETED,
                    rename_ops=[],
                )
            )

            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            queue_tab.refresh()
            history_tab.refresh()

            self.assertEqual(queue_tab._content_splitter.orientation(), Qt.Orientation.Horizontal)
            self.assertEqual(history_tab._content_splitter.orientation(), Qt.Orientation.Horizontal)
            self.assertIs(queue_tab._content_splitter.widget(0), queue_tab._list_pane)
            self.assertIs(queue_tab._content_splitter.widget(1), queue_tab._detail)
            self.assertIs(history_tab._content_splitter.widget(0), history_tab._list_pane)
            self.assertIs(history_tab._content_splitter.widget(1), history_tab._detail)
            self.assertEqual(queue_tab._detail.minimumWidth(), 400)
            self.assertEqual(history_tab._detail.minimumWidth(), 400)
            self.assertFalse(queue_tab._header.stretchLastSection())
            self.assertFalse(history_tab._header.stretchLastSection())
            self.assertEqual(queue_tab._header.sectionResizeMode(2), QHeaderView.ResizeMode.Stretch)
            self.assertEqual(history_tab._header.sectionResizeMode(2), QHeaderView.ResizeMode.Stretch)
            self.assertEqual(queue_tab._header.sectionResizeMode(7), QHeaderView.ResizeMode.Fixed)
            self.assertEqual(history_tab._header.sectionResizeMode(7), QHeaderView.ResizeMode.Fixed)
            self.assertLessEqual(queue_tab._header.sectionSize(7), 92)
            self.assertLessEqual(history_tab._header.sectionSize(7), 92)

            self.assertEqual(queue_tab._model.rowCount(), 1)
            self.assertEqual(history_tab._model.rowCount(), 1)
            self.assertEqual(queue_tab._proxy.rowCount(), 1)
            self.assertEqual(history_tab._proxy.rowCount(), 1)
            self.assertTrue(queue_tab._table.currentIndex().isValid())
            self.assertTrue(history_tab._table.currentIndex().isValid())
            self.assertIs(queue_tab._detail._stack.currentWidget(), queue_tab._detail._detail_page)
            self.assertIs(history_tab._detail._stack.currentWidget(), history_tab._detail._detail_page)
            self.assertEqual(queue_tab._remove_btn.text(), "Remove Selected")
            self.assertFalse(queue_tab._remove_btn.isEnabled())
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "secondary")
            self.assertFalse(hasattr(queue_tab, "_tv_btn"))
            self.assertFalse(hasattr(queue_tab, "_movie_btn"))

            queue_tab._filter_control.setCurrentText("Running")
            self.assertEqual(queue_tab._proxy.rowCount(), 0)
            queue_tab._filter_control.setCurrentText("Pending")
            self.assertEqual(queue_tab._proxy.rowCount(), 1)

            history_tab._filter_control.setCurrentText("Failed")
            self.assertEqual(history_tab._proxy.rowCount(), 0)
            history_tab._filter_control.setCurrentText("Completed")
            self.assertEqual(history_tab._proxy.rowCount(), 1)

            queue_tab._header.checkStateChanged.emit(Qt.CheckState.Checked.value)
            self.assertEqual(len(queue_tab._selected_jobs()), 1)
            self.assertEqual(queue_tab._header.check_state(), Qt.CheckState.Checked)
            self.assertTrue(queue_tab._remove_btn.isEnabled())
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "danger")
            queue_tab._header.checkStateChanged.emit(Qt.CheckState.Unchecked.value)
            self.assertEqual(len(queue_tab._selected_jobs()), 0)
            self.assertEqual(queue_tab._header.check_state(), Qt.CheckState.Unchecked)
            self.assertFalse(queue_tab._remove_btn.isEnabled())
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "secondary")

            history_tab._header.checkStateChanged.emit(Qt.CheckState.Checked.value)
            self.assertEqual(len(history_tab._selected_jobs()), 1)
            self.assertEqual(history_tab._header.check_state(), Qt.CheckState.Checked)
            history_tab._header.checkStateChanged.emit(Qt.CheckState.Unchecked.value)
            self.assertEqual(len(history_tab._selected_jobs()), 0)
            self.assertEqual(history_tab._header.check_state(), Qt.CheckState.Unchecked)

            queue_tab.close()
            history_tab.close()
            controller.close()

    def test_queue_and_history_tabs_show_placeholder_when_empty(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import JobStore

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)

            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)

            self.assertFalse(queue_tab._table.currentIndex().isValid())
            self.assertFalse(history_tab._table.currentIndex().isValid())
            self.assertIs(queue_tab._detail._stack.currentWidget(), queue_tab._detail._empty_page)
            self.assertIs(history_tab._detail._stack.currentWidget(), history_tab._detail._empty_page)
            self.assertEqual(queue_tab._detail._empty_title.text(), "No Job Selected!")
            self.assertEqual(history_tab._detail._empty_title.text(), "No Job Selected!")

            queue_tab.close()
            history_tab.close()
            controller.close()

    def test_queue_tab_context_menu_exposes_queue_and_folder_actions(self):
        from PySide6.QtWidgets import QMenu
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import JobStore, RenameJob, RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp)
            (library_root / "Show").mkdir()
            store = JobStore(db_path=library_root / "jobs.db")
            controller = QueueController(store)
            job = RenameJob(
                library_root=str(library_root),
                source_folder="Show",
                media_type="tv",
                media_name="Example Show",
                tmdb_id=123,
                status=JobStatus.PENDING,
                rename_ops=[
                    RenameOp(
                        original_relative="Show/Example Show - 001.mkv",
                        new_name="Example Show - S01E01.mkv",
                        target_dir_relative="Show/Season 01",
                        status="OK",
                        selected=True,
                    )
                ],
            )
            controller.job_store.add_job(job)

            queue_tab = QueueTab(controller)
            queue_tab.refresh()
            queue_tab.select_job(job.job_id)
            queue_tab._model.set_checked_job_ids({job.job_id})
            self._app.processEvents()

            menu = QMenu()
            queue_tab._populate_context_menu(menu, queue_tab._focused_job(), queue_tab._selected_jobs())
            action_text = [action.text() for action in menu.actions() if not action.isSeparator()]

            self.assertEqual(
                action_text,
                [
                    "Run This Job",
                    "Run Selected",
                    "Remove Selected",
                    "Move to Top of Queue",
                    "Open Source Folder",
                ],
            )

            queue_tab.close()
            menu.close()
            controller.close()

    def test_queue_tab_run_selected_executes_checked_pending_jobs_in_order(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            first = RenameJob(
                library_root=tmp,
                source_folder="Show1",
                media_type="tv",
                media_name="Example Show 1",
                tmdb_id=123,
                status=JobStatus.PENDING,
                rename_ops=[],
            )
            second = RenameJob(
                library_root=tmp,
                source_folder="Show2",
                media_type="tv",
                media_name="Example Show 2",
                tmdb_id=456,
                status=JobStatus.PENDING,
                rename_ops=[],
            )
            controller.job_store.add_job(first)
            controller.job_store.add_job(second)
            controller.execute_single = MagicMock(return_value=True)

            queue_tab = QueueTab(controller)
            queue_tab.refresh()
            queue_tab._model.set_checked_job_ids({first.job_id, second.job_id})

            self.assertTrue(queue_tab._execute_btn.isEnabled())
            self.assertEqual(queue_tab._execute_btn.text(), "Run Selected")

            queue_tab._execute_btn.click()

            self.assertEqual(
                [call.args[0] for call in controller.execute_single.call_args_list],
                [first.job_id, second.job_id],
            )
            queue_tab.close()
            controller.close()

    def test_media_workspace_roster_master_checkbox_controls_eligible_states(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.active_scan = states[0]
                self.tv_root_folder = Path("C:/library/tv")
                self.movie_folder = Path("C:/library/movies")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    self.active_scan = self.batch_states[index]
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state_a = ScanState(
            folder=Path("C:/library/tv/ShowA"),
            media_info={"id": 1, "name": "Show A", "year": "2020"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        state_b = ScanState(
            folder=Path("C:/library/tv/ShowB"),
            media_info={"id": 2, "name": "Show B", "year": "2021"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=1.0,
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController([state_a, state_b]),
            queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=2)})(),
        )
        workspace.show_ready()

        workspace._roster_master_check.click()

        self.assertTrue(state_a.checked)
        self.assertTrue(state_b.checked)
        self.assertEqual(workspace._roster_master_check.checkState(), Qt.CheckState.Checked)

        workspace._roster_master_check.click()

        self.assertFalse(state_a.checked)
        self.assertFalse(state_b.checked)
        self.assertEqual(workspace._roster_master_check.checkState(), Qt.CheckState.Unchecked)

        workspace.close()

    def test_queue_tab_checkbox_column_click_toggles_checked_jobs(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            controller.job_store.add_job(
                RenameJob(
                    library_root=tmp,
                    source_folder="Show",
                    media_type="tv",
                    media_name="Example Show",
                    tmdb_id=123,
                    status=JobStatus.PENDING,
                    rename_ops=[],
                )
            )

            queue_tab = QueueTab(controller)
            queue_tab.refresh()
            queue_tab.show()
            self._app.processEvents()

            checkbox_index = queue_tab._proxy.index(0, 0)
            QTest.mouseClick(
                queue_tab._table.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                queue_tab._table.visualRect(checkbox_index).center(),
            )
            self.assertEqual(len(queue_tab._selected_jobs()), 1)

            QTest.mouseClick(
                queue_tab._table.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                queue_tab._table.visualRect(checkbox_index).center(),
            )
            self.assertEqual(len(queue_tab._selected_jobs()), 0)

            queue_tab.close()
            controller.close()

    def test_media_workspace_populates_roster_and_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                states = self.movie_library_states
                if 0 <= index < len(states):
                    return states[index]
                return None

            def sync_queued_states(self):
                return None

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(self, states, root, command_gating):
                self.called = True
                return BatchQueueResult(added=len(states))

        media_ctrl = _FakeMediaController()
        queue_ctrl = _FakeQueueController()
        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            ready_state = ScanState(
                folder=Path("C:/library/movies/Dune.Part.Two.2024"),
                media_info={"id": 11, "title": "Dune: Part Two", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Dune.Part.Two.2024/Dune.Part.Two.2024.mkv"),
                        new_name="Dune: Part Two (2024).mkv",
                        target_dir=Path("C:/library/movies/Dune: Part Two (2024)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=11,
                        media_name="Dune: Part Two",
                        companions=[],
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            matched_state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                        companions=[],
                    )
                ],
                scanned=False,
                checked=False,
                confidence=1.0,
            )
            media_ctrl.movie_library_states = [ready_state, matched_state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertEqual(workspace._roster_list.count(), 3)
            self._assert_roster_section_title(workspace, 0, "MATCHED")
            self.assertIsNone(workspace._roster_list.item(1).data(Qt.ItemDataRole.CheckStateRole))
            self.assertIsNone(workspace._preview_list.item(0).data(Qt.ItemDataRole.CheckStateRole))
            self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())
            self.assertIn("2024", workspace._folder_plan_label.text())
            self.assertGreater(workspace._preview_list.count(), 0)

            workspace._queue_checked()
            self.assertTrue(queue_ctrl.called)

            workspace.close()

    def test_media_workspace_groups_movie_duplicates_once(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            matched_state = ScanState(
                folder=Path("C:/library/movies/Alien.1979"),
                media_info={"id": 42, "title": "Alien", "year": "1979", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Alien.1979/Alien.1979.mkv"),
                        new_name="Alien (1979).mkv",
                        target_dir=Path("C:/library/movies/Alien (1979)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=42,
                        media_name="Alien",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            duplicate_state = ScanState(
                folder=Path("C:/library/movies/Alien.Source"),
                media_info={"id": 42, "title": "Alien", "year": "1979", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Alien.Source/Alien.1979.1080p.mkv"),
                        new_name="Alien (1979).mkv",
                        target_dir=Path("C:/library/movies/Alien (1979)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=42,
                        media_name="Alien",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
                duplicate_of="Alien (1979)",
                duplicate_of_relative_folder="Alien (1979)",
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [matched_state, duplicate_state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertEqual(workspace._roster_list.count(), 4)
            self._assert_roster_section_title(workspace, 0, "MATCHED")
            self._assert_roster_section_title(workspace, 2, "DUPLICATES")
            self.assertIsNotNone(self._roster_widget_for_index(workspace, 0))
            self.assertIsNotNone(self._roster_widget_for_index(workspace, 1))

            workspace.close()

    def test_media_workspace_applies_live_display_settings(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                states = self.movie_library_states
                if 0 <= index < len(states):
                    return states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                        companions=[],
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            state.preview_items[0].companions = [
                CompanionFile(
                    original=Path("C:/library/movies/Arrival.2016/Arrival.2016.en.srt"),
                    new_name="Arrival (2016).en.srt",
                    file_type="subtitle",
                )
            ]

            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            preview_widget = self._preview_widget_for_index(workspace, 0)
            self.assertIsNotNone(preview_widget)
            self.assertEqual(preview_widget._target.text(), "-> Arrival (2016).mkv")

            settings.view_mode = "compact"
            settings.show_companion_files = True
            workspace.apply_settings()

            preview_widget = self._preview_widget_for_index(workspace, 0)
            self.assertIsNotNone(preview_widget)
            self.assertEqual(preview_widget._target.text(), "-> Arrival (2016).mkv")
            self.assertIsNotNone(preview_widget._companions)
            self.assertIn("Arrival.2016.en.srt", preview_widget._companions.text())
            self.assertEqual(workspace._roster_list.iconSize().width(), 32)

            workspace.close()

    def test_match_picker_enter_runs_search_instead_of_accepting(self):
        from plex_renamer.gui_qt.widgets.match_picker_dialog import MatchPickerDialog

        search_calls: list[tuple[str, str | None]] = []

        def _search(query: str, year_hint: str | None) -> list[dict]:
            search_calls.append((query, year_hint))
            return [
                {
                    "id": 99,
                    "title": "Arrival",
                    "year": "2016",
                    "overview": "First contact.",
                }
            ]

        dialog = MatchPickerDialog(
            title="Fix Match",
            title_key="title",
            initial_query="Arrival",
            initial_results=[{"id": 1, "title": "Old Result", "year": "2015"}],
            search_callback=_search,
            year_hint="2016",
        )
        dialog.show()
        self._app.processEvents()

        dialog._query.setFocus()
        dialog._query.selectAll()
        QTest.keyClicks(dialog._query, "Arrival")
        QTest.keyClick(dialog._query, Qt.Key.Key_Return)
        self._app.processEvents()

        self.assertEqual(search_calls, [("Arrival", "2016")])
        self.assertEqual(dialog.result(), 0)
        self.assertTrue(dialog._ok_button.isEnabled())

        dialog.close()

    def test_media_workspace_renders_inline_alternate_matches_for_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            review_state = ScanState(
                folder=Path("C:/library/movies/Crash.Collectors.Edition"),
                media_info={"id": 1, "title": "Crash", "year": "1996"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Crash.Collectors.Edition/Crash.Collectors.Edition.mkv"),
                        new_name="Crash (1996).mkv",
                        target_dir=Path("C:/library/movies/Crash (1996)"),
                        season=None,
                        episodes=[],
                        status="REVIEW: verify",
                        media_type="movie",
                        media_id=1,
                        media_name="Crash",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=0.42,
                alternate_matches=[
                    {"id": 2, "title": "Crash", "year": "2004"},
                    {"id": 3, "title": "Crash Landing", "year": "1999"},
                ],
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [review_state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertIsNone(row_widget._alternates_layout)
            self.assertIsNone(row_widget._alternates_widget)
            self.assertTrue(workspace._fix_match_btn.isEnabled())
            self.assertFalse(row_widget._check.isWindow())
            self.assertEqual(row_widget.styleSheet(), "")
            self.assertEqual(row_widget.property("band"), "low")
            self.assertEqual(row_widget.property("selectionState"), "selected")
            self.assertTrue(row_widget._status.isHidden())

            workspace.close()

    def test_media_workspace_sorts_tv_preview_items_by_episode_number(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _PreviewRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example Show"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E03.mkv"),
                        new_name="Example Show (2024) - S01E03 - Episode 3.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[3],
                        status="OK",
                    ),
                    PreviewItem(
                        original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E01.mkv"),
                        new_name="Example Show (2024) - S01E01 - Episode 1.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    ),
                    PreviewItem(
                        original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E02.mkv"),
                        new_name="Example Show (2024) - S01E02 - Episode 2.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[2],
                        status="OK",
                    ),
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            preview_indices = []
            for row in range(workspace._preview_list.count()):
                item = workspace._preview_list.item(row)
                index = item.data(Qt.ItemDataRole.UserRole)
                if index is not None:
                    preview_indices.append(index)

            self.assertEqual(preview_indices, [1, 2, 0])

            preview_row_widget = None
            for row in range(workspace._preview_list.count()):
                item = workspace._preview_list.item(row)
                widget = workspace._preview_list.itemWidget(item)
                if isinstance(widget, _PreviewRowWidget):
                    preview_row_widget = widget
                    break

            self.assertIsNotNone(preview_row_widget)
            self.assertFalse(preview_row_widget._check.isWindow())
            self.assertEqual(preview_row_widget.styleSheet(), "")
            self.assertEqual(preview_row_widget.property("band"), "high")
            self.assertEqual(preview_row_widget.property("selectionState"), "selected")
            self.assertEqual(preview_row_widget._status.styleSheet(), "")
            self.assertEqual(preview_row_widget._status.property("tone"), "success")

            workspace.close()

    def test_media_workspace_uses_expected_episode_count_in_season_headers(self):
        from plex_renamer.engine import CompletenessReport, SeasonCompleteness
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example Show"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Episode 1.mkv",
                    target_dir=Path("C:/library/tv/Example Show/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                ),
                PreviewItem(
                    original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E02.mkv"),
                    new_name="Example Show (2024) - S01E02 - Episode 2.mkv",
                    target_dir=Path("C:/library/tv/Example Show/Season 01"),
                    season=1,
                    episodes=[2],
                    status="SKIP: sample",
                ),
                PreviewItem(
                    original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E03.mkv"),
                    new_name="Example Show (2024) - S01E03 - Episode 3.mkv",
                    target_dir=Path("C:/library/tv/Example Show/Season 01"),
                    season=1,
                    episodes=[3],
                    status="UNMATCHED: extras",
                ),
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
            completeness=CompletenessReport(
                seasons={1: SeasonCompleteness(season=1, expected=2, matched=1, missing=[])},
                specials=None,
                total_expected=2,
                total_matched=1,
                total_missing=[],
            ),
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        self.assertTrue(any("SEASON 1 — 3/2" in text for text in self._preview_header_texts(workspace)))

        workspace.close()

    def test_media_workspace_keeps_folder_rename_states_out_of_plex_ready(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example.Show.2024.Source"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Example.Show.2024.Source/Season 01/Example Show (2024) - S01E01 - Pilot.mkv"),
                        new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Example.Show.2024.Source/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            self._assert_roster_section_title(workspace, 0, "MATCHED")
            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertTrue(row_widget._status.isHidden())

            workspace.close()

    def test_tv_workspace_blocks_review_duplicate_and_plex_ready_from_queue_selection(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _episode(path_root: str, season: int, episode: int, *, status: str = "OK", new_name: str | None = None, target_dir: Path | None = None):
            original = Path(f"{path_root}/Season 01/Example.Show.S01E0{episode}.mkv")
            return PreviewItem(
                original=original,
                new_name=new_name if new_name is not None else f"Example Show (2024) - S01E0{episode} - Pilot.mkv",
                target_dir=target_dir if target_dir is not None else Path(f"{path_root}/Season 01"),
                season=season,
                episodes=[episode],
                status=status,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            matched_state = ScanState(
                folder=Path("C:/library/tv/Matched.Show.2024"),
                media_info={"id": 101, "name": "Matched Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"),
                        new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Matched.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            review_state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 102, "name": "Review Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
                        new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="REVIEW",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=0.42,
                alternate_matches=[{"id": 202, "name": "Review Show", "year": "2024"}],
            )
            duplicate_state = ScanState(
                folder=Path("C:/library/tv/Duplicate.Show.2024"),
                media_info={"id": 101, "name": "Matched Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"),
                        new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Duplicate.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
                duplicate_of="Matched Show (2024)",
            )
            plex_ready_root = "C:/library/tv/Plex Ready Show (2024)"
            plex_ready_state = ScanState(
                folder=Path(plex_ready_root),
                media_info={"id": 103, "name": "Plex Ready Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"{plex_ready_root}/Season 01/Plex Ready Show (2024) - S01E01 - Pilot.mkv"),
                        new_name="Plex Ready Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"{plex_ready_root}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [matched_state, review_state, duplicate_state, plex_ready_state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()
            workspace._roster_collapsed["plex-ready"] = False
            workspace.refresh_from_controller()

            matched_widget = self._roster_widget_for_index(workspace, 0)
            review_widget = self._roster_widget_for_index(workspace, 1)
            duplicate_widget = self._roster_widget_for_index(workspace, 2)
            plex_ready_widget = self._roster_widget_for_index(workspace, 3)

            self.assertIsInstance(matched_widget, _RosterRowWidget)
            self.assertFalse(matched_widget._check.isHidden())
            self.assertTrue(matched_state.checked)

            self.assertIsInstance(review_widget, _RosterRowWidget)
            self.assertFalse(review_state.checked)
            self.assertTrue(review_widget._check.isHidden())

            self.assertIsInstance(duplicate_widget, _RosterRowWidget)
            self.assertFalse(duplicate_state.checked)
            self.assertTrue(duplicate_widget._check.isHidden())

            self.assertIsInstance(plex_ready_widget, _RosterRowWidget)
            self.assertFalse(plex_ready_state.checked)
            self.assertTrue(plex_ready_widget._check.isHidden())

            workspace.close()

    def test_media_workspace_prefers_matched_when_auto_selection_lands_on_plex_ready(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = list(states)
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            plex_ready_root = "C:/library/tv/Auto Selected Show (2024)"
            plex_ready_state = ScanState(
                folder=Path(plex_ready_root),
                media_info={"id": 101, "name": "Auto Selected Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"{plex_ready_root}/Season 01/Auto Selected Show (2024) - S01E01 - Pilot.mkv"),
                        new_name="Auto Selected Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"{plex_ready_root}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
            )
            matched_state = ScanState(
                folder=Path("C:/library/tv/Matched.Show.2024"),
                media_info={"id": 102, "name": "Matched Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"),
                        new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Matched.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=0.93,
            )
            review_state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 103, "name": "Review Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
                        new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="REVIEW",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=0.54,
                alternate_matches=[{"id": 203, "name": "Review Show", "year": "2024"}],
            )

            media_ctrl = _FakeMediaController([plex_ready_state, matched_state, review_state])
            workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl, settings_service=settings)

            workspace.show_ready()
            self.assertEqual(media_ctrl.library_selected_index, 1)
            self.assertEqual(workspace._selected_state(), matched_state)

            media_ctrl.library_selected_index = 0
            workspace._roster_selection_is_auto = True
            workspace.refresh_from_controller()

            self.assertEqual(media_ctrl.library_selected_index, 1)
            self.assertEqual(workspace._selected_state(), matched_state)

            workspace.close()

    def test_media_workspace_mutes_roster_confidence_for_queued_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example.Show.2024.Source"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Example.Show.2024.Source/Season 01/Example Show (2024) - S01E01 - Pilot.mkv"),
                        new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Example.Show.2024.Source/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
                queued=True,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertEqual(row_widget._confidence._color.name(), "#777777")

            workspace.close()

    def test_media_workspace_roster_rows_use_placeholder_thumbnail_without_poster(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example.Show.2024.Source"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
                tmdb_provider=lambda: None,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertIsNotNone(row_widget._poster.pixmap())
            self.assertEqual(row_widget._poster.text(), "")

            workspace.close()

    def test_media_workspace_shows_threshold_aware_roster_match_text(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            settings.auto_accept_threshold = 0.6
            review_state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 102, "name": "Review Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
                        new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="REVIEW",
                    )
                ],
                scanned=True,
                confidence=0.42,
                alternate_matches=[{"id": 202, "name": "Review Show", "year": "2024"}],
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [review_state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=0)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertIn("42% confidence", row_widget._meta.text())
            self.assertIn("needs review", row_widget._meta.text())
            self.assertTrue(row_widget._status.isHidden())
            self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

            workspace.close()

    def test_media_workspace_reuses_unchanged_roster_widgets_on_refresh(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            first = _make_state("Example Show", 101)
            second = _make_state("Another Show", 202)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [first, second]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            original_widget = self._roster_widget_for_index(workspace, 0)
            self.assertIsInstance(original_widget, _RosterRowWidget)

            second.queued = True
            workspace.refresh_from_controller()

            refreshed_widget = self._roster_widget_for_index(workspace, 0)
            self.assertIs(refreshed_widget, original_widget)

            workspace.close()

    def test_media_workspace_queues_tv_states_without_crashing_on_regroup(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(self, states, root, gating):
                self.called = True
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [
                _make_state("Show.One.2024", 101),
                _make_state("Show.Two.2024", 102),
            ]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            workspace._queue_checked()
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self._assert_roster_section_title(workspace, 0, "QUEUED")

            workspace.close()

    def test_media_workspace_preserves_movie_preview_after_queue_regroup(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(self, states, root, gating):
                self.called = True
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [state]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertEqual(workspace._preview_list.count(), 3)
            workspace._queue_checked()
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self._assert_roster_section_title(workspace, 0, "QUEUED")
            self.assertEqual(workspace._preview_list.count(), 3)
            self.assertTrue(any("FOLDER" in text for text in self._preview_header_texts(workspace)))
            self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())

            workspace.close()

    def test_media_workspace_movie_refresh_keeps_same_folder_movies_unique_after_approval(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = states
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        root = Path("C:/library/movies/Quarantine")
        matched_one = ScanState(
            folder=root,
            source_file=root / "[QM] Evangelion 1.11.mkv",
            media_info={"id": 11, "title": "Evangelion 1.11", "year": "2007", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=root / "[QM] Evangelion 1.11.mkv",
                    new_name="Evangelion 1.11 (2007).mkv",
                    target_dir=Path("C:/library/movies/Evangelion 1.11 (2007)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=11,
                    media_name="Evangelion 1.11",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        matched_two = ScanState(
            folder=root,
            source_file=root / "[LG] Evangelion 3.0+1.11.mkv",
            media_info={"id": 44, "title": "Evangelion: 3.0+1.11 Thrice Upon a Time", "year": "2021", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=root / "[LG] Evangelion 3.0+1.11.mkv",
                    new_name="Evangelion: 3.0+1.11 Thrice Upon a Time (2021).mkv",
                    target_dir=Path("C:/library/movies/Evangelion: 3.0+1.11 Thrice Upon a Time (2021)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=44,
                    media_name="Evangelion: 3.0+1.11 Thrice Upon a Time",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        review_state = ScanState(
            folder=root,
            source_file=root / "[Baws] Evangelion 3.33.mkv",
            media_info={"id": 33, "title": "Evangelion: 3.0 You Can (Not) Redo", "year": "2012", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=root / "[Baws] Evangelion 3.33.mkv",
                    new_name="Evangelion: 3.0 You Can (Not) Redo (2012).mkv",
                    target_dir=Path("C:/library/movies/Evangelion: 3.0 You Can (Not) Redo (2012)"),
                    season=None,
                    episodes=[],
                    status="REVIEW: verify",
                    media_type="movie",
                    media_id=33,
                    media_name="Evangelion: 3.0 You Can (Not) Redo",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.42,
        )

        media_ctrl = _FakeMediaController([matched_one, matched_two, review_state])
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()
        self.assertEqual(workspace._roster_list.count(), 5)

        review_state.match_origin = "manual"
        review_state.checked = True
        workspace.refresh_from_controller()
        workspace.refresh_from_controller()

        self.assertEqual(workspace._roster_list.count(), 4)
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        seen_titles = []
        for row in range(workspace._roster_list.count()):
            item = workspace._roster_list.item(row)
            widget = workspace._roster_list.itemWidget(item)
            if widget is not None and hasattr(widget, "_title"):
                seen_titles.append(widget._title.text())
        self.assertEqual(len(seen_titles), 3)
        self.assertEqual(len(set(seen_titles)), 3)
        self.assertIn("Evangelion: 3.0 You Can (Not) Redo (2012)", seen_titles)

        workspace.close()

    def test_toast_manager_repositions_stacked_wrapped_toasts_without_clipping(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        window.resize(900, 700)
        long_message = (
            "This is a long toast message intended to wrap across multiple lines so "
            "the stacked notification layout has to allocate the correct height."
        )

        window._toast_manager.show_toast(title="Queue Update", message=long_message, duration_ms=0)
        window._toast_manager.show_toast(title="Queue Update", message=long_message, duration_ms=0)
        self._app.processEvents()

        manager = window._toast_manager
        toast_geometries = []
        for index in range(manager._layout.count()):
            item = manager._layout.itemAt(index)
            toast = item.widget() if item is not None else None
            if toast is None:
                continue
            toast_geometries.append(toast.geometry())

        self.assertEqual(len(toast_geometries), 2)
        self.assertTrue(all(geometry.top() >= 0 for geometry in toast_geometries))
        self.assertTrue(all(geometry.bottom() <= manager.height() for geometry in toast_geometries))

        window.close()

    def test_toast_manager_caps_visible_toasts_with_summary_card(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        for index in range(6):
            window._toast_manager.show_toast(
                title=f"Toast {index}",
                message="A queued notification",
                duration_ms=0,
            )
        self._app.processEvents()

        self.assertEqual(window._toast_manager.toast_count(), 4)
        self.assertIsNotNone(window._toast_manager._summary_toast)
        self.assertEqual(window._toast_manager._summary_toast._message_label.text(), "3 more notifications collapsed.")

        window.close()

    def test_queue_tab_remove_updates_badge_and_tv_requeue_state(self):
        from PySide6.QtWidgets import QMessageBox
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self._reset_main_window_queue(window)

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        window.media_ctrl._batch_states = [state]
        window.media_ctrl._tv_root_folder = Path("C:/library/tv")
        window.media_ctrl.library_selected_index = 0

        window._tv_workspace.show_ready()
        window._tv_workspace._queue_checked()
        self._app.processEvents()

        self.assertEqual(window._queue_badge.count_text(), "1")
        self.assertTrue(state.queued)

        window._switch_to_tab(2)
        self._app.processEvents()
        job_id = window.queue_ctrl.get_queue()[0].job_id
        window._queue_tab.select_job(job_id)
        window._queue_tab._model.set_jobs_checked({job_id}, True)

        with patch(
            "plex_renamer.gui_qt.widgets.queue_tab.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._queue_tab._remove_selected()
        self._app.processEvents()

        self.assertEqual(window._queue_badge.count_text(), "0")

        window._switch_to_tab(0)
        self._app.processEvents()

        self.assertFalse(state.queued)
        self.assertTrue(window._tv_workspace._queue_inline_btn.isEnabled())

        window.close()

    def test_completed_queue_job_projects_tv_state_back_to_plex_ready_on_tab_return(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self._reset_main_window_queue(window)

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        window.media_ctrl._batch_states = [state]
        window.media_ctrl._tv_root_folder = Path("C:/library/tv")
        window.media_ctrl.library_selected_index = 0

        window._tv_workspace.show_ready()
        window._tv_workspace._queue_checked()
        self._app.processEvents()

        job = window.queue_ctrl.get_queue()[0]
        window.queue_ctrl.job_store.update_status(job.job_id, JobStatus.COMPLETED)
        window.queue_ctrl.job_store.set_undo_data(job.job_id, {"renames": [], "created_dirs": [], "removed_dirs": [], "renamed_dirs": []})
        job.status = JobStatus.COMPLETED

        window._switch_to_tab(2)
        self._app.processEvents()

        window._on_job_completed(job, RenameResult(renamed_count=1))
        window._on_queue_changed()

        window._switch_to_tab(0)
        self._app.processEvents()
        window._tv_workspace._roster_collapsed["plex-ready"] = False
        window._tv_workspace.refresh_from_controller()

        self.assertEqual(state.folder, Path("C:/library/tv/Example Show (2024)"))
        self.assertEqual(state.preview_items[0].original.name, "Example Show (2024) - S01E01 - Pilot.mkv")
        self.assertFalse(state.preview_items[0].is_actionable)
        self._assert_roster_section_title(window._tv_workspace, 0, "PLEX READY")

        window.close()


if __name__ == "__main__":
    unittest.main()