"""Queue submission bakes metadata plans onto jobs."""

from pathlib import Path

from plex_renamer.app.controllers._queue_submission_helpers import (
    add_single_queue_job,
)
from plex_renamer.app.services.metadata_service import (
    attach_metadata_plan,
    make_image_fetcher,
)
from plex_renamer.constants import MediaType
from plex_renamer.engine.models import PreviewItem
from tests.test_metadata_service import (
    SEASONS,
    TV_DETAILS,
    FakeTMDB,
    make_settings,
    tv_job,
)


class FakeStore:
    def __init__(self):
        self.jobs = []

    def add_job(self, job):
        self.jobs.append(job)
        return job


def test_attach_metadata_plan_sets_finalized_plan(tmp_path):
    job = tv_job(library_root=str(tmp_path))
    attach_metadata_plan(
        job,
        tmdb_client=FakeTMDB(details=TV_DETAILS, seasons=SEASONS),
        settings_service=make_settings(),
        library_root=tmp_path,
    )
    assert job.metadata_plan is not None
    slots = {e["slot"] for e in job.metadata_plan["artwork"]}
    assert "poster" in slots
    # Placeholders (specials still is None in SEASONS) were dropped.
    assert all(e["tmdb_path"] for e in job.metadata_plan["artwork"])


def test_attach_is_noop_when_disabled_or_clientless(tmp_path):
    job = tv_job(library_root=str(tmp_path))
    attach_metadata_plan(
        job, tmdb_client=None, settings_service=make_settings(), library_root=tmp_path
    )
    assert job.metadata_plan is None

    attach_metadata_plan(
        job,
        tmdb_client=FakeTMDB(),
        settings_service=make_settings(metadata_enabled=False),
        library_root=tmp_path,
    )
    assert job.metadata_plan is None


def test_add_single_queue_job_attaches_plan(tmp_path):
    src = tmp_path / "src" / "Show"
    src.mkdir(parents=True)
    video = src / "Show.S01E01.mkv"
    video.write_bytes(b"v")
    out = tmp_path / "out"
    out.mkdir()

    item = PreviewItem(
        original=video,
        new_name="Show (2019) - S01E01 - Pilot.mkv",
        target_dir=out / "Show (2019)" / "Season 01",
        season=1,
        episodes=[1],
        status="OK",
        media_type=MediaType.TV,
    )
    store = FakeStore()
    job = add_single_queue_job(
        store,
        items=[item],
        checked_indices={0},
        media_type=MediaType.TV,
        tmdb_id=42,
        media_name="Show",
        library_root=tmp_path / "src",
        output_root=out,
        source_folder=Path("Show"),
        show_folder_rename="Show (2019)",
        settings_service=make_settings(),
        tmdb_client=FakeTMDB(details=TV_DETAILS, seasons=SEASONS),
    )
    assert store.jobs == [job]
    assert job.metadata_plan is not None
    assert any(e["slot"] == "nfo:show" for e in job.metadata_plan["nfo_files"])


def test_add_single_queue_job_survives_bake_failure(tmp_path):
    """A TMDB call raising during the queue-time metadata bake must not
    abort queueing — the job still gets queued, just undecorated."""
    src = tmp_path / "src" / "Show"
    src.mkdir(parents=True)
    video = src / "Show.S01E01.mkv"
    video.write_bytes(b"v")
    out = tmp_path / "out"
    out.mkdir()

    class ExplodingTMDB(FakeTMDB):
        def get_tv_details(self, show_id):
            raise RuntimeError("TMDB is down")

    item = PreviewItem(
        original=video,
        new_name="Show (2019) - S01E01 - Pilot.mkv",
        target_dir=out / "Show (2019)" / "Season 01",
        season=1,
        episodes=[1],
        status="OK",
        media_type=MediaType.TV,
    )
    store = FakeStore()
    job = add_single_queue_job(
        store,
        items=[item],
        checked_indices={0},
        media_type=MediaType.TV,
        tmdb_id=42,
        media_name="Show",
        library_root=tmp_path / "src",
        output_root=out,
        source_folder=Path("Show"),
        show_folder_rename="Show (2019)",
        settings_service=make_settings(),
        tmdb_client=ExplodingTMDB(details=TV_DETAILS, seasons=SEASONS),
    )
    assert store.jobs == [job]
    assert job.metadata_plan is None


def test_make_image_fetcher_uses_live_client():
    class Client:
        def fetch_image_bytes(self, path, size="original"):
            return b"live:" + path.encode()

    fetch = make_image_fetcher(
        get_client=lambda: Client(),
        api_key_lookup=lambda name: None,
    )
    assert fetch("/x.jpg") == b"live:/x.jpg"


def test_make_image_fetcher_without_client_or_key_returns_none():
    fetch = make_image_fetcher(
        get_client=lambda: None,
        api_key_lookup=lambda name: None,
    )
    assert fetch("/x.jpg") is None
