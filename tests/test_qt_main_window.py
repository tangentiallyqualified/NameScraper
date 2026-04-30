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


class QtMainWindowTests(QtSmokeBase):
    def test_main_window_instantiates(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self.assertEqual(window.windowTitle(), "Plex Renamer")
        self.assertEqual(window.centralWidget().__class__.__name__, "QTabWidget")
        self.assertEqual(window.centralWidget().currentIndex(), 0)
        self.assertEqual(window.centralWidget().tabText(0), "Settings")
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
        self.assertEqual(window.centralWidget().currentIndex(), 4)
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
        self.assertEqual(window.centralWidget().currentIndex(), 4)

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

        self.assertEqual(
            [window._tabs.tabText(index) for index in range(window._tabs.count())],
            ["Settings", "TV Shows", "Movies", "Queue", "History"],
        )
        self.assertEqual(window._queue_badge.count_text(), "1")
        self.assertTrue(window._queue_badge.failure_visible())
        self.assertEqual(window._history_badge.count_text(), "2")
        window.close()

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

    def test_settings_tab_has_independent_episode_threshold_slider(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            settings.auto_accept_threshold = 0.60
            settings.episode_auto_accept_threshold = 0.85
            emitted: list[float] = []

            tab = SettingsTab(settings_service=settings)
            tab.episode_threshold_changed.connect(emitted.append)

            self.assertEqual(tab._threshold_slider.value(), 60)
            self.assertEqual(tab._episode_threshold_slider.value(), 85)

            tab._episode_threshold_slider.setValue(72)

            self.assertAlmostEqual(settings.auto_accept_threshold, 0.60)
            self.assertAlmostEqual(settings.episode_auto_accept_threshold, 0.72)
            self.assertEqual(tab._episode_threshold_label.text(), "0.72")
            self.assertEqual(emitted[-1], 0.72)

            tab.close()

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
        window._switch_to_tab(1)

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

    def test_main_window_skips_startup_job_poster_backfill_when_no_jobs_exist(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        with patch("plex_renamer.gui_qt.main_window.QTimer.singleShot") as single_shot:
            window = MainWindow()

        single_shot.assert_not_called()
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

            future = window._start_job_poster_backfill()
            if future is not None:
                future.result(timeout=1)
            for _ in range(20):
                self._app.processEvents()
                if window._refresh_job_views.call_count:
                    break
                QTest.qWait(10)

        window.queue_ctrl.backfill_missing_job_poster_paths.assert_called_once_with(tmdb)
        window._refresh_job_views.assert_called_once()
        window.close()

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
