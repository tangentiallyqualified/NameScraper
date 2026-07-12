"""Pure helper functions for media workspace presentation logic.

Extracted from media_workspace.py during Phase 10.14 to reduce that
module's line count and isolate presentation logic from widget code.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QListWidgetItem, QWidget

from ...constants import MediaType
from ...engine import PreviewItem, ScanState
from ...app.services.command_gating_service import CommandGatingService
from .. import theme
from ._formatting import percent_text


# ── State classification ────────────────────────────────────────────


def file_count_for_state(state: ScanState) -> int:
    if state.preview_items:
        return len(state.preview_items)
    if state.file_count:
        return state.file_count
    return 0


def confidence_band(score: float, *, state: ScanState | None = None, media_type: str = "tv") -> str:
    if state is not None and (
        (state.duplicate_of is not None and media_type == MediaType.MOVIE)
        or state.queued
        or state.scanning
    ):
        return "muted"
    if score >= 0.85:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def confidence_fill_color(score: float, *, state: ScanState | None = None, media_type: str = "tv") -> str:
    return band_color(confidence_band(score, state=state, media_type=media_type))


def band_color(band: str) -> str:
    return {
        "high": theme.color("success"),
        "medium": theme.color("warning"),
        "low": theme.color("error"),
        "muted": theme.color("text_dim"),
        "error": theme.color("error"),
    }[band]


def state_status(state: ScanState, *, media_type: str = "tv") -> tuple[str, QColor]:
    if state.queued:
        return "Queued", theme.qcolor("info")
    if state.scanning:
        return "Scanning", theme.qcolor("warning")
    if state.scan_error:
        return "Scan Failed", theme.qcolor("error")
    if state.duplicate_of is not None and media_type == MediaType.MOVIE:
        return "Duplicate", theme.qcolor("text_dim")
    if state.show_id is None:
        return "No Match Found", theme.qcolor("error")
    if state.needs_review or state.duplicate_of is not None:
        return "Review Match", theme.qcolor("warning")
    if has_episode_problems(state):
        return "Review Episode Matching", theme.qcolor("warning")
    if state.match_origin == "manual":
        return "Approved", theme.qcolor("info")
    if is_fully_ready_state(state):
        return "Fully Ready", theme.qcolor("success")
    return "Matched", theme.qcolor("info")


def state_status_tone(state: ScanState, *, media_type: str = "tv") -> str:
    if state.queued:
        return "info"
    if state.scanning:
        return "accent"
    if state.scan_error:
        return "error"
    if state.duplicate_of is not None and media_type == MediaType.MOVIE:
        return "muted"
    if state.show_id is None:
        return "error"
    if state.needs_review or state.duplicate_of is not None:
        return "accent"
    if has_episode_problems(state):
        return "accent"
    if is_fully_ready_state(state):
        return "success"
    return "info"


def is_fully_ready_state(state: ScanState) -> bool:
    return CommandGatingService.is_fully_ready_state(state)


def is_state_queue_approvable(state: ScanState, *, media_type: str) -> bool:
    if state.queued or state.scanning or state.scan_error:
        return False
    if state.duplicate_of is not None or state.show_id is None:
        return False
    if state.needs_review or is_fully_ready_state(state):
        return False
    # Conflicts and unapproved review rows block queueing. Unmapped primary
    # files deliberately do NOT (RC39): they route the show into "Review
    # Episode Matching" for the initial left-panel sorting, but the user must
    # be able to approve and queue the mapped files anyway — the unmapped
    # files simply produce no jobs.
    table = state.assignments
    if table is not None and table.conflicts():
        return False
    if any(item.is_review for item in state.preview_items):
        return False
    # Round6 §1: a correctly-named file with an action-bearing mux plan is
    # queue-relevant even though it produces no rename op by itself — the
    # approvable check must not exclude it (see CommandGatingService.
    # is_queue_relevant).
    return any(
        CommandGatingService.is_queue_relevant(state, index)
        for index in range(len(state.preview_items))
    )


def has_episode_problems(state: ScanState) -> bool:
    """True when the show match is settled but episode mapping has issues:
    a conflict, an unmapped primary file, or a below-threshold row.
    """
    table = state.assignments
    if table is not None:
        if table.conflicts():
            return True
        if table.unassigned_files():
            return True
    return any(item.is_episode_review for item in state.preview_items)


def is_specials_unmapped_only_state(state: ScanState) -> bool:
    """All regular (season >= 1) episodes mapped cleanly; the remaining
    problems involve only specials/extras/unknown-season files (spec §3.1)."""
    if not has_episode_problems(state):
        return False
    completeness = state.completeness
    if completeness is None or not completeness.seasons:
        return False
    if not all(season.is_complete for season in completeness.seasons.values()):
        return False
    table = state.assignments
    if table is not None and any(season >= 1 for (season, _episode) in table.conflicts()):
        return False
    for item in state.preview_items:
        if item.season is not None and item.season >= 1 and (
            item.is_conflict or item.is_episode_review or item.is_unmatched
        ):
            return False
    return True


def roster_group(state: ScanState, *, media_type: str = "tv") -> str:
    if state.queued:
        return "queued"
    if state.duplicate_of is not None and media_type == MediaType.MOVIE:
        return "duplicate"
    if state.show_id is None:
        return "unmatched"
    if state.scan_error:
        return "review-episodes"
    if state.needs_review or state.duplicate_of is not None:
        return "review-match"
    if has_episode_problems(state):
        if is_specials_unmapped_only_state(state):
            return "specials-unmapped"
        return "review-episodes"
    if is_fully_ready_state(state):
        return "fully-ready"
    return "matched"


def auto_accept_threshold(settings) -> float:
    if settings is None:
        return 0.55
    return settings.auto_accept_threshold


def state_match_summary(state: ScanState, threshold: float) -> str:
    pct = percent_text(state.confidence)
    source = (state.active_episode_source or "tmdb").upper()
    badge = f"{source} - {pct}"
    if state.duplicate_of is not None:
        return f"{source} - Duplicate"
    if state.match_origin == "manual" and not state.needs_review:
        return f"{source} - Approved"
    if state.tie_detected and state.needs_review:
        return f"{badge} - tied match"
    if state.needs_review:
        return f"{badge} - needs review"
    return badge


# ── Roster helpers ──────────────────────────────────────────────────


def state_key(state: ScanState) -> str:
    return f"{state.folder}:{state.show_id or 'unmatched'}"


def roster_item_key(state: ScanState) -> str:
    media_type = state.media_info.get("_media_type")
    if media_type == MediaType.MOVIE:
        if state.source_file is not None:
            return f"state:{state.source_file}"
        if state.preview_items:
            return f"state:{state.preview_items[0].original}"
    return f"state:{state.folder}"


def roster_selection_key(state: ScanState | None) -> str | None:
    if state is None:
        return None
    return roster_item_key(state)


def roster_signature(state: ScanState, *, compact: bool, media_type: str) -> tuple[object, ...]:
    alt_signature = tuple(
        (match.get("id"), match.get("name") or match.get("title"), match.get("year"))
        for match in state.alternate_matches[:2]
    )
    return (
        id(state),
        state.display_name,
        state.checked,
        state.show_id,
        state.queued,
        state.scanning,
        state.duplicate_of,
        state.needs_review,
        state.confidence,
        state.file_count,
        state.season_assignment,
        tuple(item.status for item in state.preview_items),
        compact,
        media_type,
        alt_signature,
    )


def match_label(match: dict, *, media_type: str) -> str:
    if media_type == "movie":
        title = match.get("title") or match.get("name") or "Unknown"
    else:
        title = match.get("name") or match.get("title") or "Unknown"
    year = match.get("year") or ""
    return f"{title} ({year})" if year else title


def placeholder_initials(text: str) -> str:
    parts = [part[0] for part in text.replace("(", " ").replace(")", " ").split() if part]
    if not parts:
        return "TM"
    return "".join(parts[:2]).upper()


# ── Preview helpers ─────────────────────────────────────────────────


def preview_status_label(preview: PreviewItem) -> str:
    if preview.is_conflict:
        return "CONFLICT"
    if preview.is_unmatched:
        return "UNMATCHED"
    if preview.is_review:
        return "NEEDS REVIEW"
    if preview.is_skipped:
        return "SKIP"
    return "OK"


def preview_status_tone(preview: PreviewItem) -> str:
    if preview.is_conflict or preview.is_unmatched:
        return "error"
    if preview.is_review:
        return "accent"
    if preview.is_skipped:
        return "muted"
    return "success"


def preview_band(preview: PreviewItem) -> str:
    return band_color(preview_band_name(preview))


def preview_band_name(preview: PreviewItem) -> str:
    if preview.is_conflict or preview.is_unmatched:
        return "error"
    if preview.is_skipped:
        return "muted"
    return confidence_band(preview.episode_confidence)


def preview_heading(preview: PreviewItem, *, compact: bool) -> str:
    if compact:
        if preview.season is not None and preview.episodes:
            episode_text = ", ".join(f"E{ep:02d}" for ep in preview.episodes)
            return f"S{preview.season:02d} {episode_text} · {preview.original.name}"
        return preview.original.name
    return preview.original.name


def preview_target_text(preview: PreviewItem) -> str:
    rename = preview.new_name or "No rename target"
    return f"-> {rename}"


def tv_preview_sort_key(preview: PreviewItem, index: int) -> tuple[int, int, int, str, int]:
    status = preview.status or ""
    if status == "OK":
        status_priority = 0
    elif "UNMATCHED" in status or "REVIEW" in status:
        status_priority = 1
    else:
        status_priority = 2

    first_episode = preview.episodes[0] if preview.episodes else 9999
    return (
        status_priority,
        first_episode,
        preview.season if preview.season is not None else 9999,
        preview.original.name.casefold(),
        index,
    )


def companion_summary(preview: PreviewItem) -> str:
    if not preview.companions:
        return ""
    names = ", ".join(companion.original.name for companion in preview.companions[:2])
    extra = ""
    if len(preview.companions) > 2:
        extra = f" +{len(preview.companions) - 2} more"
    return f"Companions: {names}{extra}"


def season_label(season_num: int | None, *, name: str = "") -> str:
    if season_num is None:
        return "Other Files"
    if season_num == 0:
        if name:
            return f"Specials - {name}"
        return "Specials"
    if name:
        return f"Season {season_num} - {name}"
    return f"Season {season_num}"


# ── Shared UI helpers ───────────────────────────────────────────────


def repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def make_section_header(text: str, *, selectable: bool = False) -> QListWidgetItem:
    header = QListWidgetItem(text.upper())
    header.setData(Qt.ItemDataRole.UserRole, None)
    flags = Qt.ItemFlag.ItemIsEnabled
    if selectable:
        flags |= Qt.ItemFlag.ItemIsSelectable
    header.setFlags(flags)
    header.setForeground(theme.qcolor("accent"))
    header.setBackground(theme.qcolor("section_header_bg"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(10)
    header.setFont(font)
    header.setSizeHint(QSize(0, 34))
    return header


def format_batch_result(result) -> str:
    parts = []
    if result.added:
        parts.append(f"Queued {result.added} job(s)")
    if result.total_skipped:
        parts.append(f"Skipped {result.total_skipped}")
    if result.blocked:
        parts.append(f"Blocked {len(result.blocked)}")
    if result.errors:
        parts.append(f"Errors: {len(result.errors)}")
    return " · ".join(parts) if parts else "No queueable items were selected."
