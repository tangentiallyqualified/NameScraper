"""Pure helper functions for media workspace presentation logic.

Extracted from media_workspace.py during Phase 10.14 to reduce that
module's line count and isolate presentation logic from widget code.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QListWidgetItem, QWidget

from ...engine import PreviewItem, ScanState
from ...app.services.command_gating_service import CommandGatingService
from ._formatting import percent_text


# ── State classification ────────────────────────────────────────────


def file_count_for_state(state: ScanState) -> int:
    if state.preview_items:
        return len(state.preview_items)
    if state.file_count:
        return state.file_count
    return 0


def confidence_band(score: float, *, state: ScanState | None = None) -> str:
    if state is not None and (state.duplicate_of is not None or state.queued or state.scanning):
        return "muted"
    if score >= 0.85:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def confidence_fill_color(score: float, *, state: ScanState | None = None) -> str:
    return {
        "high": "#3ea463",
        "medium": "#e5a00d",
        "low": "#d44040",
        "muted": "#777777",
    }[confidence_band(score, state=state)]


def band_color(band: str) -> str:
    return {
        "high": "#3ea463",
        "medium": "#e5a00d",
        "low": "#d44040",
        "muted": "#777777",
        "error": "#d44040",
    }[band]


def state_status(state: ScanState) -> tuple[str, QColor]:
    if state.queued:
        return "Queued", QColor("#4a9eda")
    if state.duplicate_of is not None:
        return "Duplicate", QColor("#777777")
    if state.scanning:
        return "Scanning", QColor("#e5a00d")
    if state.show_id is None:
        return "Unmatched", QColor("#d44040")
    if state.needs_review:
        return "Needs Review", QColor("#e5a00d")
    if state.match_origin == "manual":
        return "Approved", QColor("#4a9eda")
    if is_plex_ready_state(state):
        return "Plex Ready", QColor("#3ea463")
    return "Matched", QColor("#4a9eda")


def state_status_tone(state: ScanState) -> str:
    if state.queued:
        return "info"
    if state.duplicate_of is not None:
        return "muted"
    if state.scanning:
        return "accent"
    if state.show_id is None:
        return "error"
    if state.needs_review:
        return "accent"
    if is_plex_ready_state(state):
        return "success"
    return "info"


def is_plex_ready_state(state: ScanState) -> bool:
    return CommandGatingService.is_plex_ready_state(state)


def is_state_queue_approvable(state: ScanState, *, media_type: str) -> bool:
    if state.queued or state.scanning:
        return False
    if state.duplicate_of is not None or state.show_id is None:
        return False
    if state.needs_review or is_plex_ready_state(state):
        return False
    if media_type == "movie":
        return any(item.is_actionable for item in state.preview_items)
    return True


def roster_group(state: ScanState) -> str:
    if state.queued:
        return "queued"
    if state.duplicate_of is not None:
        return "duplicate"
    if state.show_id is None:
        return "unmatched"
    if state.needs_review:
        return "review"
    if is_plex_ready_state(state):
        return "plex-ready"
    return "matched"


def auto_accept_threshold(settings) -> float:
    if settings is None:
        return 0.55
    return settings.auto_accept_threshold


def state_match_summary(state: ScanState, threshold: float) -> str:
    pct = percent_text(state.confidence)
    threshold_text = percent_text(threshold)
    if state.duplicate_of is not None:
        return f"{pct} confidence · duplicate match"
    if state.match_origin == "manual" and not state.needs_review:
        return f"{pct} confidence · manually approved"
    if state.needs_review:
        return f"{pct} confidence · below {threshold_text} threshold"
    return f"{pct} confidence · clears {threshold_text} threshold"


# ── Roster helpers ──────────────────────────────────────────────────


def state_key(state: ScanState) -> str:
    return f"{state.folder}:{state.show_id or 'unmatched'}"


def roster_item_key(state: ScanState) -> str:
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


def season_label(season_num: int | None) -> str:
    if season_num is None:
        return "Other Files"
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
    header.setForeground(QColor("#f0b429"))
    header.setBackground(QColor("#2a2110"))
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
