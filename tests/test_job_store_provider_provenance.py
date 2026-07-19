"""Provider provenance on jobs: dedupe key + schema v6 migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from plex_renamer.job_store import DuplicateJobError, JobStore, RenameJob, RenameOp

# Helpers mirror tests/test_job_store_metadata_plan.py's `_job` factory and
# its `store.get_all()` listing method (the brief's placeholder `all_jobs()`
# does not exist on JobStore).


def _make_store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "jobs.db")


def _make_job(*, tmdb_id: int) -> RenameJob:
    return RenameJob(
        media_type="tv",
        tmdb_id=tmdb_id,
        media_name="Show",
        library_root="C:/src",
        output_root="C:/out",
        source_folder="Show",
        rename_ops=[
            RenameOp(
                original_relative="Show/a.mkv",
                new_name="Show (2019) - S01E01 - Pilot.mkv",
                target_dir_relative="Show (2019)/Season 01",
                status="OK",
                season=1,
                episodes=[1],
            )
        ],
    )


def test_same_show_id_different_source_both_queue(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    job_a = _make_job(tmdb_id=81189)
    job_a.data_source = "tmdb"
    job_b = _make_job(tmdb_id=81189)
    job_b.data_source = "tvdb"
    store.add_job(job_a)
    store.add_job(job_b)  # must NOT raise DuplicateJobError — different source
    assert len(store.get_all()) == 2


def test_same_show_same_source_is_deduped(tmp_path: Path) -> None:
    # Real JobStore.add_job behavior (see tests/test_queue_controller.py) is
    # to raise DuplicateJobError on a conflicting pending job, not to
    # silently skip it. Assert that same behavior here with source held
    # constant, adapted from the brief's silent-skip sketch.
    store = _make_store(tmp_path)
    job_a = _make_job(tmdb_id=81189)
    job_b = _make_job(tmdb_id=81189)
    store.add_job(job_a)
    with pytest.raises(DuplicateJobError):
        store.add_job(job_b)
    assert len(store.get_all()) == 1


def test_migration_v5_to_v6_rebuilds_dedup_index(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    # Build a v5-shaped store: current CREATE_SQL minus the new index, version 5.
    from plex_renamer._job_store_db import CREATE_SQL

    conn.executescript(CREATE_SQL)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedup "
        "ON jobs(job_kind, media_type, tmdb_id, library_root) "
        "WHERE status IN ('pending', 'running')"
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    conn.commit()
    conn.close()

    from plex_renamer._job_store_db import connect_job_store, initialize_job_store

    conn2 = connect_job_store(db)
    initialize_job_store(conn2)
    row = conn2.execute("SELECT sql FROM sqlite_master WHERE name = 'idx_jobs_dedup'").fetchone()
    assert row is not None
    assert "data_source" in row["sql"]
    version = conn2.execute("SELECT version FROM schema_version").fetchone()
    assert int(version["version"]) == 6
    conn2.close()
