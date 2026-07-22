"""Main-window completion behavior for a failed single-show scan."""

# pyright: strict

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from conftest_qt import QtSmokeBase

from plex_renamer.app.models import ScanLifecycle
from plex_renamer.engine import ScanState
from plex_renamer.gui_qt.main_window import MainWindow


class QtScanFailureCompletionTests(QtSmokeBase):
    def test_main_window_does_not_retry_or_mask_failed_single_show_scan(self) -> None:
        window = cast(Any, MainWindow())
        failed_state = ScanState(
            folder=Path("C:/library/tv/Failed.Show.2024"),
            media_info={"id": 7, "name": "Failed Show", "year": "2024"},
            scanned=False,
            checked=False,
            scan_error="Episode guide is unavailable; retry the provider scan.",
        )
        window.media_ctrl._active_content_mode = "tv"
        window.media_ctrl._active_library_mode = "tv"
        window.media_ctrl._batch_mode = True
        window.media_ctrl._batch_states = [failed_state]
        window.media_ctrl._scan_progress = window.media_ctrl.scan_progress.__class__(
            lifecycle=ScanLifecycle.FAILED,
            phase="TV scan failed",
            message="TV scan failed: Episode guide is unavailable; retry the provider scan.",
        )
        window._tv_workspace.show_ready_when_posters_warm = MagicMock()
        window.media_ctrl.scan_all_shows = MagicMock()

        window._on_scan_complete()
        self._app.processEvents()

        window.media_ctrl.scan_all_shows.assert_not_called()
        window._tv_workspace.show_ready_when_posters_warm.assert_called_once_with()
        self.assertEqual(window._toast_manager.toast_count(), 1)
        toast = window._toast_manager._layout.itemAt(0).widget()
        self.assertEqual(toast._title_label.text(), "Scan failed")
        self.assertIn("episode guide is unavailable", toast._message_label.text().lower())
        self.assertEqual(window.media_ctrl.scan_progress.lifecycle, ScanLifecycle.FAILED)
        window.close()
