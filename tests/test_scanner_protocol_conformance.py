"""Static conformance proof: concrete scanners satisfy the ScanState capability protocols.

The app layer widens ``ScanState.scanner`` with ``cast()`` at its boundaries
(deliberate design; see 2026-07 audit debt notes). Those casts are safe only
while the concrete scanners structurally satisfy the protocols — pyright
checks that here, so drift fails the type ratchet instead of erupting at
runtime.
"""

from plex_renamer.engine._movie_scanner import MovieScanner
from plex_renamer.engine._tv_scanner import TVScanner
from plex_renamer.engine.models import (
    MovieScanStateScanner,
    TVScannerOperations,
    TVScanStateScanner,
)


def _tv_metadata_conforms(scanner: TVScanner) -> TVScanStateScanner:
    return scanner


def _tv_operations_conform(scanner: TVScanner) -> TVScannerOperations:
    return scanner


def _movie_conforms(scanner: MovieScanner) -> MovieScanStateScanner:
    return scanner


def test_conformance_witnesses_are_intact() -> None:
    assert callable(_tv_metadata_conforms)
    assert callable(_tv_operations_conform)
    assert callable(_movie_conforms)
