# pyright: strict
"""Scan-show regression tests for MediaController."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from plex_renamer.app.models import ScanLifecycle
from plex_renamer.engine import PreviewItem, ScanState
from plex_renamer.providers import SeasonMapUnavailableError
from tests.test_media_controller import ControllerTestCase, FakeTMDB, wait_until


class ScanShowRegressionTests(ControllerTestCase):
    def _assert_scan_failure(self, error: Exception, expected_scan_error: str) -> None:
        folder = self.tmp / "Failed Show"
        folder.mkdir()
        stale_item = PreviewItem(
            original=folder / "Failed.Show.S01E01.mkv",
            new_name="Failed Show - S01E01.mkv",
            target_dir=folder,
            season=1,
            episodes=[1],
            status="OK",
        )
        state = ScanState(
            folder=folder,
            media_info={"id": 7, "name": "Failed Show", "year": "2024"},
            preview_items=[stale_item],
            scanned=True,
            checked=True,
            scan_error="stale error",
        )
        completed: list[ScanState | None] = []

        class _FailingScanner:
            def __init__(
                self,
                tmdb: Any,
                show_info: dict[str, Any],
                root_folder: Path,
                *,
                season_hint: int | None = None,
                season_folders: dict[int, Path] | None = None,
            ) -> None:
                self.show_info = show_info

            def scan(self) -> tuple[list[PreviewItem], bool]:
                raise error

        self.set_tv_session([state], batch_mode=True)
        self.ctrl.add_listener(on_scan_complete=lambda result: completed.append(result))

        with (
            patch("plex_renamer.app.controllers.media_controller.TVScanner", _FailingScanner),
            patch.object(self.ctrl, "refresh_episode_guide") as refresh_episode_guide,
        ):
            self.ctrl.scan_show(state, FakeTMDB())
            wait_until(lambda: bool(completed), description="failed single-show scan to finish")

        refresh_episode_guide.assert_not_called()
        self.assertIs(completed[-1], state)
        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.FAILED)
        self.assertEqual(state.scan_error, expected_scan_error)
        self.assertEqual(state.preview_items, [])
        self.assertFalse(state.scanned)
        self.assertFalse(state.checked)
        self.assertFalse(state.scanning)
        self.assertIsNone(state.scanner)

    def test_single_show_typed_failure_clears_stale_state_and_reports_failed(self) -> None:
        self._assert_scan_failure(
            SeasonMapUnavailableError("tmdb season map unavailable for 7"),
            "Episode guide is unavailable; retry the provider scan.",
        )

    def test_single_show_generic_failure_clears_stale_state_and_reports_failed(self) -> None:
        self._assert_scan_failure(
            RuntimeError("single scanner exploded"), "single scanner exploded"
        )

    def test_scan_show_uses_preserved_single_show_season_hint_after_rematch(self):
        folder = self.tmp / "Yuru Camp Specials"
        folder.mkdir()
        state = self.ctrl.accept_tv_show(  # pyright: ignore[reportUnknownMemberType]
            folder,
            FakeTMDB(),
            {"id": 101, "name": "Yuru Camp", "year": "2018"},
        )
        created: dict[str, object] = {}

        class _FakeScanner:
            def __init__(
                self,
                tmdb: Any,
                show_info: dict[str, Any],
                root_folder: Path,
                *,
                season_hint: int | None = None,
                season_folders: dict[int, Path] | None = None,
            ) -> None:
                created["tmdb"] = tmdb
                created["show_info"] = show_info
                created["root_folder"] = root_folder
                created["season_hint"] = season_hint
                created["season_folders"] = season_folders

            def scan(self) -> tuple[list[PreviewItem], bool]:
                created["scan_called"] = True
                return ([], False)

            def get_completeness(self, items: list[PreviewItem], checked_indices: set[int]) -> None:
                created["checked_indices"] = checked_indices

        self.ctrl.rematch_tv_state(  # pyright: ignore[reportUnknownMemberType]
            state, {"id": 202, "name": "Yuru Camp", "year": "2018"}
        )

        with patch("plex_renamer.app.controllers.media_controller.TVScanner", _FakeScanner):
            self.ctrl.scan_show(state, FakeTMDB())

        wait_until(
            lambda: state.scanned and self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="single-show rematch rescan to finish",
        )

        self.assertTrue(created.get("scan_called"))
        self.assertEqual(created.get("season_hint"), 0)
        self.assertIsNone(created.get("season_folders"))
        self.assertEqual(created.get("root_folder"), folder)
        self.assertEqual(created.get("checked_indices"), set())

    def test_scan_show_uses_batch_scan_inputs_for_rematched_tv_state(self):
        state = ScanState(
            folder=self.tmp / "Merged.Show",
            media_info={"id": 11, "name": "Merged Show", "year": "2024"},
            scanned=False,
            season_assignment=2,
            season_folders={2: self.tmp / "Merged.Show" / "Season 02"},
        )
        created: dict[str, object] = {}

        class _FakeScanner:
            def __init__(
                self,
                tmdb: Any,
                show_info: dict[str, Any],
                root_folder: Path,
                *,
                season_hint: int | None = None,
                season_folders: dict[int, Path] | None = None,
            ) -> None:
                created["tmdb"] = tmdb
                created["show_info"] = show_info
                created["root_folder"] = root_folder
                created["season_hint"] = season_hint
                created["season_folders"] = season_folders

            def scan(self) -> tuple[list[PreviewItem], bool]:
                created["scan_called"] = True
                return ([], True)

            def scan_consolidated(self) -> list[PreviewItem]:
                created["scan_consolidated_called"] = True
                return [
                    PreviewItem(
                        original=state.folder / "Season 02" / "Merged.Show.S02E01.mkv",
                        new_name="Merged Show (2024) - S02E01 - Pilot.mkv",
                        target_dir=state.folder / "Season 02",
                        season=2,
                        episodes=[1],
                        status="OK",
                    )
                ]

            def get_completeness(self, items: list[PreviewItem], checked_indices: set[int]) -> None:
                created["checked_indices"] = checked_indices

        self.set_tv_session([state], batch_mode=True)

        with patch("plex_renamer.app.controllers.media_controller.TVScanner", _FakeScanner):
            self.ctrl.scan_show(state, FakeTMDB())

        wait_until(
            lambda: state.scanned and self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="rematched TV state to finish scanning",
        )

        self.assertTrue(created.get("scan_called"))
        self.assertTrue(created.get("scan_consolidated_called"))
        self.assertEqual(created.get("season_hint"), 2)
        self.assertEqual(created.get("season_folders"), state.season_folders)
        self.assertEqual(created.get("checked_indices"), {0})
        self.assertEqual(len(state.preview_items), 1)
        self.assertEqual(state.preview_items[0].new_name, "Merged Show (2024) - S02E01 - Pilot.mkv")
