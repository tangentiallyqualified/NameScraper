"""First-class file<->episode assignment table for TV scans.

The table is the source of truth for the scan/preview layer. ``PreviewItem``
rows are projected from it (see ``_episode_projection``); nothing outside the
projection mints episode status strings.

Claims are stored per file but queried per slot as a *list*: policy, not
schema, decides what multiple claims on one slot mean. Today 2+ claims is a
conflict; a future duplicates policy may treat extra claims as library
(Plex/Jellyfin) "versions" via ``Assignment.role`` without a data migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"
ROLE_PRIMARY = "primary"
ROLE_VERSION = "version"  # reserved for future duplicate support

REASON_NO_PARSE = "could not parse episode number"
REASON_NO_TITLE_MATCH = "no TMDB title match"
REASON_NOT_IN_SEASON = "episode not in TMDB season"
REASON_LOST_CONFLICT = "lost conflict"


def lost_conflict_reason(season: int, episode: int) -> str:
    """Lost-conflict reason naming the slot the file lost the match for."""
    return f"{REASON_LOST_CONFLICT} for S{season:02d}E{episode:02d}"


REASON_DUPLICATE_COPY = "duplicate copy"


def duplicate_copy_reason(season: int, episode: int) -> str:
    """Reason marking a losing duplicate copy of one episode."""
    return f"{REASON_DUPLICATE_COPY} of S{season:02d}E{episode:02d}"


REASON_DISPLACED = "reassigned to another file"
REASON_MANUAL_UNASSIGN = "manually unassigned"
REASON_AMBIGUOUS_RUN = "ambiguous multi-episode numbering"


@dataclass(frozen=True, slots=True)
class EpisodeSlot:
    """One TMDB episode (including Season 0 specials)."""

    season: int
    episode: int
    title: str = ""
    air_date: str = ""
    overview: str = ""

    @property
    def key(self) -> tuple[int, int]:
        return (self.season, self.episode)


@dataclass(slots=True)
class FileEntry:
    """One discovered video file with its scan-time parse evidence.

    Evidence fields are written once at scan time and never mutated by
    fixes; manual operations only change the file's ``Assignment``.
    """

    file_id: int
    path: Path
    parsed_episodes: tuple[int, ...] = ()
    raw_title: str | None = None
    is_season_relative: bool = False
    season_hint: int | None = None
    folder_season: int | None = None
    from_extras_folder: bool = False
    source_relative_folder: str = ""


@dataclass(slots=True)
class Assignment:
    """Links one file to 1..N contiguous episodes in a single season."""

    file_id: int
    season: int
    episodes: tuple[int, ...]
    origin: str
    confidence: float
    role: str = ROLE_PRIMARY
    evidence: frozenset[str] = field(default_factory=frozenset)
    approved: bool = False


class EpisodeAssignmentTable:
    """Per-show registry of files, episode slots, and claims."""

    def __init__(self) -> None:
        self.files: dict[int, FileEntry] = {}
        self.slots: dict[tuple[int, int], EpisodeSlot] = {}
        self.unassigned_reasons: dict[int, str] = {}
        self._assignments: dict[int, Assignment] = {}
        self._next_file_id = 0

    # ── registration ────────────────────────────────────────────────

    def add_slot(self, slot: EpisodeSlot) -> None:
        self.slots[slot.key] = slot

    def add_file(self, path: Path, **evidence) -> FileEntry:
        entry = FileEntry(file_id=self._next_file_id, path=path, **evidence)
        self.files[entry.file_id] = entry
        self._next_file_id += 1
        return entry

    # ── mutations ───────────────────────────────────────────────────

    def assign(
        self,
        file_id: int,
        season: int,
        episodes: list[int] | tuple[int, ...],
        *,
        origin: str,
        confidence: float = 1.0,
        evidence: frozenset[str] = frozenset(),
        displace: bool = False,
    ) -> Assignment:
        """Validate and record an assignment. Raises ValueError untouched on bad input."""
        entry = self.files.get(file_id)
        if entry is None:
            raise ValueError(f"Unknown file id {file_id}")
        episode_run = tuple(sorted(int(episode) for episode in episodes))
        if not episode_run:
            raise ValueError("An assignment needs at least one episode")
        if any(b - a != 1 for a, b in zip(episode_run, episode_run[1:])):
            raise ValueError(
                f"Episodes {list(episode_run)} are not a contiguous run"
            )
        missing = [e for e in episode_run if (season, e) not in self.slots]
        if missing:
            raise ValueError(
                f"Season {season} has no episode(s) {missing} in TMDB"
            )

        if displace:
            for other_id in [
                claim.file_id
                for episode in episode_run
                for claim in self.claims(season, episode)
                if claim.file_id != file_id
            ]:
                self._assignments.pop(other_id, None)
                self.unassigned_reasons[other_id] = REASON_DISPLACED

        if origin == ORIGIN_MANUAL:
            confidence = 1.0
        assignment = Assignment(
            file_id=file_id,
            season=season,
            episodes=episode_run,
            origin=origin,
            confidence=confidence,
            evidence=evidence,
        )
        self._assignments[file_id] = assignment
        self.unassigned_reasons.pop(file_id, None)
        return assignment

    def mark_unassigned(self, file_id: int, reason: str) -> None:
        if file_id not in self.files:
            raise ValueError(f"Unknown file id {file_id}")
        self._assignments.pop(file_id, None)
        self.unassigned_reasons[file_id] = reason

    def unassign(self, file_id: int, *, reason: str = REASON_MANUAL_UNASSIGN) -> None:
        self.mark_unassigned(file_id, reason)

    def resolve_conflict(self, season: int, episode: int, *, winner_file_id: int) -> None:
        claimants = self.claims(season, episode)
        if all(claim.file_id != winner_file_id for claim in claimants):
            raise ValueError(
                f"File {winner_file_id} does not claim S{season:02d}E{episode:02d}"
            )
        for claim in claimants:
            if claim.file_id != winner_file_id:
                self.mark_unassigned(
                    claim.file_id, lost_conflict_reason(season, episode),
                )

    def set_approved(self, file_id: int, approved: bool = True) -> None:
        assignment = self._assignments.get(file_id)
        if assignment is None:
            raise ValueError(f"File {file_id} has no assignment to approve")
        self._assignments[file_id] = replace(assignment, approved=approved)

    def set_confidence(self, file_id: int, confidence: float) -> None:
        assignment = self._assignments.get(file_id)
        if assignment is None:
            raise ValueError(f"File {file_id} has no assignment")
        clamped = max(0.0, min(1.0, confidence))
        self._assignments[file_id] = replace(assignment, confidence=clamped)

    # ── queries ─────────────────────────────────────────────────────

    def assignment_for(self, file_id: int) -> Assignment | None:
        return self._assignments.get(file_id)

    def assignments(self) -> list[Assignment]:
        return list(self._assignments.values())

    def claims(self, season: int, episode: int) -> list[Assignment]:
        return [
            assignment
            for assignment in self._assignments.values()
            if assignment.season == season and episode in assignment.episodes
        ]

    def claimed_slots(self) -> set[tuple[int, int]]:
        """Every (season, episode) slot currently claimed by an assignment."""
        return {
            (assignment.season, episode)
            for assignment in self._assignments.values()
            for episode in assignment.episodes
        }

    def conflicts(self) -> dict[tuple[int, int], list[Assignment]]:
        by_slot: dict[tuple[int, int], list[Assignment]] = {}
        for assignment in self._assignments.values():
            for episode in assignment.episodes:
                by_slot.setdefault((assignment.season, episode), []).append(assignment)
        return {key: claims for key, claims in by_slot.items() if len(claims) > 1}

    def conflicted_file_ids(self) -> set[int]:
        return {
            claim.file_id
            for claims in self.conflicts().values()
            for claim in claims
        }

    def claimant(self, season: int, episode: int) -> FileEntry | None:
        claims = self.claims(season, episode)
        if len(claims) != 1:
            return None
        return self.files[claims[0].file_id]

    def unassigned_files(self) -> list[tuple[FileEntry, str]]:
        return [
            (entry, self.unassigned_reasons.get(file_id, ""))
            for file_id, entry in sorted(self.files.items())
            if file_id not in self._assignments
        ]

    def unclaimed_slots(self) -> list[EpisodeSlot]:
        claimed: set[tuple[int, int]] = set()
        for assignment in self._assignments.values():
            for episode in assignment.episodes:
                claimed.add((assignment.season, episode))
        return [
            slot for key, slot in sorted(self.slots.items()) if key not in claimed
        ]


def ingest_preview_items(
    table: EpisodeAssignmentTable,
    items: list,
) -> None:
    """Ingest already-built PreviewItems (consolidated path) into a table.

    Sets ``item.file_id`` on each item so the GUI can address files.
    Assigned items become auto claims; everything else is unassigned with
    the item's status text as the reason.
    """
    from ..parsing import extract_episode, extract_season_number

    for item in items:
        episode_numbers, raw_title, is_season_relative = extract_episode(
            item.original.name,
        )
        entry = table.add_file(
            item.original,
            parsed_episodes=tuple(episode_numbers),
            raw_title=raw_title,
            is_season_relative=is_season_relative,
            season_hint=(
                extract_season_number(item.original.name)
                if is_season_relative else None
            ),
            folder_season=item.season,
            source_relative_folder=item.source_relative_folder,
        )
        item.file_id = entry.file_id
        if (
            item.season is not None
            and item.episodes
            and item.new_name is not None
            and not item.is_skipped
            and not item.is_unmatched
        ):
            valid = [
                episode for episode in item.episodes
                if (item.season, episode) in table.slots
            ]
            if valid == list(item.episodes):
                try:
                    table.assign(
                        entry.file_id,
                        item.season,
                        valid,
                        origin=ORIGIN_AUTO,
                        confidence=item.episode_confidence,
                        evidence=frozenset({"consolidated"}),
                    )
                    continue
                except ValueError:
                    pass  # non-contiguous run at a season boundary
        raw_reason = item.status or REASON_NO_PARSE
        # Strip a leading "SKIP: " prefix so projection doesn't double-mint it.
        if raw_reason.startswith("SKIP: "):
            raw_reason = raw_reason[len("SKIP: "):]
        table.mark_unassigned(entry.file_id, raw_reason)


def merge_tables(
    primary: EpisodeAssignmentTable,
    other: EpisodeAssignmentTable,
) -> dict[int, int]:
    """Absorb *other* into *primary*; returns old->new file id mapping."""
    id_map: dict[int, int] = {}
    for slot in other.slots.values():
        if slot.key not in primary.slots:
            primary.add_slot(slot)
    for old_id, entry in sorted(other.files.items()):
        new_entry = primary.add_file(
            entry.path,
            parsed_episodes=entry.parsed_episodes,
            raw_title=entry.raw_title,
            is_season_relative=entry.is_season_relative,
            season_hint=entry.season_hint,
            folder_season=entry.folder_season,
            from_extras_folder=entry.from_extras_folder,
            source_relative_folder=entry.source_relative_folder,
        )
        id_map[old_id] = new_entry.file_id
        assignment = other.assignment_for(old_id)
        if assignment is not None:
            new_assignment = primary.assign(
                new_entry.file_id,
                assignment.season,
                list(assignment.episodes),
                origin=assignment.origin,
                confidence=assignment.confidence,
                evidence=assignment.evidence,
            )
            if assignment.role != new_assignment.role:
                primary._assignments[new_entry.file_id] = replace(
                    new_assignment, role=assignment.role,
                )
            if assignment.approved:
                primary.set_approved(new_entry.file_id)
        else:
            primary.mark_unassigned(
                new_entry.file_id, other.unassigned_reasons.get(old_id, ""),
            )
    return id_map


def carry_over_manual_assignments(
    old: EpisodeAssignmentTable,
    new: EpisodeAssignmentTable,
) -> None:
    """Re-apply manual assignments from a previous scan of the SAME show.

    Matches files by path. Files that vanished or episodes no longer in
    TMDB are skipped silently (the rescan reflects current reality).
    Spec: manual assignments survive re-scans of the same show match;
    a rematch to a different show id discards the old table entirely.
    """
    new_by_path = {entry.path: entry.file_id for entry in new.files.values()}
    for assignment in old.assignments():
        if assignment.origin != ORIGIN_MANUAL:
            continue
        entry = old.files[assignment.file_id]
        new_id = new_by_path.get(entry.path)
        if new_id is None:
            continue
        try:
            new.assign(
                new_id,
                assignment.season,
                list(assignment.episodes),
                origin=ORIGIN_MANUAL,
                displace=True,
            )
        except ValueError:
            continue
