"""Unit tests for RefreshPolicyService — TTL policies, freshness, cooldowns."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.models import RefreshState
from plex_renamer.app.services.refresh_policy_service import (
    ManualRefreshDecision,
    RefreshPolicyService,
)
from plex_renamer.constants import MediaType


def _utc(offset_hours: float = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=offset_hours)


class RefreshPolicyServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = RefreshPolicyService()

    # -- get_metadata_ttl ----------------------------------------------------

    def test_movie_ttl_is_30_days(self):
        ttl = self.svc.get_metadata_ttl(MediaType.MOVIE)
        self.assertEqual(ttl, timedelta(days=30))

    def test_active_tv_ttl_is_12_hours(self):
        for status in ("Returning Series", "In Production", "Planned", "Pilot"):
            ttl = self.svc.get_metadata_ttl(MediaType.TV, show_status=status)
            self.assertEqual(ttl, timedelta(hours=12), f"Failed for status: {status}")

    def test_inactive_tv_ttl_is_30_days(self):
        for status in ("Ended", "Canceled", "Cancelled"):
            ttl = self.svc.get_metadata_ttl(MediaType.TV, show_status=status)
            self.assertEqual(ttl, timedelta(days=30), f"Failed for status: {status}")

    def test_unknown_tv_ttl_is_7_days(self):
        ttl = self.svc.get_metadata_ttl(MediaType.TV, show_status=None)
        self.assertEqual(ttl, timedelta(days=7))
        ttl2 = self.svc.get_metadata_ttl(MediaType.TV, show_status="")
        self.assertEqual(ttl2, timedelta(days=7))

    def test_custom_ttl_overrides_defaults(self):
        svc = RefreshPolicyService(movie_ttl=timedelta(days=1))
        self.assertEqual(svc.get_metadata_ttl(MediaType.MOVIE), timedelta(days=1))

    # -- build_expiry --------------------------------------------------------

    def test_build_expiry_adds_ttl_to_refreshed_at(self):
        base = _utc()
        expiry = self.svc.build_expiry(
            refreshed_at=base.isoformat(),
            media_type=MediaType.MOVIE,
        )
        expected = (base + timedelta(days=30)).isoformat()
        self.assertEqual(expiry, expected)

    def test_build_expiry_accepts_datetime_object(self):
        base = _utc()
        expiry = self.svc.build_expiry(
            refreshed_at=base,
            media_type=MediaType.TV,
            show_status="Returning Series",
        )
        expected = (base + timedelta(hours=12)).isoformat()
        self.assertEqual(expiry, expected)

    # -- get_refresh_state ---------------------------------------------------

    def test_missing_when_no_refreshed_at(self):
        state = self.svc.get_refresh_state(refreshed_at=None, expires_at=None)
        self.assertEqual(state, RefreshState.MISSING)

    def test_refreshing_when_flagged(self):
        now = _utc()
        state = self.svc.get_refresh_state(
            refreshed_at=now.isoformat(),
            expires_at=(now + timedelta(days=1)).isoformat(),
            is_refreshing=True,
            now=now,
        )
        self.assertEqual(state, RefreshState.REFRESHING)

    def test_fresh_when_not_expired(self):
        now = _utc()
        state = self.svc.get_refresh_state(
            refreshed_at=(now - timedelta(hours=1)).isoformat(),
            expires_at=(now + timedelta(days=1)).isoformat(),
            now=now,
        )
        self.assertEqual(state, RefreshState.FRESH)

    def test_stale_when_expired(self):
        now = _utc()
        state = self.svc.get_refresh_state(
            refreshed_at=(now - timedelta(days=2)).isoformat(),
            expires_at=(now - timedelta(days=1)).isoformat(),
            now=now,
        )
        self.assertEqual(state, RefreshState.STALE)

    def test_recently_refreshed_within_window(self):
        now = _utc()
        state = self.svc.get_refresh_state(
            refreshed_at=(now - timedelta(minutes=2)).isoformat(),
            expires_at=(now + timedelta(days=1)).isoformat(),
            now=now,
        )
        self.assertEqual(state, RefreshState.RECENTLY_REFRESHED)

    def test_fresh_when_no_expiry(self):
        now = _utc()
        state = self.svc.get_refresh_state(
            refreshed_at=now.isoformat(),
            expires_at=None,
            now=now,
        )
        self.assertEqual(state, RefreshState.FRESH)

    # -- should_background_refresh -------------------------------------------

    def test_should_refresh_when_missing(self):
        self.assertTrue(
            self.svc.should_background_refresh(refreshed_at=None, expires_at=None)
        )

    def test_should_refresh_when_stale(self):
        now = _utc()
        self.assertTrue(
            self.svc.should_background_refresh(
                refreshed_at=(now - timedelta(days=2)).isoformat(),
                expires_at=(now - timedelta(days=1)).isoformat(),
                now=now,
            )
        )

    def test_should_not_refresh_when_fresh(self):
        now = _utc()
        self.assertFalse(
            self.svc.should_background_refresh(
                refreshed_at=(now - timedelta(hours=1)).isoformat(),
                expires_at=(now + timedelta(days=1)).isoformat(),
                now=now,
            )
        )

    def test_should_not_refresh_when_already_refreshing(self):
        now = _utc()
        self.assertFalse(
            self.svc.should_background_refresh(
                refreshed_at=(now - timedelta(days=2)).isoformat(),
                expires_at=(now - timedelta(days=1)).isoformat(),
                is_refreshing=True,
                now=now,
            )
        )

    # -- can_manual_refresh --------------------------------------------------

    def test_manual_refresh_allowed_when_no_prior(self):
        decision = self.svc.can_manual_refresh(None)
        self.assertTrue(decision.allowed)

    def test_manual_refresh_allowed_after_cooldown(self):
        now = _utc()
        decision = self.svc.can_manual_refresh(
            (now - timedelta(minutes=20)).isoformat(),
            now=now,
        )
        self.assertTrue(decision.allowed)

    def test_manual_refresh_blocked_during_cooldown(self):
        now = _utc()
        decision = self.svc.can_manual_refresh(
            (now - timedelta(minutes=5)).isoformat(),
            now=now,
        )
        self.assertFalse(decision.allowed)
        self.assertGreater(decision.retry_after_seconds, 0)

    def test_manual_refresh_custom_cooldown(self):
        svc = RefreshPolicyService(manual_refresh_cooldown=timedelta(minutes=1))
        now = _utc()
        decision = svc.can_manual_refresh(
            (now - timedelta(minutes=2)).isoformat(),
            now=now,
        )
        self.assertTrue(decision.allowed)

    # -- get_rescan_scope ----------------------------------------------------

    def test_rescan_scope_returns_first_subdirectory(self):
        with TemporaryDirectory() as tmp:
            lib = Path(tmp)
            show_dir = lib / "Show" / "Season 01"
            show_dir.mkdir(parents=True)
            ep = show_dir / "ep.mkv"
            ep.touch()
            result = self.svc.get_rescan_scope(lib, ep)
            self.assertEqual(result, lib / "Show")

    def test_rescan_scope_returns_library_root_for_root_change(self):
        with TemporaryDirectory() as tmp:
            lib = Path(tmp)
            result = self.svc.get_rescan_scope(lib, lib)
            self.assertEqual(result, lib)

    def test_rescan_scope_returns_library_root_for_outside_path(self):
        with TemporaryDirectory() as tmp:
            lib = Path(tmp) / "library"
            lib.mkdir()
            outside = Path(tmp) / "other" / "file.mkv"
            result = self.svc.get_rescan_scope(lib, outside)
            self.assertEqual(result, lib)


if __name__ == "__main__":
    unittest.main()
