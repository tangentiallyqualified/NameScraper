"""Batch queue submission must run off the GUI thread (RC: queue freeze).

Queueing cold shows runs per-file mkvmerge probes and TMDB metadata calls;
done synchronously on the GUI thread this froze the app for minutes-to-hours
(observed live against P:\\). These tests pin the async contract: the batch
handoff runs in a background worker while a live BusyOverlay covers the
workspace, completion is marshaled back through a Qt bridge, re-entry is
refused, and queue_selected_state's auto-check rollback still happens after
an asynchronous failure.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from conftest_qt import QtSmokeBase

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.engine import PreviewItem, ScanState

_QUEUE_ACTIONS_MODULE = "plex_renamer.gui_qt.widgets._media_workspace_queue_actions"


def _make_tv_state(name: str, tmdb_id: int) -> ScanState:
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


class QtQueueSubmissionAsyncTests(QtSmokeBase):
    def tearDown(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        self._dispose_top_level_widgets(MediaWorkspace)
        super().tearDown()

    def _build_tv_workspace(self, tmp: str, media_ctrl, queue_ctrl):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        settings = SettingsService(path=Path(tmp) / "settings.json")
        output = Path(tmp) / "tv-output"
        output.mkdir()
        settings.tv_output_folder = str(output)
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=media_ctrl,
            queue_controller=queue_ctrl,
            settings_service=settings,
        )
        workspace.resize(1200, 700)
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()
        return workspace

    def test_batch_handoff_runs_in_background_worker_under_live_overlay(self):
        """The slow add_tv_batch call must go through _submit_bg, with the
        overlay up (and the event loop free) until the worker completes."""
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        media_ctrl = _FakeMediaController()
        media_ctrl.batch_states = [_make_tv_state("Show.One.2024", 101)]
        queue_ctrl = _FakeQueueController()
        deferred: list = []
        with TemporaryDirectory() as tmp:
            workspace = self._build_tv_workspace(tmp, media_ctrl, queue_ctrl)
            fired = []
            workspace.queue_changed.connect(lambda: fired.append(True))

            with patch(
                f"{_QUEUE_ACTIONS_MODULE}._submit_bg",
                side_effect=lambda fn: deferred.append(fn),
            ):
                workspace._queue_checked()

                # Worker captured but not yet run: nothing queued, overlay up.
                self.assertFalse(queue_ctrl.called)
                self.assertEqual(len(deferred), 1)
                overlay = workspace.findChild(BusyOverlay)
                self.assertIsNotNone(overlay)
                assert overlay is not None
                self.assertTrue(overlay.isVisible())

                deferred[0]()  # the pool worker runs
                self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self.assertTrue(media_ctrl.batch_states[0].queued)
            self.assertEqual(fired, [True])
            self.assertIsNone(workspace.findChild(BusyOverlay))
            workspace.close()

    def test_second_submission_while_inflight_is_refused(self):
        class _FakeQueueController:
            def __init__(self):
                self.calls = 0

            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.calls += 1
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        media_ctrl = _FakeMediaController()
        media_ctrl.batch_states = [
            _make_tv_state("Show.One.2024", 101),
            _make_tv_state("Show.Two.2024", 102),
        ]
        queue_ctrl = _FakeQueueController()
        deferred: list = []
        with TemporaryDirectory() as tmp:
            workspace = self._build_tv_workspace(tmp, media_ctrl, queue_ctrl)
            messages: list[str] = []
            workspace.status_message.connect(lambda text, _ms: messages.append(text))

            with patch(
                f"{_QUEUE_ACTIONS_MODULE}._submit_bg",
                side_effect=lambda fn: deferred.append(fn),
            ):
                workspace._queue_checked()
                self.assertEqual(len(deferred), 1)

                workspace._queue_checked()  # second click while in flight
                self.assertEqual(len(deferred), 1)  # no second worker
                self.assertTrue(any("already" in text.lower() for text in messages))

                deferred[0]()
                self._app.processEvents()

                # Submission settled: queueing works again.
                media_ctrl.batch_states[1].queued = False
                media_ctrl.batch_states[1].checked = True
                workspace._queue_checked()
                self.assertEqual(len(deferred), 2)
            workspace.close()

    def test_progress_callback_updates_overlay_label(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay

        label_texts: list[str] = []
        workspace_holder: dict = {}

        class _FakeQueueController:
            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                if progress is not None:
                    progress("Show One", 1, 2)
                    overlay = workspace_holder["ws"].findChild(BusyOverlay)
                    if overlay is not None:
                        label_texts.append(overlay._label.text())
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        media_ctrl = _FakeMediaController()
        media_ctrl.batch_states = [
            _make_tv_state("Show.One.2024", 101),
            _make_tv_state("Show.Two.2024", 102),
        ]
        queue_ctrl = _FakeQueueController()
        with TemporaryDirectory() as tmp:
            workspace = self._build_tv_workspace(tmp, media_ctrl, queue_ctrl)
            workspace_holder["ws"] = workspace

            # Synchronous worker: progress emits land inline on the GUI thread.
            with patch(
                f"{_QUEUE_ACTIONS_MODULE}._submit_bg",
                side_effect=lambda fn: fn(),
            ):
                workspace._queue_checked()

            self.assertEqual(label_texts, ["Queueing Show One (1/2)…"])
            workspace.close()

    def test_auto_check_rolls_back_after_async_queue_failure(self):
        """round5 5a rollback survives the async flow: the auto-checked flag
        and check_vars bindings unwind when the deferred worker fails."""
        from plex_renamer.gui_qt.widgets._media_workspace_queue_actions import (
            queue_selected_state,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _ExplodingQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                raise RuntimeError("queue boom")

        class _MovieMediaController(_FakeMediaController):
            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

        class _FakeWarningBox:
            calls: list = []

            @staticmethod
            def warning(parent, title, text):
                _FakeWarningBox.calls.append((title, text))

        _FakeWarningBox.calls = []
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
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        media_ctrl = _MovieMediaController()
        media_ctrl.movie_library_states = [state]
        queue_ctrl = _ExplodingQueueController()
        deferred: list = []
        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "movie-output"
            output.mkdir()
            settings.movie_output_folder = str(output)
            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()
            self.assertFalse(state.checked)

            with patch(
                f"{_QUEUE_ACTIONS_MODULE}._submit_bg",
                side_effect=lambda fn: deferred.append(fn),
            ):
                queue_selected_state(workspace, warning_box=_FakeWarningBox)

                # In flight: auto-check applied, not yet rolled back.
                self.assertEqual(len(deferred), 1)
                self.assertTrue(state.checked)

                deferred[0]()
                self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self.assertEqual(len(_FakeWarningBox.calls), 1)
            self.assertEqual(_FakeWarningBox.calls[0][0], "Queue Failed")
            self.assertFalse(state.checked)
            self.assertFalse(state.queued)
            self.assertEqual(
                {key: binding.get() for key, binding in state.check_vars.items()},
                {"0": False},
            )
            workspace.close()
