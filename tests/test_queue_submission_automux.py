"""Queue submission ensures and bakes mux plans into REMUX jobs."""

from pathlib import Path
from types import SimpleNamespace

from plex_renamer._mkv_probe import MediaTrack, ProbeResult
from plex_renamer.app.controllers._queue_submission_helpers import (
    add_movie_batch_jobs,
    add_tv_batch_jobs,
)
from plex_renamer.app.services import automux_service as svc_mod
from plex_renamer.app.services.command_gating_service import CommandGatingService
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
    return ProbeResult(
        path="a.mkv",
        ok=True,
        tracks=[
            MediaTrack(
                track_id=0,
                track_type="video",
                codec="h264",
                language="und",
                name="",
                is_default=True,
                is_forced=False,
            ),
            MediaTrack(
                track_id=1,
                track_type="audio",
                codec="aac",
                language="eng",
                name="",
                is_default=True,
                is_forced=False,
            ),
        ],
    )


def _tv_state(tmp_path):
    lib = tmp_path / "lib"
    item = PreviewItem(
        original=lib / "Show" / "a.mkv",
        new_name="Show - S01E01 - Pilot.mkv",
        target_dir=tmp_path / "out" / "Show (2020)" / "Season 01",
        season=1,
        episodes=[1],
        status="OK",
        media_type="tv",
        companions=[
            CompanionFile(
                original=lib / "Show" / "a.eng.srt",
                new_name="Show - S01E01 - Pilot.eng.srt",
                file_type="subtitle",
            )
        ],
    )
    return ScanState(
        folder=lib / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[item],
        scanned=True,
        checked=True,
        relative_folder="Show",
    )


def _tv_state_two(tmp_path):
    """Two actionable episodes, each with a mergeable subtitle companion."""
    lib = tmp_path / "lib"

    def _item(name: str, ep: int) -> PreviewItem:
        return PreviewItem(
            original=lib / "Show" / f"{name}.mkv",
            new_name=f"Show - S01E0{ep} - Ep.mkv",
            target_dir=tmp_path / "out" / "Show (2020)" / "Season 01",
            season=1,
            episodes=[ep],
            status="OK",
            media_type="tv",
            companions=[
                CompanionFile(
                    original=lib / "Show" / f"{name}.eng.srt",
                    new_name=f"Show - S01E0{ep} - Ep.eng.srt",
                    file_type="subtitle",
                )
            ],
        )

    return ScanState(
        folder=lib / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[_item("a", 1), _item("b", 2)],
        scanned=True,
        checked=True,
        relative_folder="Show",
    )


def test_per_episode_optout_excludes_only_that_file(tmp_path, monkeypatch):
    """Spec §4b end-to-end: with plans for {0, 1} and mux_opt_outs={0}, the
    baked job muxes index 1's file and leaves index 0 on a plain rename op."""
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state_two(tmp_path)
    state.mux_opt_outs = {0}
    store = _FakeStore()

    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )

    assert result.added == 1
    job = store.jobs[0]
    assert job.job_kind == JobKind.REMUX  # index 1 still muxes
    video_ops = {op.original_relative: op for op in job.rename_ops if op.file_type == "video"}
    a_rel = str(Path("Show/a.mkv"))
    b_rel = str(Path("Show/b.mkv"))
    assert video_ops[a_rel].mux is None  # opted out -> plain rename
    assert video_ops[b_rel].mux is not None  # still muxed
    # The opted-out episode's subtitle is NOT consumed by a mux, so it keeps
    # its own rename op; the muxed one's subtitle is merged away.
    originals = [op.original_relative for op in job.rename_ops]
    assert str(Path("Show/a.eng.srt")) in originals
    assert str(Path("Show/b.eng.srt")) not in originals


def test_tv_batch_bakes_remux_job(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
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
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state(tmp_path)
    state.automux_disabled = True
    store = _FakeStore()
    add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )
    assert store.jobs[0].job_kind == JobKind.RENAME


def _settings_automux_off(tmp_path):
    """mkvmerge resolves, but every AutoMux action toggle is off — merge
    planning is toggle-independent (spec §5) and must still fire."""
    svc = SettingsService(tmp_path / "settings-off.json")
    exe = tmp_path / "mkvmerge.exe"
    if not exe.exists():
        exe.write_bytes(b"")
    svc.mkvmerge_path = str(exe)
    return svc


