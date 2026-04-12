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


class QtQueueHistoryTests(QtSmokeBase):
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