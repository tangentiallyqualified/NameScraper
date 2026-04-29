"""Engine data structures — pure data classes with no scanning logic.

Kept in its own module so controllers, GUI widgets, and tests can import
the shapes without pulling in the full engine core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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
    from ._tv_scanner import TVScanner  # noqa: F401


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
    original: Path      # Absolute source path
    new_name: str       # Target filename (already computed — no reconstruction needed)
    file_type: str      # "subtitle" | "poster" | "nfo" | …


@dataclass
class PreviewItem:
    """One file's rename plan.  The GUI reads these to build the preview."""
    original: Path
    new_name: str | None
    target_dir: Path | None
    season: int | None          # None for movies
    episodes: list[int]         # Empty for movies
    status: str                 # "OK", "SKIP: ...", "CONFLICT: ..."
    media_type: str = MediaType.TV
    media_id: int | None = None      # TMDB ID — for grouping in batch mode
    media_name: str | None = None    # Display name — for grouping in batch mode
    companions: list[CompanionFile] = field(default_factory=list)
    episode_confidence: float = 1.0

    def is_move(self) -> bool:
        """True if this rename also moves the file to a different folder."""
        return (
            self.target_dir is not None
            and self.target_dir != self.original.parent
        )

    @property
    def is_conflict(self) -> bool:
        return self.status.startswith("CONFLICT")

    @property
    def is_skipped(self) -> bool:
        return self.status.startswith("SKIP")

    @property
    def is_review(self) -> bool:
        return self.status.startswith("REVIEW")

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
        return not (
            self.new_name == self.original.name
            and target_dir == self.original.parent
        )


@dataclass
class RenameResult:
    """Outcome of an execute_rename call."""
    renamed_count: int = 0
    errors: list[str] = field(default_factory=list)
    log_entry: dict = field(default_factory=dict)
    new_root: Path | None = None


@dataclass
class SeasonCompleteness:
    """Completeness info for a single season."""
    season: int
    expected: int
    matched: int
    missing: list[tuple[int, str]]
    matched_episodes: list[tuple[int, str]] = field(default_factory=list)

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


@dataclass
class ScanState:
    """Per-show scan state — decouples show-level data from the GUI."""
    folder: Path
    media_info: dict
    scanner: "TVScanner | None" = None
    source_file: Path | None = None
    preview_items: list[PreviewItem] = field(default_factory=list)
    completeness: CompletenessReport | None = None

    # Match metadata
    confidence: float = 0.0
    match_origin: str = "auto"
    alternate_matches: list[dict] = field(default_factory=list)
    search_results: list[dict] = field(default_factory=list)
    relative_folder: str = ""
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

    # Season metadata
    season_names: dict[int, str] = field(default_factory=dict)
    season_assignment: int | None = None
    season_folders: dict[int, Path] = field(default_factory=dict)
    active_episode_source: str = "tmdb"
    orphan_companion_files: list[CompanionFile] = field(default_factory=list)

    # Flags
    scanned: bool = False
    scanning: bool = False
    checked: bool = True
    duplicate_of: str | None = None
    queued: bool = False
    tie_detected: bool = False

    @property
    def show_id(self) -> int | None:
        return self.media_info.get("id")

    @property
    def display_name(self) -> str:
        name = (self.media_info.get("name")
                or self.media_info.get("title")
                or self.folder.name)
        year = self.media_info.get("year", "")
        return f"{name} ({year})" if year else name

    @property
    def needs_review(self) -> bool:
        if self.show_id is not None and self.match_origin == "manual":
            return False
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

    @property
    def match_pct(self) -> float:
        if self.completeness:
            return self.completeness.pct
        return 0.0

    @property
    def all_skipped(self) -> bool:
        if not self.scanned or not self.preview_items:
            return False
        return all(it.status.startswith("SKIP") for it in self.preview_items)

    @property
    def actionable_indices(self) -> set[int]:
        return {
            index for index, item in enumerate(self.preview_items)
            if item.is_actionable
        }

    @property
    def actionable_file_count(self) -> int:
        return len(self.actionable_indices)

    def reset_gui_state(self) -> None:
        self.check_vars.clear()
        self.selected_index = None
        self.card_positions.clear()
        self.season_header_positions.clear()
        self.display_order.clear()
        self.collapsed_seasons.clear()

    def reset_scan(self) -> None:
        self.scanner = None
        self.preview_items.clear()
        self.completeness = None
        self.scanned = False
        self.reset_gui_state()


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

    direct_evidence = evidence if evidence is not None else collect_direct_episode_evidence(folder)
    explicit_seasons = {item.season_num for item in direct_evidence if item.season_num > 0}
    if len(explicit_seasons) == 1:
        return next(iter(explicit_seasons))

    if show_name:
        folder_cleaned = clean_folder_name(folder.name, include_year=False).lower().strip()
        show_cleaned = clean_folder_name(show_name, include_year=False).lower().strip()
        if show_cleaned and folder_cleaned.startswith(show_cleaned):
            suffix = folder_cleaned[len(show_cleaned):].strip()
            if suffix.isdigit():
                season = int(suffix)
                if 1 <= season <= 50:
                    return season

    return None
