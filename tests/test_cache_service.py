"""Unit tests for PersistentCacheService — round-trip, TTL, eviction, invalidation."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plex_renamer.app.models import RefreshState
from plex_renamer.app.services.cache_service import PersistentCacheService


def _utc(offset_hours: float = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=offset_hours)


class CacheServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "cache.db"
        self.cache = PersistentCacheService(db_path=self.db_path)

    def test_init_closes_sqlite_connection(self):
        class _FakeConnection:
            def __init__(self):
                self.closed = False
                self.row_factory = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def executescript(self, _sql):
                return None

            def close(self):
                self.closed = True

        conn = _FakeConnection()

        with patch("plex_renamer.app.services.cache_service.sqlite3.connect", return_value=conn):
            PersistentCacheService(db_path=self.db_path)

        self.assertTrue(conn.closed)

    def test_put_get_round_trip(self):
        self.cache.put("ns", "key1", {"title": "Arrival"})
        lookup = self.cache.get("ns", "key1")
        self.assertTrue(lookup.is_hit)
        self.assertEqual(lookup.value, {"title": "Arrival"})
        self.assertEqual(lookup.entry.namespace, "ns")
        self.assertEqual(lookup.entry.key, "key1")

    def test_get_missing_key_returns_missing_state(self):
        lookup = self.cache.get("ns", "nonexistent")
        self.assertFalse(lookup.is_hit)
        self.assertEqual(lookup.state, RefreshState.MISSING)
        self.assertIsNone(lookup.value)

    def test_namespace_isolation(self):
        self.cache.put("tv", "key1", {"name": "Bleach"})
        self.cache.put("movie", "key1", {"name": "Arrival"})
        self.assertEqual(self.cache.get("tv", "key1").value, {"name": "Bleach"})
        self.assertEqual(self.cache.get("movie", "key1").value, {"name": "Arrival"})

    def test_put_overwrites_existing_entry(self):
        self.cache.put("ns", "key1", {"v": 1})
        self.cache.put("ns", "key1", {"v": 2})
        self.assertEqual(self.cache.get("ns", "key1").value, {"v": 2})

    def test_stale_entry_hidden_when_allow_stale_false(self):
        past = _utc()
        expired = (past - timedelta(hours=1)).isoformat()
        self.cache.put("ns", "key1", {"v": 1}, refreshed_at=past.isoformat(), expires_at=expired)
        lookup = self.cache.get("ns", "key1", allow_stale=False, now=past)
        self.assertEqual(lookup.state, RefreshState.STALE)
        self.assertIsNone(lookup.entry)

    def test_stale_entry_returned_when_allow_stale_true(self):
        past = _utc()
        expired = (past - timedelta(hours=1)).isoformat()
        self.cache.put("ns", "key1", {"v": 1}, refreshed_at=past.isoformat(), expires_at=expired)
        lookup = self.cache.get("ns", "key1", allow_stale=True, now=past)
        self.assertEqual(lookup.state, RefreshState.STALE)
        self.assertIsNotNone(lookup.entry)

    def test_fresh_entry_state(self):
        now = _utc()
        future = (now + timedelta(days=30)).isoformat()
        self.cache.put("ns", "key1", {"v": 1}, refreshed_at=now.isoformat(), expires_at=future)
        lookup = self.cache.get("ns", "key1", now=now + timedelta(hours=1))
        self.assertEqual(lookup.state, RefreshState.FRESH)

    def test_recently_refreshed_state(self):
        now = _utc()
        future = (now + timedelta(days=30)).isoformat()
        self.cache.put("ns", "key1", {"v": 1}, refreshed_at=now.isoformat(), expires_at=future)
        lookup = self.cache.get("ns", "key1", now=now + timedelta(minutes=1))
        self.assertEqual(lookup.state, RefreshState.RECENTLY_REFRESHED)

    def test_mark_refreshing(self):
        now = _utc()
        future = (now + timedelta(days=30)).isoformat()
        self.cache.put("ns", "key1", {"v": 1}, refreshed_at=now.isoformat(), expires_at=future)
        self.cache.mark_refreshing("ns", "key1", True)
        lookup = self.cache.get("ns", "key1", now=now + timedelta(hours=1))
        self.assertEqual(lookup.state, RefreshState.REFRESHING)

        self.cache.mark_refreshing("ns", "key1", False)
        lookup = self.cache.get("ns", "key1", now=now + timedelta(hours=1))
        self.assertNotEqual(lookup.state, RefreshState.REFRESHING)

    def test_invalidate_single_entry(self):
        self.cache.put("ns", "key1", {"v": 1})
        self.cache.put("ns", "key2", {"v": 2})
        deleted = self.cache.invalidate("ns", "key1")
        self.assertEqual(deleted, 1)
        self.assertFalse(self.cache.get("ns", "key1").is_hit)
        self.assertTrue(self.cache.get("ns", "key2").is_hit)

    def test_invalidate_returns_zero_for_missing_key(self):
        self.assertEqual(self.cache.invalidate("ns", "nope"), 0)

    def test_invalidate_namespace(self):
        self.cache.put("ns", "key1", {"v": 1})
        self.cache.put("ns", "key2", {"v": 2})
        self.cache.put("other", "key1", {"v": 3})
        deleted = self.cache.invalidate_namespace("ns")
        self.assertEqual(deleted, 2)
        self.assertFalse(self.cache.get("ns", "key1").is_hit)
        self.assertTrue(self.cache.get("other", "key1").is_hit)

    def test_invalidate_namespace_prefix_removes_root_and_child_namespaces(self):
        self.cache.put("tmdb", "client_snapshot", {"movie_cache": {"1": {}}})
        self.cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
        self.cache.put("tmdb.poster_image", "poster::200", {"png_base64": "abc"})
        self.cache.put("other", "key1", {"v": 3})

        deleted = self.cache.invalidate_namespace_prefix("tmdb")

        self.assertEqual(deleted, 3)
        self.assertFalse(self.cache.get("tmdb", "client_snapshot").is_hit)
        self.assertFalse(self.cache.get("tmdb.tv_details", "1").is_hit)
        self.assertFalse(self.cache.get("tmdb.poster_image", "poster::200").is_hit)
        self.assertTrue(self.cache.get("other", "key1").is_hit)

    def test_invalidate_namespace_prefix_is_literal_case_sensitive_and_dot_bound(self):
        self.cache.put("tmdb", "root", {"v": 1})
        self.cache.put("tmdb.child", "child", {"v": 2})
        self.cache.put("tmdbx", "sibling", {"v": 3})
        self.cache.put("tmdb_extra", "underscore", {"v": 4})
        self.cache.put("TMDB.child", "case", {"v": 5})
        self.cache.put("foo_bar", "root", {"v": 6})
        self.cache.put("foo_bar.child", "child", {"v": 7})
        self.cache.put("fooXbar.child", "wildcard-lookalike", {"v": 8})

        tmdb_deleted = self.cache.invalidate_namespace_prefix("tmdb")
        foo_bar_deleted = self.cache.invalidate_namespace_prefix("foo_bar")

        self.assertEqual(tmdb_deleted, 2)
        self.assertEqual(foo_bar_deleted, 2)
        self.assertFalse(self.cache.get("tmdb", "root").is_hit)
        self.assertFalse(self.cache.get("tmdb.child", "child").is_hit)
        self.assertFalse(self.cache.get("foo_bar", "root").is_hit)
        self.assertFalse(self.cache.get("foo_bar.child", "child").is_hit)
        self.assertTrue(self.cache.get("tmdbx", "sibling").is_hit)
        self.assertTrue(self.cache.get("tmdb_extra", "underscore").is_hit)
        self.assertTrue(self.cache.get("TMDB.child", "case").is_hit)
        self.assertTrue(self.cache.get("fooXbar.child", "wildcard-lookalike").is_hit)

    def test_stats_can_be_scoped_to_namespace_prefix(self):
        self.cache.put("tmdb", "client_snapshot", {"movie_cache": {"1": {}}})
        self.cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
        self.cache.put("tmdb.poster_image", "poster::200", {"png_base64": "abc"})
        self.cache.put("other", "key1", {"v": 3})

        all_stats = self.cache.stats()
        tmdb_stats = self.cache.stats(namespace_prefix="tmdb")

        self.assertEqual(all_stats["item_count"], 4)
        self.assertEqual(tmdb_stats["item_count"], 3)
        self.assertGreater(tmdb_stats["total_size_bytes"], 0)
        self.assertEqual(tmdb_stats["max_items"], 200_000)

    def test_stats_namespace_prefix_is_literal_case_sensitive_and_dot_bound(self):
        self.cache.put("tmdb", "root", {"v": 1})
        self.cache.put("tmdb.child", "child", {"v": 2})
        self.cache.put("tmdbx", "sibling", {"v": 3})
        self.cache.put("tmdb_extra", "underscore", {"v": 4})
        self.cache.put("TMDB.child", "case", {"v": 5})
        self.cache.put("foo_bar", "root", {"v": 6})
        self.cache.put("foo_bar.child", "child", {"v": 7})
        self.cache.put("fooXbar.child", "wildcard-lookalike", {"v": 8})

        tmdb_stats = self.cache.stats(namespace_prefix="tmdb")
        foo_bar_stats = self.cache.stats(namespace_prefix="foo_bar")

        self.assertEqual(tmdb_stats["item_count"], 2)
        self.assertEqual(foo_bar_stats["item_count"], 2)

    def test_invalidate_by_prefix(self):
        self.cache.put("ns", "show::123::s1", {"v": 1})
        self.cache.put("ns", "show::123::s2", {"v": 2})
        self.cache.put("ns", "show::456::s1", {"v": 3})
        deleted = self.cache.invalidate_by_prefix("ns", "show::123")
        self.assertEqual(deleted, 2)
        self.assertFalse(self.cache.get("ns", "show::123::s1").is_hit)
        self.assertTrue(self.cache.get("ns", "show::456::s1").is_hit)

    def test_eviction_by_max_items(self):
        cache = PersistentCacheService(db_path=self.db_path, max_items=3)
        for i in range(5):
            cache.put("ns", f"key{i}", {"i": i})
        stats = cache.stats()
        self.assertLessEqual(stats["item_count"], 3)
        # Most recent entries should survive
        self.assertTrue(cache.get("ns", "key4").is_hit)

    def test_stats_accuracy(self):
        self.cache.put("ns", "key1", {"data": "hello"})
        self.cache.put("ns", "key2", {"data": "world"})
        stats = self.cache.stats()
        self.assertEqual(stats["item_count"], 2)
        self.assertGreater(stats["total_size_bytes"], 0)
        self.assertEqual(stats["max_items"], 200_000)

    def test_make_key_normalizes_backslashes(self):
        key = PersistentCacheService.make_key("C:\\library\\tv", "show")
        self.assertNotIn("\\", key)
        self.assertEqual(key, "C:/library/tv::show")

    def test_metadata_persisted_on_entry(self):
        self.cache.put("ns", "key1", {"v": 1}, metadata={"poster_path": "/poster.jpg"})
        lookup = self.cache.get("ns", "key1")
        self.assertEqual(lookup.entry.metadata, {"poster_path": "/poster.jpg"})

    def test_default_cache_size_is_one_gib(self):
        cache = PersistentCacheService(db_path=self.db_path)
        self.assertEqual(cache.stats()["max_size_bytes"], 1024**3)

    def test_set_max_size_bytes_updates_and_prunes(self):
        cache = PersistentCacheService(db_path=self.db_path, max_size_bytes=10**9)
        for i in range(50):
            cache.put("ns", f"k{i}", {"blob": "x" * 1000})
        cache.set_max_size_bytes(5000)  # tiny cap forces eviction
        self.assertLessEqual(cache.stats()["total_size_bytes"], 5000)
        self.assertEqual(cache.stats()["max_size_bytes"], 5000)

    def test_put_clears_refreshing_flag(self):
        now = _utc()
        future = (now + timedelta(days=30)).isoformat()
        self.cache.put("ns", "key1", {"v": 1}, refreshed_at=now.isoformat(), expires_at=future)
        self.cache.mark_refreshing("ns", "key1", True)
        # Re-put should clear refreshing
        self.cache.put("ns", "key1", {"v": 2}, refreshed_at=now.isoformat(), expires_at=future)
        lookup = self.cache.get("ns", "key1", now=now + timedelta(hours=1))
        self.assertNotEqual(lookup.state, RefreshState.REFRESHING)
        self.assertEqual(lookup.value, {"v": 2})


if __name__ == "__main__":
    unittest.main()