def _tv_state_merge_row(tmp_path):
    """A single group row: three parts merging into one episode."""
    lib = tmp_path / "lib"
    parts = [lib / "Show" / f"Show S01E05 ({i}).mkv" for i in (1, 2, 3)]
    for part in parts:
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"0")
    item = PreviewItem(
        original=parts[0],
        new_name="Show - S01E05 - Five.mkv",
        target_dir=tmp_path / "out" / "Show (2020)" / "Season 01",
        season=1,
        episodes=[5],
        status="OK",
        media_type="tv",
        merge_part_paths=list(parts),
        merge_part_file_ids=[0, 1, 2],
    )
    return ScanState(
        folder=lib / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[item],
        scanned=True,
        checked=True,
        relative_folder="Show",
    )


def test_tv_batch_merge_row_bakes_remux_job_with_automux_off(tmp_path, monkeypatch):
    """A merge row's append plan must reach the queued job even when the
    global AutoMux toggle is off — merge is toggle-independent (spec §5)
    and must not be gated behind automux_active() at queue-submission
    time."""
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state_merge_row(tmp_path)
    settings = _settings_automux_off(tmp_path)
    assert svc_mod.automux_active(settings) is False  # sanity: toggle is off

    store = _FakeStore()
    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=settings,
    )

    assert result.added == 1
    job = store.jobs[0]
    assert job.job_kind == JobKind.REMUX
    video_ops = [op for op in job.rename_ops if op.file_type == "video"]
    assert len(video_ops) == 1
    op = video_ops[0]
    assert op.mux is not None
    assert op.mux["append_sources"] == [
        str(Path("Show/Show S01E05 (2).mkv")),
        str(Path("Show/Show S01E05 (3).mkv")),
    ]


def test_tv_batch_merge_row_survives_automux_disabled(tmp_path, monkeypatch):
    """A per-show AutoMux opt-out (state.automux_disabled) suppresses
    track-edit plans but must not drop an approved merge row's append plan
    -- the merge itself is not an optional AutoMux action once the user
    approved the merged group row."""
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state_merge_row(tmp_path)
    state.automux_disabled = True

    store = _FakeStore()
    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )

    assert result.added == 1
    job = store.jobs[0]
    assert job.job_kind == JobKind.REMUX
    video_ops = [op for op in job.rename_ops if op.file_type == "video"]
    assert len(video_ops) == 1
    op = video_ops[0]
    assert op.mux is not None
    assert op.mux["append_sources"] == [
        str(Path("Show/Show S01E05 (2).mkv")),
        str(Path("Show/Show S01E05 (3).mkv")),
    ]


def _tv_state_correctly_named(tmp_path):
    """Single item whose name is already correct (is_actionable False) but
    which still has a subtitle companion eligible for an AutoMux merge."""
    lib = tmp_path / "lib"
    item = PreviewItem(
        original=lib / "Show" / "Show - S01E01 - Pilot.mkv",
        new_name="Show - S01E01 - Pilot.mkv",
        target_dir=lib / "Show",
        season=1,
        episodes=[1],
        status="OK",
        media_type="tv",
        companions=[
            CompanionFile(
                original=lib / "Show" / "Show - S01E01 - Pilot.eng.srt",
                new_name="Show - S01E01 - Pilot.eng.srt",
                file_type="subtitle",
            )
        ],
    )
    state = ScanState(
        folder=lib / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[item],
        scanned=True,
        checked=True,
        relative_folder="Show",
    )
    state.check_vars = {"0": SimpleNamespace(get=lambda: True)}
    return state


def test_mux_only_op_for_correctly_named_file(tmp_path, monkeypatch):
    """A correctly-named file (is_actionable False) with an action-bearing
    mux plan must still be baked into the job as a mux-only op."""
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state_correctly_named(tmp_path)
    store = _FakeStore()

    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )

    assert result.added == 1
    job = store.jobs[0]
    assert job.job_kind == JobKind.REMUX
    video_ops = [op for op in job.rename_ops if op.file_type == "video"]
    assert len(video_ops) == 1
    op = video_ops[0]
    assert op.new_name == "Show - S01E01 - Pilot.mkv"
    assert op.mux is not None


def test_mux_only_file_optout_produces_no_op(tmp_path, monkeypatch):
    """Opting out of the mux for a correctly-named file must leave it with
    no op at all — there is nothing left to bake (no rename, no mux)."""
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state_correctly_named(tmp_path)
    state.mux_opt_outs = {0}
    store = _FakeStore()

    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )

    assert result.added == 1
    job = store.jobs[0]
    video_rel = str(Path("Show/Show - S01E01 - Pilot.mkv"))
    sub_rel = str(Path("Show/Show - S01E01 - Pilot.eng.srt"))
    originals = [op.original_relative for op in job.rename_ops]
    assert video_rel not in originals
    assert sub_rel not in originals


