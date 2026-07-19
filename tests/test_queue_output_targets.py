"""Regression tests for output-root targeting of queued TV jobs.

Bug: after a manual rematch + single-show rescan, preview items kept
``target_dir`` under the SOURCE folder. Queue build then stored an absolute
source path in ``target_dir_relative`` and execution failed with
"Target path is outside the output root".
"""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._queue_bridge import build_rename_job_from_state
from plex_renamer.engine.models import PreviewItem, ScanState

SHOW_INFO = {"id": 42, "name": "Demo Show", "year": "2020", "poster_path": None}


def _make_state(tmp_path: Path) -> tuple[ScanState, Path, Path]:
    library_root = tmp_path / "library"
    source = library_root / "Demo.Show.S01.2160p"
    source.mkdir(parents=True)
    output_root = tmp_path / "output"
    output_root.mkdir()

    original = source / "Demo.Show.S01E01.mkv"
    original.touch()
    item = PreviewItem(
        original=original,
        new_name="Demo Show (2020) - S01E01 - Pilot.mkv",
        # Stale target under the SOURCE folder (never retargeted to output).
        target_dir=source / "Season 01",
        season=1,
        episodes=[1],
        status="OK",
    )
    state = ScanState(folder=source, media_info=SHOW_INFO)
    state.preview_items = [item]
    state.scanned = True
    return state, library_root, output_root


class TestQueueBuildTargetFallback:
    def test_source_rooted_target_dir_is_rebuilt_under_output_root(self, tmp_path):
        state, library_root, output_root = _make_state(tmp_path)
        job = build_rename_job_from_state(
            state,
            library_root,
            output_root,
            show_folder_rename="Demo Show (2020)",
            checked_indices={0},
        )
        op = job.rename_ops[0]
        assert not Path(op.target_dir_relative).is_absolute()
        assert op.target_dir_relative.replace("\\", "/") == "Demo Show (2020)/Season 01"

    def test_target_already_under_output_root_is_kept(self, tmp_path):
        state, library_root, output_root = _make_state(tmp_path)
        state.preview_items[0].target_dir = output_root / "Demo Show (2020)" / "Season 01"
        job = build_rename_job_from_state(
            state,
            library_root,
            output_root,
            show_folder_rename="Demo Show (2020)",
            checked_indices={0},
        )
        op = job.rename_ops[0]
        assert op.target_dir_relative.replace("\\", "/") == "Demo Show (2020)/Season 01"


class TestSingleShowScanRetarget:
    def test_single_show_scan_retargets_items_to_output_root(self, tmp_path, monkeypatch):
        from plex_renamer.app.controllers import _single_show_scan_helpers as helpers

        state, _library_root, output_root = _make_state(tmp_path)
        state.scanned = False

        class _Settings:
            valid_tv_output_folder = output_root

        class _Controller:
            _batch_orchestrator = None
            _batch_states = [state]
            _settings = _Settings()

            @property
            def library_states(self):
                return self._batch_states

            def _set_progress(self, *args, **kwargs):
                pass

            def _notify(self, *args, **kwargs):
                pass

            def refresh_episode_guide(self, target):
                pass

        def _fake_run_scan(target, tmdb, scanner_factory, duplicate_checker):
            target.scanned = True

        monkeypatch.setattr(helpers, "ensure_tv_scanner", lambda *a, **k: None)
        monkeypatch.setattr(helpers, "run_tv_scan", _fake_run_scan)
        monkeypatch.setattr(helpers, "_submit_bg", lambda fn: fn())

        helpers.start_single_show_scan(
            _Controller(),
            state,
            tmdb=None,
            scanner_factory=None,
            duplicate_checker=None,
        )

        target_dir = state.preview_items[0].target_dir
        assert target_dir is not None
        assert target_dir == output_root.resolve() / "Demo Show (2020)" / "Season 01"
