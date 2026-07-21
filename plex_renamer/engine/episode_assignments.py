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

import itertools
from dataclasses import dataclass, field, replace
from pathlib import Path

ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"
ROLE_PRIMARY = "primary"
ROLE_VERSION = "version"  # reserved for future duplicate support
ROLE_PART = "part"  # member 2+ of a multi-file (split) episode group

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
    part_marker: int | None = None  # 1-based part number parsed from the stem


@dataclass(slots=True)
class Assignment:
    """Links one file to 1..N contiguous episodes in a single season."""

    file_id: int
    season: int
    episodes: tuple[int, ...]
    origin: str
    confidence: float
    role: str = ROLE_PRIMARY
    # 1-based position within a part group (primary=1); 0 = not grouped.
    part_order: int = 0
    # Identity of the part group this assignment belongs to; 0 = not grouped.
    # Distinguishes two independent groups that happen to target the same slot.
    part_group: int = 0
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
        self._next_part_group = 1

    # ── registration ────────────────────────────────────────────────

    def add_slot(self, slot: EpisodeSlot) -> None:
        self.slots[slot.key] = slot

    def add_file(
        self,
        path: Path,
        *,
        parsed_episodes: tuple[int, ...] = (),
        raw_title: str | None = None,
        is_season_relative: bool = False,
        season_hint: int | None = None,
        folder_season: int | None = None,
        from_extras_folder: bool = False,
        source_relative_folder: str = "",
        part_marker: int | None = None,
    ) -> FileEntry:
        entry = FileEntry(
            file_id=self._next_file_id,
            path=path,
            parsed_episodes=parsed_episodes,
            raw_title=raw_title,
            is_season_relative=is_season_relative,
            season_hint=season_hint,
            folder_season=folder_season,
            from_extras_folder=from_extras_folder,
            source_relative_folder=source_relative_folder,
            part_marker=part_marker,
        )
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
        if any(b - a != 1 for a, b in itertools.pairwise(episode_run)):
            raise ValueError(f"Episodes {list(episode_run)} are not a contiguous run")
        missing = [e for e in episode_run if (season, e) not in self.slots]
        if missing:
            raise ValueError(f"Season {season} has no episode(s) {missing} in TMDB")

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
            raise ValueError(f"File {winner_file_id} does not claim S{season:02d}E{episode:02d}")
        for claim in claimants:
            if claim.file_id != winner_file_id:
                self.mark_unassigned(
                    claim.file_id,
                    lost_conflict_reason(season, episode),
                )

    def group_parts(
        self,
        ordered_file_ids: list[int],
        season: int,
        episodes: list[int] | tuple[int, ...],
        *,
        origin: str,
        confidence: float = 1.0,
    ) -> None:
        """Assign *ordered_file_ids* to the same slot(s) as one part group.

        The first id becomes the primary carrier; the rest become
        role="part" claims. Policy (conflicts/claimant/projection) treats
        the set as one logical claim.
        """
        if len(ordered_file_ids) < 2:
            raise ValueError("A part group needs at least two files")
        if len(set(ordered_file_ids)) != len(ordered_file_ids):
            raise ValueError(f"Duplicate file id(s) in part group {ordered_file_ids}")
        missing = [i for i in ordered_file_ids if i not in self.files]
        if missing:
            raise ValueError(f"Unknown file id(s) {missing}")
        group_id = self._next_part_group
        self._next_part_group += 1
        for order, file_id in enumerate(ordered_file_ids, start=1):
            assignment = self.assign(
                file_id,
                season,
                list(episodes),
                origin=origin,
                confidence=confidence,
            )
            self._assignments[file_id] = replace(
                assignment,
                role=ROLE_PRIMARY if order == 1 else ROLE_PART,
                part_order=order,
                part_group=group_id,
            )

    def ungroup_parts(self, file_id: int) -> None:
        """Dissolve the group containing *file_id*: every member reverts to
        an independent primary claim (the normal conflict flow applies)."""
        for member in self.part_group_members(file_id):
            self._assignments[member.file_id] = replace(
                member, role=ROLE_PRIMARY, part_order=0, part_group=0
            )

    def part_group_members(self, file_id: int) -> list[Assignment]:
        """All assignments in *file_id*'s part group, ordered by part_order;
        empty when the file is not part of a group."""
        own = self._assignments.get(file_id)
        if own is None or own.part_order == 0:
            return []
        members = [
            a
            for a in self._assignments.values()
            if a.part_group == own.part_group and a.part_order > 0
        ]
        return sorted(members, key=lambda a: a.part_order)

    def set_approved(self, file_id: int, approved: bool = True) -> None:
        assignment = self._assignments.get(file_id)
        if assignment is None:
            raise ValueError(f"File {file_id} has no assignment to approve")
        targets = self.part_group_members(file_id) or [assignment]
        for member in targets:
            self._assignments[member.file_id] = replace(member, approved=approved)

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

    def logical_claims(self, season: int, episode: int) -> list[list[Assignment]]:
        """Claims on a slot, grouped: a primary and its part-role claims
        form ONE logical claim (list ordered by part_order); ungrouped
        claims are singleton groups."""
        raw = self.claims(season, episode)
        grouped: dict[int, list[Assignment]] = {}
        singles: list[list[Assignment]] = []
        for claim in raw:
            if claim.part_order > 0:
                grouped.setdefault(claim.part_group, []).append(claim)
            else:
                singles.append([claim])
        for group in grouped.values():
            group.sort(key=lambda a: a.part_order)
        return list(grouped.values()) + singles

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
        return {
            key: claims for key, claims in by_slot.items() if len(self.logical_claims(*key)) > 1
        }

    def conflicted_file_ids(self) -> set[int]:
        return {claim.file_id for claims in self.conflicts().values() for claim in claims}

    def claimant(self, season: int, episode: int) -> FileEntry | None:
        logical = self.logical_claims(season, episode)
        if len(logical) != 1:
            return None
        return self.files[logical[0][0].file_id]

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
        return [slot for key, slot in sorted(self.slots.items()) if key not in claimed]


