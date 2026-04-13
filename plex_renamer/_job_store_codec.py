"""Row-mapping and JSON serialization helpers for the job store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from typing import Any


def serialize_rename_ops(rename_ops: Iterable[Any]) -> str:
    """Serialize rename ops using their existing to_dict contract."""
    return json.dumps([op.to_dict() for op in rename_ops])


def serialize_rename_op_dicts(rename_ops: list[dict[str, Any]]) -> str:
    """Serialize already-expanded rename-op payloads."""
    return json.dumps(rename_ops)


def deserialize_rename_op_dicts(raw_rename_ops: str) -> list[dict[str, Any]]:
    """Parse the stored rename-op JSON payload."""
    return json.loads(raw_rename_ops)


def serialize_undo_data(undo_data: dict | None) -> str | None:
    """Serialize undo data when present."""
    return json.dumps(undo_data) if undo_data else None


def deserialize_undo_data(raw_undo_data: str | None) -> dict | None:
    """Parse the stored undo-data JSON payload."""
    return json.loads(raw_undo_data) if raw_undo_data else None


def row_to_job(
    row: sqlite3.Row,
    *,
    rename_op_from_dict: Callable[[dict[str, Any]], Any],
    job_factory: Callable[..., Any],
) -> Any:
    """Build one job object from a SQLite row."""
    rename_ops = [
        rename_op_from_dict(data)
        for data in deserialize_rename_op_dicts(row["rename_ops"])
    ]
    undo_data = deserialize_undo_data(row["undo_data"])

    return job_factory(
        job_id=row["job_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        media_type=row["media_type"],
        tmdb_id=row["tmdb_id"],
        media_name=row["media_name"],
        poster_path=row["poster_path"],
        library_root=row["library_root"],
        source_folder=row["source_folder"],
        show_folder_rename=row["show_folder_rename"],
        status=row["status"],
        error_message=row["error_message"],
        position=row["position"],
        undo_data=undo_data,
        job_kind=row["job_kind"],
        data_source=row["data_source"],
        depends_on=row["depends_on"],
        rename_ops=rename_ops,
    )
