"""Persistence for scan snapshots so sessions can be restored safely."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...constants import MediaType, SCAN_SNAPSHOT_FILE, ensure_log_dir
from ...engine import CompletenessReport, PreviewItem, ScanState, SeasonCompleteness


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SnapshotEnvelope:
    snapshot_id: str
    media_type: str
    library_root: str
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    states: list[dict[str, Any]] = field(default_factory=list)


class ScanSnapshotService:
    """Persist and restore serializable ScanState snapshots."""

    def __init__(self, snapshot_file: Path | None = None):
        self._snapshot_file = snapshot_file or SCAN_SNAPSHOT_FILE

    def save_snapshot(
        self,
        snapshot_id: str,
        *,
        media_type: str,
        library_root: Path,
        states: list[ScanState],
    ) -> SnapshotEnvelope:
        """Persist a batch or single-session scan snapshot."""
        payload = self._load_payload()
        snapshots = payload["snapshots"]
        envelope = SnapshotEnvelope(
            snapshot_id=snapshot_id,
            media_type=media_type,
            library_root=str(library_root),
            states=[self._serialize_state(state) for state in states],
        )
        if snapshot_id in snapshots:
            envelope.created_at = snapshots[snapshot_id].get("created_at", envelope.created_at)
        snapshots[snapshot_id] = asdict(envelope)
        self._save_payload(payload)
        return envelope

    def set_active_snapshot_id(self, snapshot_id: str | None) -> None:
        """Record which snapshot should be restored first on startup."""
        payload = self._load_payload()
        payload["active_snapshot_id"] = snapshot_id
        self._save_payload(payload)

    def get_active_snapshot_id(self) -> str | None:
        """Return the snapshot id marked as the preferred restore target."""
        payload = self._load_payload()
        return payload.get("active_snapshot_id")

    def load_snapshot(self, snapshot_id: str) -> SnapshotEnvelope | None:
        """Load a stored snapshot envelope by id."""
        payload = self._load_payload()
        record = payload["snapshots"].get(snapshot_id)
        if record is None:
            return None
        return SnapshotEnvelope(**record)

    def restore_states(self, snapshot_id: str) -> tuple[str, Path, list[ScanState]] | None:
        """Restore ScanState objects from a persisted snapshot."""
        envelope = self.load_snapshot(snapshot_id)
        if envelope is None:
            return None
        states = [self._deserialize_state(record) for record in envelope.states]
        return envelope.media_type, Path(envelope.library_root), states

    def list_snapshots(self) -> list[SnapshotEnvelope]:
        """Return all stored snapshots in update order."""
        payload = self._load_payload()
        envelopes = [SnapshotEnvelope(**record) for record in payload["snapshots"].values()]
        envelopes.sort(key=lambda item: item.updated_at, reverse=True)
        return envelopes

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a persisted snapshot if it exists."""
        payload = self._load_payload()
        if snapshot_id not in payload["snapshots"]:
            return False
        del payload["snapshots"][snapshot_id]
        if payload.get("active_snapshot_id") == snapshot_id:
            payload["active_snapshot_id"] = None
        self._save_payload(payload)
        return True

    def _load_payload(self) -> dict[str, Any]:
        ensure_log_dir()
        if not self._snapshot_file.exists():
            return {"active_snapshot_id": None, "snapshots": {}}
        raw = json.loads(self._snapshot_file.read_text(encoding="utf-8"))
        if "snapshots" in raw:
            return {
                "active_snapshot_id": raw.get("active_snapshot_id"),
                "snapshots": raw.get("snapshots", {}),
            }
        return {"active_snapshot_id": None, "snapshots": raw}

    def _save_payload(self, payload: dict[str, Any]) -> None:
        ensure_log_dir()
        self._snapshot_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _serialize_state(self, state: ScanState) -> dict[str, Any]:
        return {
            "folder": str(state.folder),
            "media_info": state.media_info,
            "preview_items": [self._serialize_item(item) for item in state.preview_items],
            "completeness": self._serialize_completeness(state.completeness),
            "confidence": state.confidence,
            "alternate_matches": state.alternate_matches,
            "search_results": state.search_results,
            "scanned": state.scanned,
            "scanning": state.scanning,
            "checked": state.checked,
            "duplicate_of": state.duplicate_of,
            "queued": state.queued,
        }

    def _deserialize_state(self, payload: dict[str, Any]) -> ScanState:
        preview_items = [
            self._deserialize_item(item)
            for item in payload.get("preview_items", [])
        ]
        completeness = self._deserialize_completeness(payload.get("completeness"))
        scanning = bool(payload.get("scanning", False))
        scanned = bool(payload.get("scanned", False))
        if not scanned and not scanning and (preview_items or completeness is not None):
            scanned = True

        state = ScanState(
            folder=Path(payload["folder"]),
            media_info=payload["media_info"],
            preview_items=preview_items,
            completeness=completeness,
            confidence=payload.get("confidence", 0.0),
            alternate_matches=list(payload.get("alternate_matches", [])),
            search_results=list(payload.get("search_results", [])),
            scanned=scanned,
            scanning=scanning,
            checked=bool(payload.get("checked", True)),
            duplicate_of=payload.get("duplicate_of"),
            queued=bool(payload.get("queued", False)),
        )
        return state

    @staticmethod
    def _serialize_item(item: PreviewItem) -> dict[str, Any]:
        return {
            "original": str(item.original),
            "new_name": item.new_name,
            "target_dir": str(item.target_dir) if item.target_dir is not None else None,
            "season": item.season,
            "episodes": list(item.episodes),
            "status": item.status,
            "media_type": item.media_type,
            "media_id": item.media_id,
            "media_name": item.media_name,
        }

    @staticmethod
    def _deserialize_item(payload: dict[str, Any]) -> PreviewItem:
        return PreviewItem(
            original=Path(payload["original"]),
            new_name=payload.get("new_name"),
            target_dir=Path(payload["target_dir"]) if payload.get("target_dir") else None,
            season=payload.get("season"),
            episodes=list(payload.get("episodes", [])),
            status=payload.get("status", "OK"),
            media_type=payload.get("media_type", MediaType.TV),
            media_id=payload.get("media_id"),
            media_name=payload.get("media_name"),
        )

    @staticmethod
    def _serialize_completeness(report: CompletenessReport | None) -> dict[str, Any] | None:
        if report is None:
            return None
        return {
            "seasons": {
                str(season): {
                    "season": data.season,
                    "expected": data.expected,
                    "matched": data.matched,
                    "missing": [list(item) for item in data.missing],
                    "matched_episodes": [list(item) for item in data.matched_episodes],
                }
                for season, data in report.seasons.items()
            },
            "specials": None if report.specials is None else {
                "season": report.specials.season,
                "expected": report.specials.expected,
                "matched": report.specials.matched,
                "missing": [list(item) for item in report.specials.missing],
                "matched_episodes": [list(item) for item in report.specials.matched_episodes],
            },
            "total_expected": report.total_expected,
            "total_matched": report.total_matched,
            "total_missing": [list(item) for item in report.total_missing],
        }

    @staticmethod
    def _deserialize_completeness(payload: dict[str, Any] | None) -> CompletenessReport | None:
        if payload is None:
            return None
        seasons = {
            int(season): SeasonCompleteness(
                season=data["season"],
                expected=data["expected"],
                matched=data["matched"],
                missing=[tuple(item) for item in data.get("missing", [])],
                matched_episodes=[tuple(item) for item in data.get("matched_episodes", [])],
            )
            for season, data in payload.get("seasons", {}).items()
        }
        specials_payload = payload.get("specials")
        specials = None
        if specials_payload is not None:
            specials = SeasonCompleteness(
                season=specials_payload["season"],
                expected=specials_payload["expected"],
                matched=specials_payload["matched"],
                missing=[tuple(item) for item in specials_payload.get("missing", [])],
                matched_episodes=[tuple(item) for item in specials_payload.get("matched_episodes", [])],
            )
        return CompletenessReport(
            seasons=seasons,
            specials=specials,
            total_expected=payload.get("total_expected", 0),
            total_matched=payload.get("total_matched", 0),
            total_missing=[tuple(item) for item in payload.get("total_missing", [])],
        )