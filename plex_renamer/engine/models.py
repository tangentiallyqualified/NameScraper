"""Engine data structures — pure data classes with no scanning logic.

Kept in its own module so controllers, GUI widgets, and tests can import
the shapes without pulling in the full engine core.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias

from ..constants import VIDEO_EXTENSIONS, MediaType
from ..parsing import (
    clean_folder_name,
    extract_episode,
    extract_season_number,
    get_season,
    looks_like_tv_episode,
)
from ._state import get_auto_accept_threshold

if TYPE_CHECKING:
    from .episode_assignments import EpisodeAssignmentTable


EPISODE_REVIEW_STATUS_PREFIX = "REVIEW: episode confidence below threshold"
SeasonFolderEntry = Path | tuple[Path, ...]
MediaInfoValue: TypeAlias = str | int | float | None


def iter_season_folder_paths(entry: SeasonFolderEntry) -> tuple[Path, ...]:
    if isinstance(entry, Path):
        return (entry,)
    return entry


@dataclass
class CompanionFile:
    """
    A non-video file renamed alongside its parent media file.

    Carries a fully-computed rename plan so every consumer — the GUI,
    the job builder, the snapshot service — can read it directly without
    reconstructing names from intermediate data.

    ``file_type`` is an open string enum.  Current values:
      ``"subtitle"``  — SRT, ASS, SSA, VTT, SUP, etc.

    Future values (not yet implemented):
      ``"poster"``    — cover art (.jpg/.png) inside the movie folder
      ``"nfo"``       — metadata sidecar files (.nfo)

    Adding a new companion type requires only producing ``CompanionFile``
    objects with the appropriate ``file_type``; no changes to ``PreviewItem``,
    ``_build_rename_ops``, the job executor, or the snapshot service.
    """

    original: Path  # Absolute source path
    new_name: str  # Target filename (already computed — no reconstruction needed)
    file_type: str  # "subtitle" | "poster" | "nfo" | …


@dataclass
class PreviewItem:
    """One file's rename plan.  The GUI reads these to build the preview."""

    original: Path
    new_name: str | None
    target_dir: Path | None
    season: int | None  # None for movies
    episodes: list[int]  # Empty for movies
    status: str  # "OK", "SKIP: ...", "CONFLICT: ..."
    media_type: str = MediaType.TV
    media_id: int | None = None  # TMDB ID — for grouping in batch mode
    media_name: str | None = None  # Display name — for grouping in batch mode
    companions: list[CompanionFile] = field(default_factory=list)
    episode_confidence: float = 1.0
    source_relative_folder: str = ""
    file_id: int | None = None  # Link back to EpisodeAssignmentTable.files

    @property
    def is_conflict(self) -> bool:
        return self.status.startswith("CONFLICT")

    @property
    def is_skipped(self) -> bool:
        return self.status.startswith("SKIP")

    @property
    def is_duplicate(self) -> bool:
        return self.status.startswith("DUPLICATE")

    @property
    def is_review(self) -> bool:
        return self.status.startswith("REVIEW")

    @property
    def is_episode_review(self) -> bool:
        return self.status.startswith(EPISODE_REVIEW_STATUS_PREFIX)

    @property
    def is_unmatched(self) -> bool:
        return "UNMATCHED" in self.status

    @property
    def is_actionable(self) -> bool:
        """True when this item can produce a concrete rename operation."""
        if self.new_name is None:
            return False
        if self.status != "OK" and not self.is_unmatched and "REVIEW" not in self.status:
            return False
        target_dir = self.target_dir or self.original.parent
        return not (self.new_name == self.original.name and target_dir == self.original.parent)


@dataclass
class RenameResult:
    """Outcome of a rename-execution pass (see ``job_executor._execute_rename``)."""

    renamed_count: int = 0
    errors: list[str] = field(default_factory=list)
    log_entry: dict[str, Any] = field(default_factory=dict)
    new_root: Path | None = None


@dataclass
class SeasonCompleteness:
    """Completeness info for a single season."""

    season: int
    expected: int
    matched: int
    missing: list[tuple[int, str]]
    matched_episodes: list[tuple[int, str]] = field(default_factory=list)
    review: int = 0  # expected episodes mapped only by review-status files
    review_episodes: list[tuple[int, str]] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.expected > 0 and self.matched >= self.expected

    @property
    def pct(self) -> float:
        return (self.matched / self.expected * 100) if self.expected else 0.0


@dataclass
class CompletenessReport:
    """Full completeness report for a TV series."""

    seasons: dict[int, SeasonCompleteness]
    specials: SeasonCompleteness | None
    total_expected: int
    total_matched: int
    total_missing: list[tuple[int, int, str]]

    @property
    def is_complete(self) -> bool:
        return self.total_expected > 0 and self.total_matched >= self.total_expected

    @property
    def pct(self) -> float:
        return (self.total_matched / self.total_expected * 100) if self.total_expected else 0.0