def merge_tables(
    primary: EpisodeAssignmentTable,
    other: EpisodeAssignmentTable,
) -> dict[int, int]:
    """Absorb *other* into *primary*; returns old->new file id mapping."""
    id_map: dict[int, int] = {}
    group_id_map: dict[int, int] = {}
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
            part_marker=entry.part_marker,
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
            if assignment.role != new_assignment.role or assignment.part_order:
                mapped_group = 0
                if assignment.part_group:
                    mapped_group = group_id_map.get(assignment.part_group, 0)
                    if not mapped_group:
                        mapped_group = primary._next_part_group
                        primary._next_part_group += 1
                        group_id_map[assignment.part_group] = mapped_group
                primary._assignments[new_entry.file_id] = replace(
                    new_assignment,
                    role=assignment.role,
                    part_order=assignment.part_order,
                    part_group=mapped_group,
                )
            if assignment.approved:
                primary.set_approved(new_entry.file_id)
        else:
            primary.mark_unassigned(
                new_entry.file_id,
                other.unassigned_reasons.get(old_id, ""),
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

    Manual part groups are carried atomically: either every member of the
    group re-lands on the same slot in *new*, or (if any member's path is
    missing) the whole group is skipped, matching the per-file skip-silently
    contract.
    """
    new_by_path = {entry.path: entry.file_id for entry in new.files.values()}
    carried_groups: set[int] = set()
    for assignment in old.assignments():
        if assignment.origin != ORIGIN_MANUAL:
            continue
        entry = old.files[assignment.file_id]
        if assignment.part_group:
            if assignment.part_group in carried_groups:
                continue
            carried_groups.add(assignment.part_group)
            members = old.part_group_members(assignment.file_id)
            new_ids: list[int] = []
            for member in members:
                member_entry = old.files[member.file_id]
                new_member_id = new_by_path.get(member_entry.path)
                if new_member_id is None:
                    new_ids = []
                    break
                new_ids.append(new_member_id)
            if not new_ids:
                continue
            try:
                new.assign(
                    new_ids[0],
                    assignment.season,
                    list(assignment.episodes),
                    origin=ORIGIN_MANUAL,
                    displace=True,
                )
            except ValueError:
                continue
            new.group_parts(
                new_ids,
                assignment.season,
                list(assignment.episodes),
                origin=ORIGIN_MANUAL,
            )
            continue
        new_id = new_by_path.get(entry.path)
        if new_id is None:
            continue
        try:
            carried = new.assign(
                new_id,
                assignment.season,
                list(assignment.episodes),
                origin=ORIGIN_MANUAL,
                displace=True,
            )
        except ValueError:
            continue
        if assignment.part_order:
            new._assignments[new_id] = replace(
                carried, role=assignment.role, part_order=assignment.part_order
            )
