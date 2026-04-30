"""Reusable row widgets for the media workspace roster and preview panels."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ._formatting import clamped_percent
from ._image_utils import (
    ShimmerOverlay,
    build_placeholder_pixmap,
    scale_pixmap_for_device,
)
from ._workspace_widget_primitives import (
    _CheckBinding,
    ClickableRow,
    ElidedLabel,
    MasterCheckBox,
    MiniProgressBar,
    RosterPosterBridge,
    ToggleSwitch,
)
from ._media_helpers import (
    companion_summary as _companion_summary,
    confidence_band as _confidence_band,
    confidence_fill_color as _confidence_fill_color,
    file_count_for_state as _file_count_for_state,
    placeholder_initials as _placeholder_initials,
    preview_band as _preview_band,
    preview_band_name as _preview_band_name,
    preview_heading as _preview_heading,
    preview_status_label as _preview_status_label,
    preview_status_tone as _preview_status_tone,
    preview_target_text as _preview_target_text,
    repolish as _repolish,
    state_match_summary as _state_match_summary,
    state_status as _state_status,
    state_status_tone as _state_status_tone,
)


# ── Utility helpers ──────────────────────────────────────────────────

def _state_spans_multiple_seasons(state: ScanState) -> bool:
    if len(state.season_folders) > 1:
        return True
    preview_seasons = {
        preview.season
        for preview in state.preview_items
        if preview.season not in (None, 0)
    }
    return len(preview_seasons) > 1


def _known_non_special_season_count(state: ScanState) -> int:
    if state.completeness is not None:
        return len(state.completeness.seasons)
    if state.season_names:
        return len({season for season in state.season_names if season > 0})
    if state.season_folders:
        return len({season for season in state.season_folders if season > 0})
    return len({
        preview.season
        for preview in state.preview_items
        if preview.season not in (None, 0)
    })


def _should_show_season_assignment(state: ScanState) -> bool:
    if state.season_assignment in (None, 0):
        return False
    return (
        _known_non_special_season_count(state) > 1
        and not _state_spans_multiple_seasons(state)
    )


def _percent_from_label(value: str) -> int | None:
    text = value.strip()
    if not text.endswith("%"):
        return None
    try:
        return max(0, min(100, int(round(float(text[:-1])))))
    except ValueError:
        return None


# ── Roster row widget ────────────────────────────────────────────────

class RosterRowWidget(ClickableRow):
    check_toggled = Signal(bool)
    season_assign_requested = Signal()
    geometry_changed = Signal()

    def __init__(
        self,
        state: ScanState,
        *,
        compact: bool,
        media_type: str,
        auto_accept_threshold: float,
        checkable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("rosterRowCard")
        self.setProperty("cssClass", "roster-row-card")
        self._state = state
        self._compact = compact
        self._media_type = media_type
        self._auto_accept_threshold = auto_accept_threshold
        self._selected = False
        self._poster = QLabel()
        self._poster_size = QSize(34, 50) if compact else QSize(48, 70)
        self._poster.setFixedSize(self._poster_size)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shimmer: ShimmerOverlay | None = None
        if not compact:
            self._apply_placeholder_poster()
            self._shimmer = ShimmerOverlay(self._poster)
        self._poster.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = ToggleSwitch(state.checked if checkable else False, self)
        self._check.setVisible(checkable)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        if not compact:
            poster_alignment = (
                Qt.AlignmentFlag.AlignVCenter
                if media_type == "movie"
                else Qt.AlignmentFlag.AlignTop
            )
            layout.addWidget(self._poster, alignment=poster_alignment)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title = QLabel(state.display_name)
        self._title.setProperty("cssClass", "row-title")
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self._title, stretch=1)

        self._status = QLabel(_state_status(state)[0].upper())
        self._status.setProperty("cssClass", "status-pill")
        self._status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(
            self._status,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        self._status.hide()
        body.addLayout(title_row)

        meta_parts = [f"{_file_count_for_state(state)} file(s)"]
        if _should_show_season_assignment(state):
            meta_parts.append(f"Season {state.season_assignment}")
        if state.duplicate_of is not None:
            duplicate_target = state.duplicate_of_relative_folder or state.duplicate_of
            meta_parts.append(f"Same match as {duplicate_target}")
        elif state.show_id is not None:
            meta_parts.append(_state_match_summary(state, auto_accept_threshold))
        if state.needs_review and state.alternate_matches and not state.queued:
            n_alts = min(len(state.alternate_matches), 2)
            meta_parts.append(f"{n_alts} alternative{'s' if n_alts != 1 else ''}")
        self._meta = QLabel(" · ".join(meta_parts))
        self._meta.setProperty("cssClass", "caption")
        self._meta.setWordWrap(True)
        self._meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._meta)

        confidence_row = QHBoxLayout()
        confidence_row.setContentsMargins(0, 0, 0, 0)
        confidence_row.setSpacing(8)
        self._confidence_label = QLabel("Confidence")
        self._confidence_label.setProperty("cssClass", "caption")
        self._confidence_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        confidence_row.addWidget(self._confidence_label)

        self._confidence = MiniProgressBar(
            color=_confidence_fill_color(self._state.confidence, state=self._state),
            value=clamped_percent(state.confidence),
        )
        self._confidence.setFixedWidth(92 if compact else 110)
        confidence_row.addWidget(self._confidence)
        confidence_row.addStretch(1)
        body.addLayout(confidence_row)

        self._approve_btn = None

        self._season_btn = None

        self._alternates_layout = None
        self._alternates_widget = None
        self._confirm_row = None

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_checked(self, checked: bool) -> None:
        blocked = self._check.blockSignals(True)
        self._check.setChecked(checked)
        self._check.blockSignals(blocked)

    def set_poster(self, pixmap: QPixmap) -> None:
        if self._compact or pixmap.isNull():
            if not self._compact:
                self._apply_placeholder_poster()
            return
        if self._shimmer is not None:
            self._shimmer.stop()
            self._shimmer = None
        self._poster.setText("")
        self._poster.setPixmap(
            scale_pixmap_for_device(
                pixmap,
                self._poster.size(),
                device_pixel_ratio=self._poster_device_pixel_ratio(),
            )
        )

    def _apply_placeholder_poster(self) -> None:
        title = _placeholder_initials(self._state.display_name)
        placeholder = build_placeholder_pixmap(
            self._poster_size,
            title=title,
            subtitle="",
            accent=_state_status(self._state)[1].name(),
            device_pixel_ratio=self._poster_device_pixel_ratio(),
        )
        self._poster.setPixmap(placeholder)
        self._poster.setText("")

    def poster_request_width(self) -> int:
        return max(220, min(420, int(round(self._poster_size.width() * self._poster_device_pixel_ratio() * 2.0))))

    def _poster_device_pixel_ratio(self) -> float:
        try:
            return max(1.0, float(self._poster.devicePixelRatioF()))
        except Exception:
            return 1.0

    def _apply_style(self) -> None:
        self.setProperty("band", _confidence_band(self._state.confidence, state=self._state))
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        self._status.setProperty("tone", _state_status_tone(self._state))
        _repolish(self)
        _repolish(self._status)
        self._confidence.setColor(_confidence_fill_color(self._state.confidence, state=self._state))


# ── Preview row widget ───────────────────────────────────────────────

class PreviewRowWidget(ClickableRow):
    check_toggled = Signal(bool)

    def __init__(
        self,
        preview: PreviewItem,
        *,
        compact: bool,
        show_confidence: bool,
        show_companions: bool,
        checked: bool,
        checkable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self._preview = preview
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = ToggleSwitch(checked if preview.is_actionable and checkable else False, self)
        self._check.setVisible(preview.is_actionable and checkable)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        original = _preview_heading(preview, compact=compact)
        self._original = QLabel(original)
        self._original.setProperty("cssClass", "row-title")
        self._original.setWordWrap(True)
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._original, stretch=1)

        self._status = QLabel(_preview_status_label(preview))
        self._status.setProperty("cssClass", "status-pill")
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(top_row)

        self._target = QLabel(_preview_target_text(preview))
        self._target.setProperty("cssClass", "row-target")
        self._target.setWordWrap(True)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._target)

        if show_companions and preview.companions:
            self._companions = QLabel(_companion_summary(preview))
            self._companions.setProperty("cssClass", "caption")
            self._companions.setWordWrap(True)
            self._companions.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            body.addWidget(self._companions)
        else:
            self._companions = None

        self._confidence = None
        if show_confidence:
            self._confidence = MiniProgressBar(
                color=_preview_band(self._preview),
                value=clamped_percent(preview.episode_confidence),
            )
            body.addWidget(self._confidence)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_checked(self, checked: bool) -> None:
        if not self._check.isVisible():
            return
        blocked = self._check.blockSignals(True)
        self._check.setChecked(checked)
        self._check.blockSignals(blocked)

    def _apply_style(self) -> None:
        self.setProperty("band", _preview_band_name(self._preview))
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        self._status.setProperty("tone", _preview_status_tone(self._preview))
        _repolish(self)
        _repolish(self._status)
        if self._confidence is not None:
            self._confidence.setColor(_preview_band(self._preview))


# ── Folder preview row widget ────────────────────────────────────────

class EpisodeGuideRowWidget(ClickableRow):
    def __init__(
        self,
        *,
        title: str,
        status: str,
        original: str = "",
        target: str = "",
        confidence: str = "",
        companions: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("episodeGuideRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self.setProperty("band", self._band_for_status(status))
        self.setProperty("selectionState", "normal")
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = ToggleSwitch(False, self)
        self._check.hide()
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._title = QLabel(title)
        self._title.setProperty("cssClass", "row-title")
        self._title.setWordWrap(True)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._title, stretch=1)

        self._status = QLabel(status)
        self._status.setProperty("cssClass", "status-pill")
        self._status.setProperty("tone", self._tone_for_status(status))
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(top_row)

        self._original = QLabel(original)
        self._original.setProperty("cssClass", "caption")
        self._original.setWordWrap(True)
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._original.setVisible(bool(original))
        body.addWidget(self._original)

        self._target = QLabel(f"-> {target}" if target else "")
        self._target.setProperty("cssClass", "row-target")
        self._target.setWordWrap(True)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._target.setVisible(bool(target))
        body.addWidget(self._target)

        companion_text = ", ".join(companions or [])
        self._companions = QLabel(f"Companions: {companion_text}" if companion_text else "")
        self._companions.setProperty("cssClass", "caption")
        self._companions.setWordWrap(True)
        self._companions.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._companions.setVisible(bool(companion_text))
        body.addWidget(self._companions)

        confidence_value = _percent_from_label(confidence)
        confidence_row = QHBoxLayout()
        confidence_row.setContentsMargins(0, 0, 0, 0)
        confidence_row.setSpacing(8)
        self._confidence_label = QLabel("Confidence")
        self._confidence_label.setProperty("cssClass", "caption")
        self._confidence_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._confidence_label.setVisible(confidence_value is not None)
        confidence_row.addWidget(self._confidence_label)

        self._confidence = MiniProgressBar(
            color=_confidence_fill_color((confidence_value or 0) / 100),
            value=confidence_value or 0,
        )
        self._confidence.setFixedWidth(96)
        self._confidence.setVisible(confidence_value is not None)
        confidence_row.addWidget(self._confidence)
        confidence_row.addStretch(1)
        body.addLayout(confidence_row)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        _repolish(self)
        _repolish(self._status)

    @staticmethod
    def _band_for_status(status: str) -> str:
        if status == "Conflict":
            return "error"
        if status == "Missing File":
            return "muted"
        if status == "Review":
            return "accent"
        return "success"

    @staticmethod
    def _tone_for_status(status: str) -> str:
        if status == "Conflict":
            return "error"
        if status == "Missing File":
            return "muted"
        if status == "Review":
            return "accent"
        return "success"


class FolderPreviewRowWidget(QFrame):
    def __init__(self, source_name: str, target_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setProperty("cssClass", "preview-row-card")
        self.setProperty("band", "muted")
        self.setProperty("selectionState", "normal")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(6)

        self._original = ElidedLabel(
            source_name,
            elide_mode=Qt.TextElideMode.ElideRight,
            parent=self,
        )
        self._original.setProperty("cssClass", "row-title")
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._original, stretch=1)

        self._arrow = QLabel("->")
        self._arrow.setProperty("cssClass", "caption")
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._arrow.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._arrow, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._target = QLabel(target_name)
        self._target.setProperty("cssClass", "row-target")
        self._target.setWordWrap(False)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._target.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._target.setToolTip(target_name)
        layout.addWidget(self._target)

        _repolish(self)