class TVScanStateScanner(Protocol):
    """Episode metadata capability retained by a TV ``ScanState``."""

    @property
    def episode_meta(self) -> Mapping[tuple[int, int], Mapping[str, object]]: ...


class TVScannerOperations(TVScanStateScanner, Protocol):
    """Full TV scan operations used by controllers and reconciliation."""

    @property
    def assignment_table(self) -> EpisodeAssignmentTable | None: ...

    @property
    def show_info(self) -> Mapping[str, object]: ...

    def scan(self) -> tuple[list[PreviewItem], bool]: ...

    def scan_consolidated(self) -> list[PreviewItem]: ...

    def get_completeness(
        self,
        items: list[PreviewItem],
        checked_indices: set[int] | None = None,
    ) -> CompletenessReport: ...


class MovieScanStateScanner(Protocol):
    """Movie scanner capabilities retained by a shared ``ScanState``."""

    def rematch_file(self, item: PreviewItem, chosen: dict) -> PreviewItem: ...

    def get_search_results(self, file_path: Path) -> list[dict]: ...


ScanStateScanner = TVScanStateScanner | MovieScanStateScanner


@dataclass
class ScanState:
    """Per-show scan state — decouples show-level data from the GUI."""

    folder: Path
    media_info: dict[str, MediaInfoValue]
    scanner: ScanStateScanner | None = None
    source_file: Path | None = None
    preview_items: list[PreviewItem] = field(default_factory=list)
    completeness: CompletenessReport | None = None
    assignments: EpisodeAssignmentTable | None = None

    # Match metadata
    confidence: float = 0.0
    match_origin: str = "auto"
    provider_name: str = "tmdb"
    alternate_matches: list[dict] = field(default_factory=list)
    search_results: list[dict] = field(default_factory=list)
    relative_folder: str = ""
    output_root: Path | None = None
    parent_relative_folder: str | None = None
    duplicate_of_relative_folder: str | None = None
    discovery_reason: str = ""
    has_direct_season_subdirs: bool = False
    direct_episode_file_count: int = 0
    direct_video_file_count: int = 0
    discovered_via_symlink: bool = False

    # GUI-side state
    check_vars: dict = field(default_factory=dict)
    selected_index: int | None = None
    card_positions: list[tuple[int, int, int]] = field(default_factory=list)
    season_header_positions: list[tuple[int, int, int]] = field(default_factory=list)
    display_order: list[int] = field(default_factory=list)
    collapsed_seasons: set[int] = field(default_factory=set)

    # AutoMux session state (mkvmerge spec §5.1) — per-entry, resets on
    # rescan/app restart. Keys are preview-item indices; values are
    # serialized MuxPlan dicts (engine/_mux_planner.MuxPlan.to_dict()).
    automux_disabled: bool = False
    mux_plans: dict[int, dict] = field(default_factory=dict)
    mux_probe_errors: dict[int, str] = field(default_factory=dict)
    # Per-file AutoMux opt-out (session-scoped; spec: gui-round5 §4b).
    mux_opt_outs: set[int] = field(default_factory=set)

    # Season metadata
    season_names: dict[int, str] = field(default_factory=dict)
    season_assignment: int | None = None
    season_folders: dict[int, SeasonFolderEntry] = field(default_factory=dict)
    active_episode_source: str = "tmdb"
    orphan_companion_files: list[CompanionFile] = field(default_factory=list)

    # Flags
    scanned: bool = False
    scanning: bool = False
    checked: bool = True
    duplicate_of: str | None = None
    queued: bool = False
    tie_detected: bool = False
    # Set when the per-show episode scan raised; the show must surface as an
    # error in the GUI instead of silently showing no episodes.
    scan_error: str | None = None

    @property
    def show_id(self) -> int | None:
        media_id = self.media_info.get("id")
        return media_id if isinstance(media_id, int) else None

    @property
    def provider_show_key(self) -> tuple[str, int] | None:
        """Cross-provider show identity — numeric IDs collide between
        providers, so bare show_id must never be compared across states."""
        show_id = self.show_id
        if show_id is None:
            return None
        return (self.provider_name, show_id)

    @property
    def display_name(self) -> str:
        name = self.media_info.get("name") or self.media_info.get("title") or self.folder.name
        year = self.media_info.get("year", "")
        return f"{name} ({year})" if year else str(name)

    @property
    def needs_review(self) -> bool:
        if self.show_id is not None and self.match_origin == "manual":
            return False
        if self.match_origin == "fallback":
            return True
        if self.tie_detected:
            return True
        return self.confidence < get_auto_accept_threshold()

    @property
    def file_count(self) -> int:
        return len(self.preview_items)

    @property
    def total_expected(self) -> int:
        if self.completeness:
            return self.completeness.total_expected
        return 0

    @property
    def total_matched(self) -> int:
        if self.completeness:
            return self.completeness.total_matched
        return 0

    def reset_gui_state(self) -> None:
        self.check_vars.clear()
        self.selected_index = None
        self.card_positions.clear()
        self.season_header_positions.clear()
        self.display_order.clear()
        self.collapsed_seasons.clear()
        self.automux_disabled = False
        self.mux_plans.clear()
        self.mux_probe_errors.clear()
        self.mux_opt_outs.clear()

    def reset_scan(self) -> None:
        self.scanner = None
        self.preview_items.clear()
        self.completeness = None
        self.assignments = None
        self.scanned = False
        self.scan_error = None
        self.reset_gui_state()