def test_ensure_state_plans_probes_correctly_named_items(tmp_path):
    """ensure_state_plans must widen its probing to correctly-named (OK)
    items, not just state.actionable_indices, so mux-only plans exist."""
    state = _tv_state_correctly_named(tmp_path)
    svc = _settings(tmp_path)
    probed_paths = []

    def fake_prober(mkv, path, **kwargs):
        probed_paths.append(path)
        return _probe_ok()

    svc_mod.ensure_state_plans(state, svc, tmp_path / "lib", prober=fake_prober)

    assert state.preview_items[0].original in probed_paths


def test_get_checked_indices_includes_mux_active_items(tmp_path):
    """Direct unit test of the widened get_checked_indices_from_state:
    a checked actionable item (0) and a checked mux-active-but-correctly-
    named item (1) are included; a checked correctly-named item with no
    plan (2) and an unchecked mux-active item (3) are not."""
    from plex_renamer.engine._queue_bridge import get_checked_indices_from_state

    lib = tmp_path / "lib"

    def _actionable(name: str, ep: int) -> PreviewItem:
        return PreviewItem(
            original=lib / "Show" / f"{name}.mkv",
            new_name=f"Show - S01E0{ep} - Ep.mkv",
            target_dir=lib / "Show",
            season=1,
            episodes=[ep],
            status="OK",
            media_type="tv",
        )

    def _correct(ep: int) -> PreviewItem:
        # new_name == original.name, target_dir == parent -> not actionable
        return PreviewItem(
            original=lib / "Show" / f"Show - S01E0{ep} - Ep.mkv",
            new_name=f"Show - S01E0{ep} - Ep.mkv",
            target_dir=lib / "Show",
            season=1,
            episodes=[ep],
            status="OK",
            media_type="tv",
        )

    action_plan = {"subtitle_merges": [{"action": "merge", "source_relative": "Show/x.eng.srt"}]}
    state = ScanState(
        folder=lib / "Show",
        media_info={"id": 7, "name": "Show", "year": "2020"},
        preview_items=[
            _actionable("a", 1),  # 0: checked + actionable -> in
            _correct(2),  # 1: checked + mux-active -> in
            _correct(3),  # 2: checked, no plan -> out
            _correct(4),  # 3: mux-active but UNCHECKED -> out
        ],
        scanned=True,
        checked=True,
        relative_folder="Show",
    )
    state.mux_plans = {1: action_plan, 3: action_plan}
    state.check_vars = {
        "0": SimpleNamespace(get=lambda: True),
        "1": SimpleNamespace(get=lambda: True),
        "2": SimpleNamespace(get=lambda: True),
        "3": SimpleNamespace(get=lambda: False),
    }

    assert get_checked_indices_from_state(state) == {0, 1}


def _tv_state_named(tmp_path, name, show_id):
    """A second, independent TV state (own folder/show id) for
    mixed-provider-batch tests below."""
    lib = tmp_path / "lib"
    item = PreviewItem(
        original=lib / name / "a.mkv",
        new_name=f"{name} - S01E01 - Pilot.mkv",
        target_dir=tmp_path / "out" / f"{name} (2020)" / "Season 01",
        season=1,
        episodes=[1],
        status="OK",
        media_type="tv",
    )
    return ScanState(
        folder=lib / name,
        media_info={"id": show_id, "name": name, "year": "2020"},
        preview_items=[item],
        scanned=True,
        checked=True,
        relative_folder=name,
    )


def test_data_source_reflects_state_provider_name_not_shared_client(tmp_path):
    """A mixed batch's job.data_source must reflect each STATE's own
    provider attribution (pin/fallback/manual-switch), not the single
    tmdb_client threaded through the whole add_tv_batch_jobs call — a
    show pinned to tvdb must record data_source="tvdb" even when the
    batch's shared client is the tmdb primary."""
    state = _tv_state(tmp_path)
    state.provider_name = "tvdb"
    store = _FakeStore()

    class _SharedClient:
        provider_name = "tmdb"

    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        tmdb_client=_SharedClient(),
    )

    assert result.added == 1
    assert store.jobs[0].data_source == "tvdb"


