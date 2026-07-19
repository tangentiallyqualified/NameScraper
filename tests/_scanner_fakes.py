"""Shared test double for the TVScanStateScanner metadata capability."""

from collections.abc import Mapping


class MetadataScannerFake:
    """Minimal ScanState.scanner stand-in exposing only episode_meta."""

    def __init__(
        self, episode_meta: Mapping[tuple[int, int], Mapping[str, object]] | None = None
    ) -> None:
        self._episode_meta = dict(episode_meta or {})

    @property
    def episode_meta(self) -> Mapping[tuple[int, int], Mapping[str, object]]:
        return self._episode_meta
