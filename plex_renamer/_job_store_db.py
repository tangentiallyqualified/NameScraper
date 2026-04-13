"""SQLite connection and schema helpers for the persistent job queue."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .constants import ensure_log_dir

SCHEMA_VERSION = 2

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    tmdb_id         INTEGER NOT NULL,
    media_name      TEXT NOT NULL,
    poster_path     TEXT,
    library_root    TEXT NOT NULL,
    source_folder   TEXT NOT NULL,
    show_folder_rename TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    position        INTEGER NOT NULL DEFAULT 0,
    undo_data       TEXT,
    job_kind        TEXT NOT NULL DEFAULT 'rename',
    data_source     TEXT NOT NULL DEFAULT 'tmdb',
    depends_on      TEXT,
    rename_ops      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_position ON jobs(position);
"""

DEDUP_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedup
    ON jobs(job_kind, media_type, tmdb_id, library_root)
    WHERE status IN ('pending', 'running');
"""


def connect_job_store(db_path: Path) -> sqlite3.Connection:
    """Create one SQLite connection configured for the job queue."""
    ensure_log_dir()
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_job_store(conn: sqlite3.Connection) -> None:
    """Create the schema and run any needed migrations."""
    conn.executescript(CREATE_SQL)
    conn.executescript(DEDUP_INDEX_SQL)
    row = conn.execute(
        "SELECT version FROM schema_version LIMIT 1"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
    elif int(row["version"]) < SCHEMA_VERSION:
        migrate_job_store(conn, int(row["version"]))
    conn.commit()


def migrate_job_store(conn: sqlite3.Connection, current_version: int) -> None:
    """Upgrade an existing job-store schema in place."""
    version = current_version
    if version < 2:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "poster_path" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN poster_path TEXT")
        conn.execute("UPDATE schema_version SET version = ?", (2,))
