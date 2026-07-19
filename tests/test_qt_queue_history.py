from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from conftest_qt import QtSmokeBase
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from plex_renamer.constants import JobStatus
from plex_renamer.engine import PreviewItem, RenameResult, ScanState
from plex_renamer.job_store import JobStore


class QtQueueHistoryTests(QtSmokeBase):
    def test_job_table_files_column_merges_selected_counts(self):
        from plex_renamer.gui_qt.models.job_table_model import (
            SORT_ROLE,
            JobTableModel,
            files_cell_text,
        )
        from plex_renamer.job_store import RenameJob, RenameOp

        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            rename_ops=[
                RenameOp(
                    original_relative="Show/Example Show - S01E01.mkv",
                    new_name="Example Show - S01E01.mkv",
                    target_dir_relative="Show/Season 01",
                    status="OK",
                    selected=True,
                    file_type="video",
                ),
                RenameOp(
                    original_relative="Show/Example Show - S01E01.eng.srt",
                    new_name="Example Show - S01E01.eng.srt",
                    target_dir_relative="Show/Season 01",
                    status="OK",
                    selected=True,
                    file_type="subtitle",
                ),
                RenameOp(
                    original_relative="Show/Example Show - S01E02.mkv",
                    new_name="Example Show - S01E02.mkv",
                    target_dir_relative="Show/Season 01",
                    status="OK",
                    selected=False,
                    file_type="video",
                ),
                RenameOp(
                    original_relative="Show/Example Show - S01E02.eng.srt",
                    new_name="Example Show - S01E02.eng.srt",
                    target_dir_relative="Show/Season 01",
                    status="OK",
                    selected=False,
                    file_type="subtitle",
                ),
            ],
        )
        model = JobTableModel(history=False)
        model.set_jobs([job])

        self.assertEqual(model.columnCount(), 7)
        self.assertEqual(model.headerData(5, Qt.Orientation.Horizontal), "Files")
        self.assertEqual(model.headerData(6, Qt.Orientation.Horizontal), "When")
        # Only the selected pair counts: 1 video + 1 companion.
        self.assertEqual(
            model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole),
            "1 file (1 comp.)",
        )
        self.assertEqual(model.data(model.index(0, 5), SORT_ROLE), 1)
        self.assertEqual(files_cell_text(job), "1 file (1 comp.)")
        # When column renders a formatted date, not a count.
        self.assertNotEqual(model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole), "1")

    def test_job_table_files_column_omits_companion_suffix_when_none(self):
        from plex_renamer.gui_qt.models.job_table_model import files_cell_text
        from plex_renamer.job_store import RenameJob, RenameOp

        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            rename_ops=[
                RenameOp(
                    original_relative="Show/a.mkv",
                    new_name="A.mkv",
                    target_dir_relative="Show",
                    status="OK",
                    selected=True,
                    file_type="video",
                ),
                RenameOp(
                    original_relative="Show/b.mkv",
                    new_name="B.mkv",
                    target_dir_relative="Show",
                    status="OK",
                    selected=True,
                    file_type="video",
                ),
                RenameOp(
                    original_relative="Show/c.mkv",
                    new_name="C.mkv",
                    target_dir_relative="Show",
                    status="OK",
                    selected=True,
                    file_type="video",
                ),
            ],
        )
        self.assertEqual(files_cell_text(job), "3 files")

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
            self.assertTrue(history_tab._revert_banner.isVisibleTo(history_tab))
            self.assertTrue(history_tab._confirm_revert_btn.isVisibleTo(history_tab))
            self.assertTrue(history_tab._cancel_revert_btn.isVisibleTo(history_tab))
            self.assertTrue(history_tab._revert_info.isVisibleTo(history_tab))
            self.assertIn("1 job, 2 files", history_tab._revert_info.text())

            history_tab._confirm_revert()

            queue_ctrl.revert_job.assert_called_once_with(job.job_id)
            self.assertFalse(history_tab._revert_banner.isVisibleTo(history_tab))
            self.assertFalse(history_tab._confirm_revert_btn.isVisibleTo(history_tab))
            self.assertFalse(history_tab._cancel_revert_btn.isVisibleTo(history_tab))
            self.assertFalse(history_tab._revert_info.isVisibleTo(history_tab))
            self.assertFalse(history_tab._revert_btn.isHidden())
            history_tab.close()
            queue_ctrl.close()

    def test_history_header_and_revert_use_only_revertible_checked_jobs(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            queue_ctrl = QueueController(store)
            revertible = RenameJob(
                library_root="C:/library",
                source_folder="Show",
                media_name="Revertible Show",
                status=JobStatus.COMPLETED,
                undo_data={"renames": [{"old": "a", "new": "b"}, {"old": "c", "new": "d"}]},
            )
            completed_without_undo = RenameJob(
                library_root="C:/library",
                source_folder="NoUndo",
                media_name="No Undo Show",
                status=JobStatus.COMPLETED,
                undo_data=None,
            )
            failed_with_undo = RenameJob(
                library_root="C:/library",
                source_folder="Failed",
                media_name="Failed Show",
                status=JobStatus.FAILED,
                undo_data={"renames": [{"old": "e", "new": "f"}]},
            )
            store.add_job(revertible)
            store.add_job(completed_without_undo)
            store.add_job(failed_with_undo)

            history_tab = HistoryTab(queue_ctrl)
            self._app.processEvents()
            history_tab._header.checkStateChanged.emit(Qt.CheckState.Checked.value)

            self.assertEqual(history_tab._model.checked_job_ids(), {revertible.job_id})
            self.assertEqual(history_tab._selection_status.text(), "1 job checked")

            def check_state_for(job_id: str):
                for row, job in enumerate(history_tab._model.jobs()):
                    if job.job_id == job_id:
                        return history_tab._model.data(
                            history_tab._model.index(row, 0),
                            Qt.ItemDataRole.CheckStateRole,
                        )
                self.fail(f"Missing job {job_id}")

            self.assertEqual(check_state_for(revertible.job_id), Qt.CheckState.Checked)
            self.assertIsNone(check_state_for(completed_without_undo.job_id))
            self.assertIsNone(check_state_for(failed_with_undo.job_id))

            history_tab._revert_selected()

            self.assertEqual(history_tab._pending_revert_job_ids, [revertible.job_id])
            self.assertIn("1 job, 2 files", history_tab._revert_info.text())

            history_tab.close()
            queue_ctrl.close()

    def test_history_header_click_resyncs_when_no_visible_revertible_jobs(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            queue_ctrl = QueueController(store)
            job = RenameJob(
                library_root="C:/library",
                source_folder="NoUndo",
                media_name="No Undo Show",
                status=JobStatus.COMPLETED,
                undo_data=None,
            )
            store.add_job(job)

            history_tab = HistoryTab(queue_ctrl)
            try:
                history_tab.show()
                self._app.processEvents()

                QTest.mouseClick(
                    history_tab._header.viewport(),
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    QPoint(
                        history_tab._header.sectionViewportPosition(0)
                        + history_tab._header.sectionSize(0) // 2,
                        history_tab._header.height() // 2,
                    ),
                )

                self.assertEqual(history_tab._model.checked_job_ids(), set())
                self.assertEqual(history_tab._selection_status.text(), "0 jobs checked")
                self.assertEqual(history_tab._header.check_state(), Qt.CheckState.Unchecked)
            finally:
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
                    undo_data={"renames": [{"old": "a", "new": "b"}]},
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
            self.assertEqual(
                history_tab._header.sectionResizeMode(2), QHeaderView.ResizeMode.Stretch
            )
            self.assertEqual(queue_tab._header.sectionResizeMode(6), QHeaderView.ResizeMode.Fixed)
            self.assertEqual(history_tab._header.sectionResizeMode(6), QHeaderView.ResizeMode.Fixed)
            self.assertLessEqual(queue_tab._header.sectionSize(6), 92)
            self.assertLessEqual(history_tab._header.sectionSize(6), 92)

            self.assertEqual(queue_tab._model.rowCount(), 1)
            self.assertEqual(history_tab._model.rowCount(), 1)
            self.assertEqual(queue_tab._proxy.rowCount(), 1)
            self.assertEqual(history_tab._proxy.rowCount(), 1)
            self.assertTrue(queue_tab._table.currentIndex().isValid())
            self.assertTrue(history_tab._table.currentIndex().isValid())
            self.assertIs(queue_tab._detail._stack.currentWidget(), queue_tab._detail._detail_page)
            self.assertIs(
                history_tab._detail._stack.currentWidget(), history_tab._detail._detail_page
            )
            self.assertEqual(queue_tab._remove_btn.text(), "Remove Selected")
            self.assertFalse(queue_tab._remove_btn.isEnabled())
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "danger-outline")
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
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "danger-outline")
            queue_tab._header.checkStateChanged.emit(Qt.CheckState.Unchecked.value)
            self.assertEqual(len(queue_tab._selected_jobs()), 0)
            self.assertEqual(queue_tab._header.check_state(), Qt.CheckState.Unchecked)
            self.assertFalse(queue_tab._remove_btn.isEnabled())
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "danger-outline")

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
            self.assertIs(
                history_tab._detail._stack.currentWidget(), history_tab._detail._empty_page
            )
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
            queue_tab._populate_context_menu(
                menu, queue_tab._focused_job(), queue_tab._selected_jobs()
            )
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
        output_root = Path(self._main_window_tmp.name) / "TV Output"
        output_root.mkdir()
        window.settings_service.tv_output_folder = str(output_root)

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=output_root / "Example Show (2024)" / "Season 01",
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            output_root=output_root,
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

        window._switch_to_tab(3)
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

        window._switch_to_tab(1)
        self._app.processEvents()

        self.assertFalse(state.queued)
        self.assertTrue(window._tv_workspace._queue_inline_btn.isEnabled())

        window.close()

    def test_completed_queue_job_projects_tv_state_back_to_plex_ready_on_tab_return(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self._reset_main_window_queue(window)
        output_root = Path(self._main_window_tmp.name) / "TV Output"
        output_root.mkdir()
        window.settings_service.tv_output_folder = str(output_root)

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=output_root / "Example Show (2024)" / "Season 01",
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            output_root=output_root,
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
        window.queue_ctrl.job_store.set_undo_data(
            job.job_id, {"renames": [], "created_dirs": [], "removed_dirs": [], "renamed_dirs": []}
        )
        job.status = JobStatus.COMPLETED

        window._switch_to_tab(3)
        self._app.processEvents()

        window._on_job_completed(job, RenameResult(renamed_count=1))
        window._on_queue_changed()

        window._switch_to_tab(1)
        self._app.processEvents()
        window._tv_workspace._roster_collapsed["fully-ready"] = False
        window._tv_workspace.refresh_from_controller()

        # The projection derives state.folder from job.output_root, which the
        # settings service resolves (validate_output_folder) — on runners whose
        # temp path contains an 8.3 short component the raw tmp path differs,
        # so the expectation must be resolved the same way.
        self.assertEqual(state.folder, output_root.resolve() / "Example Show (2024)")
        self.assertEqual(
            state.preview_items[0].original.name, "Example Show (2024) - S01E01 - Pilot.mkv"
        )
        self.assertFalse(state.preview_items[0].is_actionable)
        self._assert_roster_section_title(window._tv_workspace, 0, "FULLY READY")

        window.close()

    def test_job_status_tone_map_covers_every_status(self):
        from plex_renamer.gui_qt.widgets._job_list_tab import _JOB_STATUS_TONE

        for status in (
            JobStatus.PENDING,
            JobStatus.RUNNING,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.REVERTED,
            JobStatus.REVERT_FAILED,
        ):
            self.assertIn(status, _JOB_STATUS_TONE)

    def test_queue_table_row_height_and_no_alternation(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            tab = QueueTab(controller)
            self.assertEqual(tab._table.verticalHeader().defaultSectionSize(), _scale.px(36))
            self.assertFalse(tab._table.alternatingRowColors())
            tab.close()
            controller.close()

    def test_status_pill_paints_without_error(self):
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem

        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            store.add_job(
                RenameJob(
                    library_root="C:/library",
                    source_folder="Show",
                    media_name="Example Show",
                )
            )
            controller = QueueController(store)
            tab = QueueTab(controller)
            index = tab._proxy.index(0, 1)
            self.assertTrue(index.isValid())
            pixmap = QPixmap(200, 40)
            painter = QPainter(pixmap)
            option = QStyleOptionViewItem()
            option.rect = pixmap.rect()
            try:
                tab._hover_delegate._paint_status_pill(painter, option, index)
            finally:
                painter.end()
            tab.close()
            controller.close()

    def test_remove_and_revert_buttons_use_danger_outline(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets._queue_tab_state import remove_button_css_class
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab

        self.assertEqual(remove_button_css_class(enabled=True), "danger-outline")
        self.assertEqual(remove_button_css_class(enabled=False), "danger-outline")
        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "danger-outline")
            self.assertEqual(history_tab._revert_btn.property("cssClass"), "danger-outline")
            queue_tab.close()
            history_tab.close()
            controller.close()

    def test_revert_banner_is_a_styled_frame_between_table_and_actions(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            tab = HistoryTab(controller)
            banner = tab._revert_banner
            self.assertEqual(banner.property("cssClass"), "revert-banner")
            self.assertFalse(banner.isVisibleTo(tab))  # hidden until armed
            self.assertIs(tab._revert_info.parent(), banner)
            self.assertIs(tab._confirm_revert_btn.parent(), banner)
            self.assertIs(tab._cancel_revert_btn.parent(), banner)
            layout_index = tab._list_layout.indexOf(banner)
            actions_index = tab._list_layout.indexOf(tab._actions_bar)
            self.assertGreaterEqual(layout_index, 0)
            self.assertEqual(layout_index, actions_index - 1)  # directly above actions
            tab.close()
            controller.close()

    def test_empty_queue_table_shows_illustrated_empty_state(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            self.assertIs(queue_tab._table_stack.currentWidget(), queue_tab._table_empty)
            self.assertEqual(queue_tab._table_empty._heading.text(), "Queue is empty")
            self.assertIs(history_tab._table_stack.currentWidget(), history_tab._table_empty)
            self.assertEqual(history_tab._table_empty._heading.text(), "No history yet")
            queue_tab.close()
            history_tab.close()
            controller.close()

    def test_jobs_flip_the_stack_to_the_table_and_filters_show_no_match(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            store.add_job(
                RenameJob(
                    library_root="C:/library",
                    source_folder="Show",
                    media_name="Example Show",
                )
            )
            controller = QueueController(store)
            tab = QueueTab(controller)
            self.assertIs(tab._table_stack.currentWidget(), tab._table)
            tab._filter_control.currentTextChanged.emit("Running")
            self._app.processEvents()
            self.assertIs(tab._table_stack.currentWidget(), tab._table_empty)
            self.assertEqual(tab._table_empty._heading.text(), "No matching jobs")
            self.assertIn("Running", tab._table_empty._hint.text())
            tab.close()
            controller.close()

    def test_status_size_hint_reserves_uppercase_pill_width(self):
        from PySide6.QtWidgets import QStyleOptionViewItem, QTableView

        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.models.job_table_model import JobTableModel
        from plex_renamer.gui_qt.widgets._job_list_tab import _HoverRowDelegate
        from plex_renamer.job_store import RenameJob

        # REVERT_FAILED paints the widest pill; ResizeToContents sizes the
        # Status section from this hint, so it must reserve the uppercase
        # advance + pill padding + cell margin, not the mixed-case text.
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            status=JobStatus.REVERT_FAILED,
        )
        model = JobTableModel(history=True)
        model.set_jobs([job])
        table = QTableView()
        table.setModel(model)
        delegate = _HoverRowDelegate(table, parent=table)
        index = model.index(0, 1)
        option = QStyleOptionViewItem()
        hint = delegate.sizeHint(option, index)
        label = str(model.data(index, Qt.ItemDataRole.DisplayRole)).upper()
        required = option.fontMetrics.horizontalAdvance(label) + _scale.px(16) + _scale.px(4)
        self.assertGreaterEqual(hint.width(), required)
        table.close()


if __name__ == "__main__":
    unittest.main()
