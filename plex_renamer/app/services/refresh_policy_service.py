"""Refresh policy rules for metadata TTLs, cooldowns, and rescan scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...constants import MediaType
from ..models import RefreshState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(slots=True)
class ManualRefreshDecision:
    allowed: bool
    reason: str
    retry_after_seconds: int = 0


class RefreshPolicyService:
    """Central refresh policy rules, independent of any GUI toolkit."""

    def __init__(
        self,
        *,
        movie_ttl: timedelta | None = None,
        active_tv_ttl: timedelta | None = None,
        inactive_tv_ttl: timedelta | None = None,
        unknown_tv_ttl: timedelta | None = None,
        recent_window: timedelta | None = None,
        manual_refresh_cooldown: timedelta | None = None,
    ):
        self._movie_ttl = movie_ttl or timedelta(days=30)
        self._active_tv_ttl = active_tv_ttl or timedelta(hours=12)
        self._inactive_tv_ttl = inactive_tv_ttl or timedelta(days=30)
        self._unknown_tv_ttl = unknown_tv_ttl or timedelta(days=7)
        self._recent_window = recent_window or timedelta(minutes=5)
        self._manual_refresh_cooldown = manual_refresh_cooldown or timedelta(minutes=15)

    def get_metadata_ttl(self, media_type: str, show_status: str | None = None) -> timedelta:
        """Return the TTL for a metadata record based on media type and show status."""
        if media_type == MediaType.MOVIE:
            return self._movie_ttl

        status = (show_status or "").strip().lower()
        if status in {"returning series", "in production", "planned", "pilot"}:
            return self._active_tv_ttl
        if status in {"ended", "canceled", "cancelled"}:
            return self._inactive_tv_ttl
        return self._unknown_tv_ttl

    def build_expiry(
        self,
        *,
        refreshed_at: str | datetime | None,
        media_type: str,
        show_status: str | None = None,
    ) -> str:
        """Return the cache expiry timestamp for a refreshed metadata record."""
        if isinstance(refreshed_at, str):
            base = _parse_dt(refreshed_at)
        else:
            base = refreshed_at
        base = base or _utc_now()
        return (base + self.get_metadata_ttl(media_type, show_status)).isoformat()

    def get_refresh_state(
        self,
        *,
        refreshed_at: str | None,
        expires_at: str | None,
        is_refreshing: bool = False,
        now: datetime | None = None,
    ) -> RefreshState:
        """Classify freshness for cached content."""
        if refreshed_at is None:
            return RefreshState.MISSING
        if is_refreshing:
            return RefreshState.REFRESHING

        now = now or _utc_now()
        refreshed_dt = _parse_dt(refreshed_at)
        expires_dt = _parse_dt(expires_at)
        if expires_dt is None:
            return RefreshState.FRESH
        if expires_dt <= now:
            return RefreshState.STALE
        if refreshed_dt is not None and (now - refreshed_dt) <= self._recent_window:
            return RefreshState.RECENTLY_REFRESHED
        return RefreshState.FRESH

    def should_background_refresh(
        self,
        *,
        refreshed_at: str | None,
        expires_at: str | None,
        is_refreshing: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """Return True when stale data should refresh in the background."""
        state = self.get_refresh_state(
            refreshed_at=refreshed_at,
            expires_at=expires_at,
            is_refreshing=is_refreshing,
            now=now,
        )
        return state in {RefreshState.MISSING, RefreshState.STALE}

    def can_manual_refresh(
        self,
        last_manual_refresh_at: str | None,
        *,
        now: datetime | None = None,
    ) -> ManualRefreshDecision:
        """Apply the manual refresh cooldown so users cannot hammer TMDB."""
        now = now or _utc_now()
        last_refresh = _parse_dt(last_manual_refresh_at)
        if last_refresh is None:
            return ManualRefreshDecision(True, "Manual refresh available.")

        elapsed = now - last_refresh
        if elapsed >= self._manual_refresh_cooldown:
            return ManualRefreshDecision(True, "Manual refresh available.")

        retry_after = int((self._manual_refresh_cooldown - elapsed).total_seconds())
        return ManualRefreshDecision(
            False,
            "Manual refresh is cooling down.",
            retry_after_seconds=max(0, retry_after),
        )

    def get_rescan_scope(self, library_root: Path, changed_path: Path) -> Path:
        """Return the narrowest subdirectory that should be rescanned for integrity."""
        library_root = library_root.resolve()
        changed_path = changed_path.resolve()
        if changed_path == library_root:
            return library_root
        if changed_path.is_file():
            changed_path = changed_path.parent
        try:
            relative = changed_path.relative_to(library_root)
        except ValueError:
            return library_root
        if not relative.parts:
            return library_root
        return library_root / relative.parts[0]