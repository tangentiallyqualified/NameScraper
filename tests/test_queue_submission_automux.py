"""Queue submission ensures and bakes mux plans into REMUX jobs."""
from pathlib import Path
from types import SimpleNamespace

from plex_renamer._mkv_probe import MediaTrack, ProbeResult
from plex_renamer.app.controllers._queue_submission_helpers import (
    add_movie_batch_jobs,
    add_tv_batch_jobs,
)
from plex_renamer.app.services import automux_service as svc_mod
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobKind
from plex_renamer.engine.models import CompanionFile, PreviewItem, ScanState


class _FakeStore:
    def __init__(self):
        self.jobs = []

    def add_job(self, job):
        self.jobs.append(job)
        return job


class _Eligibility:
    enabled = True
    reason = ""
    command_state = SimpleNamespace(value="enabled")

    def __init__(self, indices):
        self.selected_indices = indices


class _Gating:
    def evaluate_scan_state(self, state, **kwargs):
        return _Eligibility(set(range(len(state.preview_items))))

    def is_actionable_item(self, item):
        return True


def _settings(tmp_path):
    svc = SettingsService(tmp_path / "settings.json")
    svc.automux_merge_subs = True
    svc.automux_merge_sub_languages = ["eng"]
    exe = tmp_path / "mkvmerge.exe"
    exe.write_bytes(b"")
    svc.mkvmerge_path = str(exe)
    return svc


def _probe_ok():
    return ProbeResult(path="a.mkv", ok=True, tracks=[
        MediaTrack(track_id=0, track_type="video", codec="h264",
                   language="und", name="", is_default=True, is_forced=False),
        MediaTrack(track_id=1, track_type="audio", codec="aac",
                   language="eng", name="", is_default=True, is_forced=False),
    ])


def _tv_state(tmp_path):
    lib = tmp_path / "lib"
    item = PreviewItem(
        original=lib / "Show" / "a.mkv",
        new_name="Show - S01E01 - Pilot.mkv",
        target_dir=tmp_path / "out" / "Show (2020)" / "Season 01",
        season=1, episodes=[1], status="OK", media_type="tv",
        companions=[CompanionFile(
            original=lib / "Show" / "a.eng.srt",
            new_name="Show - S01E01 - Pilot.eng.srt",
            file_type="subtitle")],
    )
    return ScanState(
        folder=lib / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[item], scanned=True, checked=True,
        relative_folder="Show",
    )


def test_tv_batch_bakes_remux_job(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path: _probe_ok())
    store = _FakeStore()
    result = add_tv_batch_jobs(
        store,
        states=[_tv_state(tmp_path)],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )
    assert result.added == 1
    job = store.jobs[0]
    assert job.job_kind == JobKind.REMUX
    assert job.rename_ops[0].mux is not None
    # The merged companion is consumed by the mux — no rename op for it.
    originals = [op.original_relative for op in job.rename_ops]
    assert str(Path("Show/a.eng.srt")) not in originals


def test_tv_batch_without_settings_stays_rename(tmp_path):
    store = _FakeStore()
    result = add_tv_batch_jobs(
        store,
        states=[_tv_state(tmp_path)],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
    )
    assert result.added == 1
    assert store.jobs[0].job_kind == JobKind.RENAME


def test_disabled_state_stays_rename(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path: _probe_ok())
    state = _tv_state(tmp_path)
    state.automux_disabled = True
    store = _FakeStore()
    add_tv_batch_jobs(
        store, states=[state],
        library_root=tmp_path / "lib", output_root=tmp_path / "out",
        command_gating=_Gating(), settings_service=_settings(tmp_path),
    )
    assert store.jobs[0].job_kind == JobKind.RENAME


def test_movie_batch_bakes_remux_job(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path: _probe_ok())
    lib = tmp_path / "lib"
    item = PreviewItem(
        original=lib / "Movie" / "m.mkv",
        new_name="Movie (2020).mkv",
        target_dir=tmp_path / "out" / "Movie (2020)",
        season=None, episodes=[], status="OK", media_type="movie",
        companions=[CompanionFile(
            original=lib / "Movie" / "m.eng.srt",
            new_name="Movie (2020).eng.srt",
            file_type="subtitle")],
    )
    state = ScanState(
        folder=lib / "Movie",
        media_info={"id": 9, "title": "Movie", "year": "2020"},
        preview_items=[item], scanned=True, checked=True,
    )
    store = _FakeStore()
    result = add_movie_batch_jobs(
        store, states=[state],
        library_root=lib, output_root=tmp_path / "out",
        command_gating=_Gating(), settings_service=_settings(tmp_path),
    )
    assert result.added == 1
    assert store.jobs[0].job_kind == JobKind.REMUX
