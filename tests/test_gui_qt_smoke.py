from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobStatus
from plex_renamer.engine import CompanionFile, PreviewItem, ScanState


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class QtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

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
        self.assertEqual(window._toast_manager.toast_count(), 1)

        window._history_tab.select_job = MagicMock()
        window._on_job_failed(job, "permission denied")
        self.assertEqual(window._toast_manager.toast_count(), 2)

        window._show_history_job(job.job_id)
        window._history_tab.select_job.assert_called_once_with(job.job_id)
        self.assertEqual(window.centralWidget().currentIndex(), 3)

        window._on_queue_finished()
        self.assertGreaterEqual(window._toast_manager.toast_count(), 3)
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

        tmdb.fetch_image.assert_called_once_with("/poster.jpg", target_width=96)
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
        tmdb.fetch_image.assert_called_once_with("/poster.jpg", target_width=96)
        self.assertEqual(job.poster_path, "/poster.jpg")
        self.assertEqual(persisted, [(job.job_id, "/poster.jpg")])
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

    def test_settings_tab_async_api_key_test_updates_ui_via_bridge(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab()
        tab._api_key_input.setText("test-key")

        with patch("requests.get", return_value=MagicMock(ok=True, status_code=200)) as get_mock:
            tab._on_test_key()
            self._app.processEvents()
            QTest.qWait(25)
            self._app.processEvents()

        get_mock.assert_called_once()
        self.assertTrue(tab._test_key_btn.isEnabled())
        self.assertEqual(tab._key_status.text(), "TMDB connection successful.")
        self.assertEqual(tab._clear_cache_btn.text(), "Clear TMDB Cache")
        self.assertEqual(tab._clear_all_btn.text(), "Clear All Data")
        tab.close()

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

    def test_main_window_restores_tmdb_snapshot_when_client_is_created(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        with patch("plex_renamer.gui_qt.main_window.QTimer.singleShot"):
            window = MainWindow()
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

            history_tab._revert_selected()

            self.assertFalse(history_tab._revert_banner.isHidden())
            self.assertIn("move 2 files", history_tab._revert_banner_label.text())

            history_tab._confirm_revert()

            queue_ctrl.revert_job.assert_called_once_with(job.job_id)
            self.assertTrue(history_tab._revert_banner.isHidden())
            history_tab.close()
            store.close()

    def test_queue_and_history_tabs_refresh(self):
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

            self.assertEqual(queue_tab._model.rowCount(), 1)
            self.assertEqual(history_tab._model.rowCount(), 1)
            self.assertEqual(queue_tab._proxy.rowCount(), 1)
            self.assertEqual(history_tab._proxy.rowCount(), 1)

            queue_tab._filter_control.setCurrentText("Running")
            self.assertEqual(queue_tab._proxy.rowCount(), 0)
            queue_tab._filter_control.setCurrentText("Pending")
            self.assertEqual(queue_tab._proxy.rowCount(), 1)

            history_tab._filter_control.setCurrentText("Failed")
            self.assertEqual(history_tab._proxy.rowCount(), 0)
            history_tab._filter_control.setCurrentText("Completed")
            self.assertEqual(history_tab._proxy.rowCount(), 1)

            queue_tab._select_all()
            self.assertEqual(len(queue_tab._table.selectionModel().selectedRows()), 1)
            queue_tab._clear_selection()
            self.assertEqual(len(queue_tab._table.selectionModel().selectedRows()), 0)

            history_tab._select_all()
            self.assertEqual(len(history_tab._table.selectionModel().selectedRows()), 1)
            history_tab._clear_selection()
            self.assertEqual(len(history_tab._table.selectionModel().selectedRows()), 0)

            queue_tab.close()
            history_tab.close()
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
            self.assertEqual(workspace._roster_list.item(0).text(), "MATCHED")
            self.assertIsNone(workspace._roster_list.item(1).data(Qt.ItemDataRole.CheckStateRole))
            self.assertIsNone(workspace._preview_list.item(0).data(Qt.ItemDataRole.CheckStateRole))
            self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())
            self.assertIn("2024", workspace._folder_plan_label.text())
            self.assertGreater(workspace._preview_list.count(), 0)

            workspace._queue_checked()
            self.assertTrue(queue_ctrl.called)

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

            preview_widget = workspace._preview_list.itemWidget(workspace._preview_list.item(0))
            self.assertIsNotNone(preview_widget)
            self.assertEqual(preview_widget._target.text(), "-> Arrival (2016).mkv")

            settings.view_mode = "compact"
            settings.show_companion_files = True
            workspace.apply_settings()

            preview_widget = workspace._preview_list.itemWidget(workspace._preview_list.item(0))
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
            self.assertIsNotNone(row_widget._alternates_layout)
            self.assertEqual(row_widget._alternates_layout.count(), 2)
            self.assertFalse(row_widget._check.isWindow())
            self.assertEqual(row_widget.styleSheet(), "")
            self.assertEqual(row_widget.property("band"), "low")
            self.assertEqual(row_widget.property("selectionState"), "selected")
            self.assertEqual(row_widget._status.styleSheet(), "")
            self.assertEqual(row_widget._status.property("tone"), "accent")

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

            self.assertEqual(workspace._roster_list.item(0).text(), "MATCHED")
            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertEqual(row_widget._status.text(), "MATCHED")

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


if __name__ == "__main__":
    unittest.main()