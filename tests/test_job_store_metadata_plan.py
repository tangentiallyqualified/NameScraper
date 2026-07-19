"""metadata_plan column: round-trip + v4 migration."""

import sqlite3

from plex_renamer.job_store import JobStore, RenameJob, RenameOp


def _job(**overrides) -> RenameJob:
    defaults = {
        "media_type": "tv",
        "tmdb_id": 42,
        "media_name": "Show",
        "library_root": "C:/src",
        "output_root": "C:/out",
        "source_folder": "Show",
        "rename_ops": [
            RenameOp(
                original_relative="Show/a.mkv",
                new_name="Show (2019) - S01E01 - Pilot.mkv",
                target_dir_relative="Show (2019)/Season 01",
                status="OK",
                season=1,
                episodes=[1],
            )
        ],
    }
    defaults.update(overrides)
    return RenameJob(**defaults)


def test_metadata_plan_round_trip(tmp_path):
    store = JobStore(db_path=tmp_path / "jobs.db")
    plan = {
        "nfo_files": [
            {
                "target_relative": "Show (2019)/tvshow.nfo",
                "content": "<tvshow/>",
                "slot": "nfo:show",
            }
        ],
        "artwork": [],
        "embed_title": True,
        "prefer_local": False,
        "plex_naming": False,
    }
    store.add_job(_job(metadata_plan=plan))

    reloaded = store.get_all()[0]
    assert reloaded.metadata_plan == plan


def test_metadata_plan_defaults_to_none(tmp_path):
    store = JobStore(db_path=tmp_path / "jobs.db")
    store.add_job(_job())
    assert store.get_all()[0].metadata_plan is None


def test_v4_database_migrates(tmp_path):
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (4);
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, media_type TEXT NOT NULL,
            tmdb_id INTEGER NOT NULL, media_name TEXT NOT NULL,
            poster_path TEXT, library_root TEXT NOT NULL,
            output_root TEXT, source_folder TEXT NOT NULL,
            show_folder_rename TEXT,
            status TEXT NOT NULL DEFAULT 'pending', error_message TEXT,
            position INTEGER NOT NULL DEFAULT 0, undo_data TEXT,
            job_kind TEXT NOT NULL DEFAULT 'rename',
            data_source TEXT NOT NULL DEFAULT 'tmdb',
            depends_on TEXT, active_temp TEXT, rename_ops TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    store = JobStore(db_path=db)  # triggers migration
    store.add_job(
        _job(
            metadata_plan={
                "embed_title": True,
                "nfo_files": [],
                "artwork": [],
                "prefer_local": False,
                "plex_naming": False,
            }
        )
    )
    assert store.get_all()[0].metadata_plan["embed_title"] is True