def test_provider_for_state_resolves_bake_client_per_show(tmp_path, monkeypatch):
    """The metadata-plan bake uses provider_for_state(state) per show, not
    the single shared tmdb_client, when a resolver is given — a mixed
    batch (some shows tmdb, some tvdb) must bake each show's plan through
    ITS OWN provider client."""
    from plex_renamer.app.controllers import _queue_submission_helpers as helpers

    baked_with = []
    monkeypatch.setattr(
        helpers,
        "_bake_metadata_plan",
        lambda job, settings_service, tmdb_client, library_root: baked_with.append(tmdb_client),
    )

    state_a = _tv_state_named(tmp_path, "ShowA", 7)
    state_a.provider_name = "tmdb"
    state_b = _tv_state_named(tmp_path, "ShowB", 8)
    state_b.provider_name = "tvdb"

    class _Client:
        def __init__(self, name):
            self.provider_name = name

    tmdb_client = _Client("tmdb")
    tvdb_client = _Client("tvdb")

    def _provider_for_state(state):
        return tvdb_client if state.provider_name == "tvdb" else tmdb_client

    store = _FakeStore()
    add_tv_batch_jobs(
        store,
        states=[state_a, state_b],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        tmdb_client=tmdb_client,
        provider_for_state=_provider_for_state,
    )

    assert baked_with == [tmdb_client, tvdb_client]


def test_movie_batch_bakes_remux_job(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    lib = tmp_path / "lib"
    item = PreviewItem(
        original=lib / "Movie" / "m.mkv",
        new_name="Movie (2020).mkv",
        target_dir=tmp_path / "out" / "Movie (2020)",
        season=None,
        episodes=[],
        status="OK",
        media_type="movie",
        companions=[
            CompanionFile(
                original=lib / "Movie" / "m.eng.srt",
                new_name="Movie (2020).eng.srt",
                file_type="subtitle",
            )
        ],
    )
    state = ScanState(
        folder=lib / "Movie",
        media_info={"id": 9, "title": "Movie", "year": "2020"},
        preview_items=[item],
        scanned=True,
        checked=True,
    )
    store = _FakeStore()
    result = add_movie_batch_jobs(
        store,
        states=[state],
        library_root=lib,
        output_root=tmp_path / "out",
        command_gating=_Gating(),
        settings_service=_settings(tmp_path),
    )
    assert result.added == 1
    assert store.jobs[0].job_kind == JobKind.REMUX


def test_mux_only_state_queued_through_real_gating(tmp_path, monkeypatch):
    """Round6 §1 mandatory end-to-end coverage: a checked state whose only
    relevant item is mux-only (correctly-named, action-bearing plan) must be
    evaluated ENABLED by the REAL CommandGatingService (no _Gating fake),
    its index must appear in selected_indices, and the job built from that
    selection must contain the mux op with selected=True. This is the exact
    chain RC-round6-task2-review found broken: allow_show_level_queue's
    is_actionable_item-only selection and evaluate()'s actionable
    intersection previously stripped mux-only indices before job_executor
    ever saw them."""
    monkeypatch.setattr(svc_mod, "probe_file", lambda mkv, path, **kwargs: _probe_ok())
    state = _tv_state_correctly_named(tmp_path)
    # An approved, high-confidence match: require_resolved_review=True (as
    # add_tv_batch_jobs always passes) must not trip on an unrelated
    # needs_review flag -- this test is only about mux-only selection.
    state.confidence = 1.0
    # Seed a cached, action-bearing plan so the REAL gating call (which runs
    # before _mux_plans_for_state/ensure_state_plans in add_tv_batch_jobs)
    # sees this index as mux-active.
    state.mux_plans[0] = {"subtitle_merges": [{"action": "merge"}]}

    gating = CommandGatingService()
    eligibility = gating.evaluate_scan_state(
        state,
        require_resolved_review=True,
        allow_show_level_queue=True,
    )
    assert eligibility.enabled
    assert eligibility.selected_indices == [0]

    store = _FakeStore()
    result = add_tv_batch_jobs(
        store,
        states=[state],
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        command_gating=gating,
        settings_service=_settings(tmp_path),
    )

    assert result.added == 1
    job = store.jobs[0]
    assert job.job_kind == JobKind.REMUX
    video_ops = [op for op in job.rename_ops if op.file_type == "video"]
    assert len(video_ops) == 1
    op = video_ops[0]
    assert op.mux is not None
    assert op.selected is True
