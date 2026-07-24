"""Provider attribution on ScanState."""

from pathlib import Path
from typing import Any

from plex_renamer.engine.models import ScanState
from plex_renamer.metadata_types import MediaInfo


def test_scan_state_accepts_scalar_media_records(tmp_path: Path) -> None:
    record: MediaInfo = {
        "id": 7,
        "name": "Show",
        "year": "2020",
        "poster_path": None,
        "overview": "",
    }
    state = ScanState(
        folder=tmp_path,
        media_info=record,
        search_results=[record],
        alternate_matches=[record],
    )
    assert state.show_id == 7
    assert state.display_name == "Show (2020)"


def _state(**kwargs: Any) -> ScanState:
    return ScanState(folder=Path("Show"), media_info={"id": 42, "name": "Show"}, **kwargs)


def test_provider_defaults_to_tmdb() -> None:
    assert _state().provider_name == "tmdb"


def test_provider_show_key() -> None:
    assert _state(provider_name="tvdb").provider_show_key == ("tvdb", 42)
    unmatched = ScanState(folder=Path("Show"), media_info={"id": None, "name": "Show"})
    assert unmatched.provider_show_key is None


def test_fallback_origin_always_needs_review() -> None:
    state = _state(match_origin="fallback", confidence=0.99)
    assert state.needs_review is True


def test_id_tag_origin_auto_accepts() -> None:
    state = _state(match_origin="id_tag", confidence=1.0)
    assert state.needs_review is False
