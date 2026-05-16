"""
Persistent job queue backed by SQLite.

Stores rename jobs (and future job types) with full lifecycle tracking,
per-job undo data, deduplication, and path propagation.

The database lives alongside the existing rename log at
~/.plex_renamer/job_queue.db.

Thread safety: All public methods acquire the instance-level lock so the
GUI thread and background executor can safely share a single JobStore
instance.  Each thread gets its own SQLite connection via
``threading.local()`` since SQLite connections cannot be shared across
threads.  WAL mode allows concurrent readers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._job_path_propagation import rebase_path, rewrite_job_paths
from ._job_store_codec import (
    deserialize_rename_op_dicts,
    row_to_job,
    serialize_rename_op_dicts,
    serialize_rename_ops,
    serialize_undo_data,
)
from ._job_store_db import connect_job_store, initialize_job_store, migrate_job_store
from ._job_store_ordering import (
    compact_positions,
    move_pending_jobs,
    move_pending_jobs_to_top,
    reorder_pending_job,
)
from .constants import DB_FILE, JobKind, JobStatus, MediaType

_log = logging.getLogger(__name__)


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class RenameOp:
    """
    One file's rename plan — fully serializable, no Path objects.

    Paths are stored relative to the job's library_root so they survive
    drive remounts and are portable across machines.
    """
    original_relative: str          # Relative path from library_root
    new_name: str                   # Target filename
    target_dir_relative: str        # Relative path from library_root to target dir
    status: str                     # "OK", "UNMATCHED", etc.
    season: int | None = None
    episodes: list[int] = field(default_factory=list)
    selected: bool = True           # Was this file checked by the user?
    # "video" for the main media file; "subtitle" for companion subtitle files
    # renamed alongside it.  Extensible for future companion types (e.g. "nfo").
    file_type: str = "video"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RenameOp:
        d = dict(d)
        d.setdefault("file_type", "video")  # Back-compat: old rows lack this field
        return cls(**d)


@dataclass
class RenameJob:
    """
    A single unit of work in the job queue.

    Each job corresponds to exactly one media entity (one TV series or
    one movie).  Jobs are the atomic unit of execution, undo, and
    status tracking.
    """
    # Identity
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Media identity (dedup key together with job_kind + library_root)
    media_type: str = MediaType.TV
    tmdb_id: int = 0
    media_name: str = ""
    poster_path: str | None = None

    # Paths
    library_root: str = ""          # Absolute path to the library root
    source_folder: str = ""         # Relative path from library_root to show/movie folder

    # What to rename
    rename_ops: list[RenameOp] = field(default_factory=list)
    show_folder_rename: str | None = None   # New show folder name, or None

    # Status
    status: str = JobStatus.PENDING
    error_message: str | None = None
    position: int = 0               # Queue ordering (lower = earlier)

    # Undo data (populated after execution)
    undo_data: dict | None = None   # The log_entry dict from RenameResult

    # Job type + data source (extensibility)
    job_kind: str = JobKind.RENAME
    data_source: str = "tmdb"

    # Dependency linking
    # ─────────────────
    # For companion files that are renamed *alongside* their media file
    # (subtitles, future: posters, NFOs), use RenameOp entries within this
    # same job.  They execute and revert atomically — there is no scenario
    # where a subtitle reverts without its video, or vice versa.
    #
    # ``depends_on`` is reserved for jobs that are *sequentially dependent*
    # rather than atomic companions — specifically, a future
    # ``JobKind.SUBTITLE_DOWNLOAD`` job that downloads a subtitle file from
    # OpenSubtitles *after* a rename job has established the correct filename.
    # That job sets ``depends_on = rename_job_id`` so the executor can resolve
    # the final path and wait for the rename to complete first.
    depends_on: str | None = None   # job_id of prerequisite, or None

    @property
    def selected_ops(self) -> list[RenameOp]:
        """Return only the ops the user checked for execution."""
        return [op for op in self.rename_ops if op.selected]

    @property
    def selected_count(self) -> int:
        return sum(1 for op in self.rename_ops if op.selected)

    @property
    def video_ops(self) -> list[RenameOp]:
        """Ops for the primary media files (file_type == 'video')."""
        return [op for op in self.rename_ops if op.file_type == "video"]

    @property
    def companion_ops(self) -> list[RenameOp]:
        """
        Ops for companion files renamed alongside the video (subtitles,
        future: posters, NFOs).  Grouped by ``file_type`` in the GUI.

        These are always part of the same job as their video op — reverting
        this job reverts all companion ops atomically.
        """
        return [op for op in self.rename_ops if op.file_type != "video"]

    @property
    def source_path(self) -> Path:
        """Absolute path to the show/movie folder."""
        return Path(self.library_root) / self.source_folder

    @property
    def is_actionable(self) -> bool:
        """True if this job can be executed (pending with selected ops)."""
        return self.status == JobStatus.PENDING and self.selected_count > 0

    @property
    def is_terminal(self) -> bool:
        """True if this job is in a final state."""
        return self.status in (
            JobStatus.COMPLETED, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.REVERTED,
            JobStatus.REVERT_FAILED,
        )


# ─── SQLite store ────────────────────────────────────────────────────────────


class DuplicateJobError(Exception):
    """Raised when adding a job that duplicates a pending/running job."""
    def __init__(self, existing_job_id: str, media_name: str):
        self.existing_job_id = existing_job_id
        self.media_name = media_name
        super().__init__(
            f"A {media_name!r} job is already pending or running "
            f"(job {existing_job_id})")


class JobStore:
    """
    SQLite-backed persistent job queue with path propagation.

    Each thread gets its own SQLite connection via ``threading.local()``.
    This is mandatory because SQLite connections cannot be shared across
    threads (default ``check_same_thread=True``).  All public methods
    still acquire a shared lock for write serialization.
    """

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or DB_FILE
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    # ── Connection management ────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return the per-thread connection, creating it if needed."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = connect_job_store(self._db_path)
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close the current thread's connection.  Safe to call multiple times."""
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._lock:
            conn = self._get_conn()
            initialize_job_store(conn)

    def _migrate_db(self, conn: sqlite3.Connection, current_version: int) -> None:
        """Compatibility wrapper for extracted schema migration helpers."""
        migrate_job_store(conn, current_version)

    # ── Write operations ──────────────────────────────────────────────

    def add_job(self, job: RenameJob) -> RenameJob:
        """
        Add a job to the queue.

        Raises DuplicateJobError if a pending/running job with the same
        (job_kind, media_type, tmdb_id, library_root) already exists.
        """
        ops_json = serialize_rename_ops(job.rename_ops)
        undo_json = serialize_undo_data(job.undo_data)
        job.updated_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM jobs "
                    "WHERE status IN ('pending', 'running')"
                ).fetchone()
                job.position = row[0]

                conn.execute("""
                    INSERT INTO jobs (
                        job_id, created_at, updated_at, media_type, tmdb_id,
                        media_name, poster_path, library_root, source_folder,
                        show_folder_rename, status, error_message, position,
                        undo_data, job_kind, data_source, depends_on,
                        rename_ops
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.job_id, job.created_at, job.updated_at,
                    job.media_type, job.tmdb_id,
                    job.media_name, job.poster_path, job.library_root, job.source_folder,
                    job.show_folder_rename, job.status, job.error_message,
                    job.position, undo_json, job.job_kind, job.data_source,
                    job.depends_on, ops_json,
                ))
                conn.commit()
            except sqlite3.IntegrityError as e:
                conn.rollback()
                if "idx_jobs_dedup" in str(e) or "UNIQUE constraint" in str(e):
                    existing = conn.execute(
                        "SELECT job_id FROM jobs "
                        "WHERE job_kind = ? AND media_type = ? "
                        "AND tmdb_id = ? AND library_root = ? "
                        "AND status IN ('pending', 'running')",
                        (job.job_kind, job.media_type, job.tmdb_id,
                         job.library_root),
                    ).fetchone()
                    existing_id = existing["job_id"] if existing else "?"
                    raise DuplicateJobError(existing_id, job.media_name) from e
                raise

        return job

    def update_status(
        self,
        job_id: str,
        new_status: str,
        error_message: str | None = None,
    ) -> None:
        """Update a job's status and optionally its error message."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ?, "
                "updated_at = ? WHERE job_id = ?",
                (new_status, error_message, now, job_id))
            conn.commit()

    def set_undo_data(self, job_id: str, undo_data: dict) -> None:
        """Store undo/revert data after successful execution."""
        now = datetime.now(timezone.utc).isoformat()
        undo_json = serialize_undo_data(undo_data)
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE jobs SET undo_data = ?, updated_at = ? "
                "WHERE job_id = ?",
                (undo_json, now, job_id))
            conn.commit()

    def set_poster_path(self, job_id: str, poster_path: str | None) -> None:
        """Persist a resolved TMDB poster path for an existing job."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE jobs SET poster_path = ?, updated_at = ? WHERE job_id = ?",
                (poster_path, now, job_id),
            )
            conn.commit()

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a pending or cancelled job from the queue.

        Returns True if a row was deleted.
        """
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM jobs WHERE job_id = ? "
                "AND status IN ('pending', 'cancelled')",
                (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def remove_jobs(self, job_ids: list[str]) -> int:
        """
        Remove multiple pending or cancelled jobs.

        Returns the number of rows deleted.
        """
        if not job_ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            total = 0
            for jid in job_ids:
                cursor = conn.execute(
                    "DELETE FROM jobs WHERE job_id = ? "
                    "AND status IN ('pending', 'cancelled')",
                    (jid,))
                total += cursor.rowcount
            conn.commit()
            return total

    def reorder_job(self, job_id: str, new_position: int) -> None:
        """Move a pending job to a new position, then compact all positions."""
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(timezone.utc).isoformat()
            reorder_pending_job(
                conn,
                job_id=job_id,
                new_position=new_position,
                now=now,
            )
            conn.commit()

    def move_jobs(self, job_ids: list[str], direction: int) -> None:
        """
        Move multiple pending jobs up (direction=-1) or down (direction=1).

        Jobs are moved as a block: their relative order is preserved.
        """
        if not job_ids or direction not in (-1, 1):
            return
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(timezone.utc).isoformat()
            if move_pending_jobs(
                conn,
                job_ids=job_ids,
                direction=direction,
                now=now,
            ):
                conn.commit()

    def move_jobs_to_top(self, job_ids: list[str]) -> None:
        """Move the given pending jobs to the top of the queue."""
        if not job_ids:
            return
        with self._lock:
            conn = self._get_conn()
            now = datetime.now(timezone.utc).isoformat()
            if move_pending_jobs_to_top(conn, job_ids=job_ids, now=now):
                conn.commit()

    def clear_history(self) -> int:
        """Delete all terminal jobs.  Returns row count."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM jobs WHERE status IN "
                "('completed', 'failed', 'cancelled', 'reverted', 'revert_failed')")
            conn.commit()
            return cursor.rowcount

    def _compact_positions(self, conn: sqlite3.Connection) -> None:
        """Reassign positions 1..N for pending/running jobs. Call under lock."""
        compact_positions(conn)

    # ── Path propagation ──────────────────────────────────────────────

    def propagate_path_changes(
        self,
        completed_job_id: str,
        renamed_dirs: list[dict],
    ) -> int:
        """
        Update pending jobs whose paths overlap with renamed directories.

        When a job renames a show folder (e.g. "Bad.Name" → "Good Name (2020)"),
        other pending jobs referencing files inside that old tree need their
        source_folder and op paths rewritten to match the new location.

        Returns the number of pending jobs that were updated.
        """
        if not renamed_dirs:
            return 0

        updated_count = 0
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT job_id, library_root, source_folder, rename_ops "
                "FROM jobs WHERE status = 'pending' AND job_id != ?",
                (completed_job_id,)
            ).fetchall()

            for row in rows:
                job_id = row["job_id"]
                source_folder, ops_data, changed = rewrite_job_paths(
                    library_root=row["library_root"],
                    source_folder=row["source_folder"],
                    rename_ops=deserialize_rename_op_dicts(row["rename_ops"]),
                    renamed_dirs=renamed_dirs,
                )

                if changed:
                    conn.execute(
                        "UPDATE jobs SET source_folder = ?, rename_ops = ?, "
                        "updated_at = ? WHERE job_id = ?",
                        (source_folder, serialize_rename_op_dicts(ops_data), now, job_id))
                    updated_count += 1

            if updated_count:
                conn.commit()

        if updated_count:
            _log.info(
                "Propagated path changes from job %s to %d pending job(s)",
                completed_job_id[:8], updated_count)

        return updated_count

    @staticmethod
    def _rebase_path(path_str: str, old_prefix: str, new_prefix: str) -> str:
        """Compatibility wrapper for the extracted path-rewrite helper."""
        return rebase_path(path_str, old_prefix, new_prefix)

    # ── Read operations ───────────────────────────────────────────────

    def get_job(self, job_id: str) -> RenameJob | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return self._row_to_job(row) if row else None

    def get_pending(self) -> list[RenameJob]:
        return self._get_by_status([JobStatus.PENDING])

    def get_running(self) -> list[RenameJob]:
        return self._get_by_status([JobStatus.RUNNING])

    def get_queue(self) -> list[RenameJob]:
        return self._get_by_status([JobStatus.PENDING, JobStatus.RUNNING])

    def get_history(self) -> list[RenameJob]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM jobs "
                "WHERE status IN ('completed', 'failed', 'cancelled', 'reverted', 'revert_failed') "
                "ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_job(r) for r in rows]

    def get_latest_completed_with_undo(self) -> RenameJob | None:
        """Return the most recently completed job that can still be reverted."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM jobs "
                "WHERE status = ? AND undo_data IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 1",
                (JobStatus.COMPLETED,),
            ).fetchone()
            return self._row_to_job(row) if row else None

    def get_all(self) -> list[RenameJob]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY "
                "CASE WHEN status IN ('pending', 'running') THEN 0 ELSE 1 END, "
                "position ASC, updated_at DESC"
            ).fetchall()
            return [self._row_to_job(r) for r in rows]

    def get_next_pending(self) -> RenameJob | None:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending' "
                "ORDER BY position ASC"
            ).fetchall()
            for row in rows:
                job = self._row_to_job(row)
                if job.depends_on:
                    dep = conn.execute(
                        "SELECT status FROM jobs WHERE job_id = ?",
                        (job.depends_on,)
                    ).fetchone()
                    if dep and dep["status"] != JobStatus.COMPLETED:
                        continue
                return job
            return None

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
            ).fetchall()
            return {r["status"]: r["cnt"] for r in rows}

    def get_queued_tmdb_ids(self) -> set[int]:
        """Return TMDB IDs of all pending/running jobs for queued-state restoration."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT DISTINCT tmdb_id FROM jobs "
                "WHERE status IN ('pending', 'running')"
            ).fetchall()
            return {r["tmdb_id"] for r in rows}

    # ── Internal ──────────────────────────────────────────────────────

    def _get_by_status(self, statuses: list[str]) -> list[RenameJob]:
        placeholders = ",".join("?" for _ in statuses)
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) "
                "ORDER BY position ASC",
                statuses,
            ).fetchall()
            return [self._row_to_job(r) for r in rows]

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> RenameJob:
        return row_to_job(
            row,
            rename_op_from_dict=RenameOp.from_dict,
            job_factory=RenameJob,
        )