def show_pin_key(folder: Path) -> str:
    """Stable per-show key for provider pins: cleaned title, plus year
    when the folder name carries one ("breaking bad|2008")."""
    from ..parsing import best_tv_match_title, extract_year

    title = best_tv_match_title(folder, include_year=False).casefold()
    year = extract_year(folder.name)
    return f"{title}|{year}" if year else title


def plan_has_actions(plan: dict) -> bool:
    """Mirror of MuxPlan.has_actions for serialized plans (user edits can
    reduce a plan to a no-op; such plans must not force a remux).

    Moved from automux_service (round6 §1) so engine-level code can use it
    without an engine -> app import; automux_service re-exports it."""
    if plan.get("container_conversion"):
        return True
    if any(not d.get("keep", True) for d in plan.get("track_decisions", [])):
        return True
    return any(m.get("action") == "merge" for m in plan.get("subtitle_merges", []))


def file_mux_active(state: ScanState, index: int) -> bool:
    """True when this preview item will actually be muxed: cached plan
    with actions, not opted out, AutoMux not disabled for the entry.

    Moved from automux_service (round6 §1) — see plan_has_actions."""
    if state.automux_disabled or index in state.mux_opt_outs:
        return False
    plan = state.mux_plans.get(index)
    return plan is not None and plan_has_actions(plan)


@dataclass(frozen=True)
class DirectEpisodeEvidence:
    """Direct child file evidence for TMDB TV disambiguation."""

    season_num: int
    episode_num: int
    raw_title: str | None = None


def collect_direct_episode_evidence(folder: Path) -> list[DirectEpisodeEvidence]:
    """Collect explicit ``S##E##`` evidence for a show folder."""
    evidence: list[DirectEpisodeEvidence] = []

    def _collect_from(directory: Path) -> int:
        count = 0
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return count
        for entry in entries:
            if not entry.is_file() or entry.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if not looks_like_tv_episode(entry):
                continue
            eps, raw_title, is_season_relative = extract_episode(entry.name)
            season_num = extract_season_number(entry.name)
            if not is_season_relative or season_num is None or not eps:
                continue
            for episode_num in eps:
                evidence.append(DirectEpisodeEvidence(season_num, episode_num, raw_title))
            count += 1
        return count

    direct_count = _collect_from(folder)
    if direct_count > 0:
        return evidence

    try:
        child_dirs = sorted(folder.iterdir())
    except OSError:
        return evidence

    for child in child_dirs:
        if not child.is_dir():
            continue
        if get_season(child) is None:
            continue
        _collect_from(child)

    return evidence


def infer_explicit_season_assignment(
    folder: Path,
    evidence: list[DirectEpisodeEvidence] | None = None,
    show_name: str | None = None,
) -> int | None:
    """Infer a season assignment from folder name or consistent S##E## files."""
    season_num = get_season(folder)
    if season_num is not None:
        return season_num

    # "Specials (1998-2003)": the year range hides the bare specials label
    # from get_season; retry on the cleaned name.
    cleaned_name = clean_folder_name(folder.name, include_year=False).strip()
    if cleaned_name and cleaned_name != folder.name and get_season(Path(cleaned_name)) == 0:
        return 0

    direct_evidence = evidence if evidence is not None else collect_direct_episode_evidence(folder)
    explicit_seasons = {item.season_num for item in direct_evidence}
    if len(explicit_seasons) == 1:
        return next(iter(explicit_seasons))

    if show_name:
        folder_cleaned = clean_folder_name(folder.name, include_year=False).lower().strip()
        show_cleaned = clean_folder_name(show_name, include_year=False).lower().strip()
        if show_cleaned and folder_cleaned.startswith(show_cleaned):
            suffix = folder_cleaned[len(show_cleaned) :].strip()
            if suffix.isdigit():
                season = int(suffix)
                if 1 <= season <= 50:
                    return season

    return None
