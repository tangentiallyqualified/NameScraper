"""Queue ordering helpers for the persistent job store."""

from __future__ import annotations

import sqlite3


def compact_positions(conn: sqlite3.Connection) -> None:
    """Reassign positions 1..N for pending/running jobs."""
    rows = conn.execute(
        "SELECT job_id FROM jobs "
        "WHERE status IN ('pending', 'running') "
        "ORDER BY position ASC"
    ).fetchall()
    for idx, row in enumerate(rows, start=1):
        conn.execute(
            "UPDATE jobs SET position = ? WHERE job_id = ?",
            (idx, row["job_id"]),
        )


def reorder_pending_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    new_position: int,
    now: str,
) -> None:
    """Move one pending job to a new queue position."""
    conn.execute(
        "UPDATE jobs SET position = position + 1 "
        "WHERE status = 'pending' AND position >= ?",
        (new_position,),
    )
    conn.execute(
        "UPDATE jobs SET position = ?, updated_at = ? "
        "WHERE job_id = ? AND status = 'pending'",
        (new_position, now, job_id),
    )
    compact_positions(conn)


def move_pending_jobs(
    conn: sqlite3.Connection,
    *,
    job_ids: list[str],
    direction: int,
    now: str,
) -> bool:
    """Move a block of pending jobs up or down while preserving order."""
    if not job_ids or direction not in (-1, 1):
        return False

    rows = conn.execute(
        "SELECT job_id, position FROM jobs "
        "WHERE status = 'pending' "
        "ORDER BY position ASC"
    ).fetchall()
    ordered = [row["job_id"] for row in rows]
    id_set = set(job_ids)
    indices = [idx for idx, job_id in enumerate(ordered) if job_id in id_set]
    if not indices:
        return False

    if direction == -1 and indices[0] > 0:
        swap_idx = indices[0] - 1
        item = ordered.pop(swap_idx)
        ordered.insert(indices[-1], item)
    elif direction == 1 and indices[-1] < len(ordered) - 1:
        swap_idx = indices[-1] + 1
        item = ordered.pop(swap_idx)
        ordered.insert(indices[0], item)
    else:
        return False

    _write_pending_positions(conn, ordered, now)
    return True


def move_pending_jobs_to_top(
    conn: sqlite3.Connection,
    *,
    job_ids: list[str],
    now: str,
) -> bool:
    """Move the given pending jobs to the top while preserving order."""
    if not job_ids:
        return False

    rows = conn.execute(
        "SELECT job_id, position FROM jobs "
        "WHERE status = 'pending' "
        "ORDER BY position ASC"
    ).fetchall()
    ordered = [row["job_id"] for row in rows]
    id_set = set(job_ids)
    selected = [job_id for job_id in ordered if job_id in id_set]
    if not selected:
        return False
    rest = [job_id for job_id in ordered if job_id not in id_set]
    _write_pending_positions(conn, selected + rest, now)
    return True


def _write_pending_positions(
    conn: sqlite3.Connection,
    ordered_job_ids: list[str],
    now: str,
) -> None:
    for pos, job_id in enumerate(ordered_job_ids, start=1):
        conn.execute(
            "UPDATE jobs SET position = ?, updated_at = ? WHERE job_id = ?",
            (pos, now, job_id),
        )
