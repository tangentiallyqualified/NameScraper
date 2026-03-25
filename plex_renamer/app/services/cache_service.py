"""Persistent metadata cache with freshness tracking and bounded eviction."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...constants import CACHE_DB_FILE, ensure_log_dir
from ..models import CacheEntry, CacheLookup, RefreshState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class PersistentCacheService:
    """SQLite-backed cache for persisted metadata and scan-related state."""

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        max_size_bytes: int = 64 * 1024 * 1024,
        max_items: int = 4000,
    ):
        self._db_path = db_path or CACHE_DB_FILE
        self._max_size_bytes = max_size_bytes
        self._max_items = max_items
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        ensure_log_dir()
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    refreshed_at TEXT NOT NULL,
                    expires_at TEXT,
                    last_accessed_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    is_refreshing INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(namespace, cache_key)
                );

                CREATE INDEX IF NOT EXISTS idx_cache_access
                    ON cache_entries(last_accessed_at);
                """
            )

    @staticmethod
    def make_key(*parts: object) -> str:
        """Create a stable cache key from path-safe string parts."""
        return "::".join(str(part).strip().replace("\\", "/") for part in parts)

    def get(
        self,
        namespace: str,
        key: str,
        *,
        allow_stale: bool = True,
        now: datetime | None = None,
    ) -> CacheLookup:
        """Return a cached value plus freshness state."""
        now = now or _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cache_entries WHERE namespace = ? AND cache_key = ?",
                (namespace, key),
            ).fetchone()
            if row is None:
                return CacheLookup(state=RefreshState.MISSING)

            access_ts = now.isoformat()
            conn.execute(
                "UPDATE cache_entries SET last_accessed_at = ? WHERE namespace = ? AND cache_key = ?",
                (access_ts, namespace, key),
            )

            entry = CacheEntry(
                namespace=row["namespace"],
                key=row["cache_key"],
                value=json.loads(row["payload_json"]),
                refreshed_at=row["refreshed_at"],
                expires_at=row["expires_at"],
                last_accessed_at=access_ts,
                metadata=json.loads(row["metadata_json"] or "{}"),
                size_bytes=row["size_bytes"],
                is_refreshing=bool(row["is_refreshing"]),
            )

        state = self._resolve_state(entry, now=now)
        if state == RefreshState.STALE and not allow_stale:
            return CacheLookup(state=RefreshState.STALE, entry=None)
        return CacheLookup(state=state, entry=entry)

    def put(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        refreshed_at: str | None = None,
    ) -> CacheEntry:
        """Store or replace a cache entry, then enforce eviction caps."""
        refreshed_at = refreshed_at or _utc_now().isoformat()
        access_ts = refreshed_at
        metadata = metadata or {}
        payload_json = json.dumps(value, sort_keys=True)
        metadata_json = json.dumps(metadata, sort_keys=True)
        size_bytes = len(payload_json.encode("utf-8")) + len(metadata_json.encode("utf-8"))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entries (
                    namespace, cache_key, payload_json, metadata_json,
                    refreshed_at, expires_at, last_accessed_at, size_bytes, is_refreshing
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    metadata_json = excluded.metadata_json,
                    refreshed_at = excluded.refreshed_at,
                    expires_at = excluded.expires_at,
                    last_accessed_at = excluded.last_accessed_at,
                    size_bytes = excluded.size_bytes,
                    is_refreshing = 0
                """,
                (
                    namespace,
                    key,
                    payload_json,
                    metadata_json,
                    refreshed_at,
                    expires_at,
                    access_ts,
                    size_bytes,
                ),
            )
            self._prune_locked(conn)

        return CacheEntry(
            namespace=namespace,
            key=key,
            value=value,
            refreshed_at=refreshed_at,
            expires_at=expires_at,
            last_accessed_at=access_ts,
            metadata=metadata,
            size_bytes=size_bytes,
        )

    def mark_refreshing(self, namespace: str, key: str, refreshing: bool = True) -> None:
        """Set or clear the refreshing flag for an entry."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE cache_entries SET is_refreshing = ? WHERE namespace = ? AND cache_key = ?",
                (1 if refreshing else 0, namespace, key),
            )

    def invalidate(self, namespace: str, key: str) -> int:
        """Delete a single cache entry."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE namespace = ? AND cache_key = ?",
                (namespace, key),
            )
            return cursor.rowcount

    def invalidate_namespace(self, namespace: str) -> int:
        """Delete every entry in a namespace."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE namespace = ?",
                (namespace,),
            )
            return cursor.rowcount

    def invalidate_by_prefix(self, namespace: str, key_prefix: str) -> int:
        """Delete every entry whose key starts with the provided prefix."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE namespace = ? AND cache_key LIKE ?",
                (namespace, f"{key_prefix}%"),
            )
            return cursor.rowcount

    def stats(self) -> dict[str, int]:
        """Return aggregate cache statistics for auditing and tests."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS item_count, COALESCE(SUM(size_bytes), 0) AS total_size FROM cache_entries"
            ).fetchone()
            return {
                "item_count": int(row["item_count"]),
                "total_size_bytes": int(row["total_size"]),
                "max_items": self._max_items,
                "max_size_bytes": self._max_size_bytes,
            }

    def _resolve_state(self, entry: CacheEntry, *, now: datetime) -> RefreshState:
        if entry.is_refreshing:
            return RefreshState.REFRESHING
        expires_at = _parse_dt(entry.expires_at)
        refreshed_at = _parse_dt(entry.refreshed_at)
        if expires_at is None:
            return RefreshState.FRESH
        if expires_at > now:
            if refreshed_at is not None and (now - refreshed_at).total_seconds() <= 300:
                return RefreshState.RECENTLY_REFRESHED
            return RefreshState.FRESH
        return RefreshState.STALE

    def _prune_locked(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT COUNT(*) AS item_count, COALESCE(SUM(size_bytes), 0) AS total_size FROM cache_entries"
        ).fetchone()
        item_count = int(row["item_count"])
        total_size = int(row["total_size"])

        while item_count > self._max_items or total_size > self._max_size_bytes:
            victim = conn.execute(
                "SELECT namespace, cache_key, size_bytes FROM cache_entries ORDER BY last_accessed_at ASC LIMIT 1"
            ).fetchone()
            if victim is None:
                break
            conn.execute(
                "DELETE FROM cache_entries WHERE namespace = ? AND cache_key = ?",
                (victim["namespace"], victim["cache_key"]),
            )
            item_count -= 1
            total_size -= int(victim["size_bytes"])