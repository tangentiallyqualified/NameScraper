"""Scanning progress dashboard shown while batch scans are running."""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt, QElapsedTimer, QTimer, Signal
from PySide6.QtGui import QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import _scale, theme
from ...app.models import ScanLifecycle
from ._workspace_widget_primitives import ElidedLabel


_TV_CHECKLIST = [
    ScanLifecycle.DISCOVERING,
    ScanLifecycle.MATCHING,
    ScanLifecycle.BUILDING_PREVIEWS,
    ScanLifecycle.RECONCILING,
    ScanLifecycle.PREPARING_REVIEW,
]

_MOVIE_CHECKLIST = [
    ScanLifecycle.DISCOVERING,
    ScanLifecycle.MATCHING,
    ScanLifecycle.BUILDING_PREVIEWS,
    ScanLifecycle.PREPARING_REVIEW,
]

_LIFECYCLE_LABELS = {
    ScanLifecycle.DISCOVERING: "Discover folders",
    ScanLifecycle.MATCHING: "Match on TMDB",
    ScanLifecycle.SCANNING: "Scan files",
    ScanLifecycle.BUILDING_PREVIEWS: "Build previews",
    ScanLifecycle.RECONCILING: "Reconcile scan results",
    ScanLifecycle.PREPARING_REVIEW: "Prepare review list",
}

_TERMINAL = {
    ScanLifecycle.READY,
    ScanLifecycle.WARNING,
    ScanLifecycle.FAILED,
    ScanLifecycle.CANCELLED,
}

_FILLER_DELAY_MS = 4000
_TV_FILLERS = (
    "Politely interrogating TMDB…",
    "Counting specials twice, just in case…",
    "Untangling Season 0…",
    "Cross-checking absolute numbering…",
    "Politely disagreeing with filenames…",
    "Reading release-group tea leaves…",
    "Consulting the episode guide, again…",
    "Wondering why S01E07 is missing…",
    "Filing multi-part episodes under 'both'…",
    "Translating scene names into English…",
    "Double-checking the double episodes…",
    "Convincing subtitles to tag along…",
)
_MOVIE_FILLERS = (
    "Politely interrogating TMDB…",
    "Comparing runtimes and vibes…",
    "Squinting at release years…",
    "Sorting sequels from remakes…",
    "Debating director's cuts…",
    "Separating remasters from reboots…",
    "Judging covers by their folders…",
    "Cross-referencing the credits…",
    "Asking the extras to identify themselves…",
    "Filing trailers under 'not the movie'…",
)


_CARD_COUNT = 5
_CONVEYOR_CYCLE_MS = 10_800     # full slot slide period (was 120 ticks × 90 ms)


def conveyor_offset(elapsed_ms: int, slot_w: int, cycle_ms: int = _CONVEYOR_CYCLE_MS) -> float:
    if slot_w <= 0 or cycle_ms <= 0:
        return 0.0
    phase = (elapsed_ms % cycle_ms) / cycle_ms
    return phase * slot_w


class _ConveyorAnimation(QWidget):
    """Poster-card conveyor (spec §10): blank cards slide left through a fixed
    center beam; cards left of the beam render 'filled'.  One repaint timer
    (the widget's owner drives ``advance()``), QPainter only."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._clock = QElapsedTimer()
        self._active = False
        self._posters: list[QPixmap] = []
        self._scaled_cache: dict[tuple[int, int, int], QPixmap] = {}
        self.setMinimumHeight(_scale.px(180))

    def set_posters(self, pixmaps: list[QPixmap]) -> None:
        self._posters = [p for p in pixmaps if p is not None and not p.isNull()]
        self._scaled_cache.clear()
        self.update()

    def add_poster(self, pixmap: QPixmap) -> None:
        if pixmap is not None and not pixmap.isNull():
            self._posters.append(pixmap)
            self.update()

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        if active:
            self._clock.restart()
        self.update()

    def set_lifecycle(self, lifecycle: ScanLifecycle | None) -> None:
        del lifecycle
        self.update()

    def advance(self) -> None:
        if not self._active:
            return
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(_scale.px(12), _scale.px(12), -_scale.px(12), -_scale.px(12))
        if rect.width() <= 0 or rect.height() <= 0:
            return
        slot_w = max(1, rect.width() // _CARD_COUNT)
        card_h = min(rect.height(), int(slot_w * 1.4))
        card_w = max(_scale.px(24), int(card_h * 2 / 3))
        y = rect.center().y() - card_h // 2
        elapsed = self._clock.elapsed() if self._clock.isValid() else 0
        offset = conveyor_offset(elapsed, slot_w)
        beam_x = rect.center().x()
        radius = _scale.px(6)

        blank = theme.qcolor("surface")
        border = theme.qcolor("border_light")
        filled_wash = theme.qcolor("accent_alt")
        filled_wash.setAlpha(36)

        for index in range(_CARD_COUNT + 2):
            slot_x = rect.left() + index * slot_w - offset
            card_x = slot_x + (slot_w - card_w) / 2.0
            if card_x + card_w < rect.left() or card_x > rect.right():
                continue
            card = QRectF(card_x, y, card_w, card_h)
            center_x = card.center().x()
            painter.setPen(QPen(border, max(1, _scale.px(1))))
            painter.setBrush(blank)
            painter.drawRoundedRect(card, radius, radius)
            if self._active and center_x < beam_x - slot_w * 0.5:
                if self._posters:
                    poster = self._posters[index % len(self._posters)]
                    painter.save()
                    painter.setClipRect(card)
                    dpr = self.devicePixelRatioF()
                    key = (poster.cacheKey(), int(card.width() * dpr), int(card.height() * dpr))
                    scaled = self._scaled_cache.get(key)
                    if scaled is None:
                        scaled = poster.scaled(
                            int(card.width() * dpr), int(card.height() * dpr),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        scaled.setDevicePixelRatio(dpr)
                        if len(self._scaled_cache) > 64:
                            self._scaled_cache.clear()
                        self._scaled_cache[key] = scaled
                    painter.drawPixmap(card.topLeft(), scaled)
                    painter.restore()
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(filled_wash)
                    painter.drawRoundedRect(card, radius, radius)
                    painter.setBrush(border)
                    line_w = card_w - _scale.px(12)
                    painter.drawRoundedRect(
                        QRectF(card.left() + _scale.px(6), card.bottom() - _scale.px(18), line_w, _scale.px(4)), 2, 2
                    )
                    painter.drawRoundedRect(
                        QRectF(card.left() + _scale.px(6), card.bottom() - _scale.px(10), line_w * 0.6, _scale.px(4)), 2, 2
                    )
            if self._active and abs(center_x - beam_x) <= slot_w * 0.5:
                sweep = (beam_x - (center_x - slot_w * 0.5)) / slot_w
                beam_pos = card.left() + card.width() * max(0.0, min(1.0, sweep))
                gradient = QLinearGradient(beam_pos - _scale.px(10), 0.0, beam_pos + _scale.px(10), 0.0)
                lead = theme.qcolor("accent")
                lead.setAlpha(0)
                core = theme.qcolor("accent")
                core.setAlpha(150)
                trail = theme.qcolor("accent_alt")
                trail.setAlpha(0)
                gradient.setColorAt(0.0, lead)
                gradient.setColorAt(0.5, core)
                gradient.setColorAt(1.0, trail)
                painter.fillRect(
                    QRectF(beam_pos - _scale.px(10), card.top(), _scale.px(20), card.height()), gradient
                )


def overall_progress_fraction(
    checklist_len: int, active_index: int | None, done: int, total: int, completed: int
) -> float:
    """Whole-scan progress in [0,1]: each phase is an equal slice; the active
    phase contributes its done/total fraction."""
    if checklist_len <= 0:
        return 0.0
    if active_index is None:
        return max(0.0, min(1.0, completed / checklist_len))
    frac = (max(0, min(done, total)) / total) if total > 0 else 0.0
    return max(0.0, min(1.0, (active_index + frac) / checklist_len))


class ScanProgressWidget(QWidget):
    """Structured progress dashboard for active batch scans."""

    cancel_requested = Signal()

    def __init__(self, media_type: str = "tv", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._elapsed = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._filler_timer = QTimer(self)
        self._filler_timer.setInterval(_FILLER_DELAY_MS)
        self._filler_timer.timeout.connect(self._rotate_filler)
        self._fillers = _TV_FILLERS if media_type == "tv" else _MOVIE_FILLERS
        self._filler_order: list[int] = []
        self._filler_pos = 0
        self._text_update_timer = QElapsedTimer()
        self._current_lifecycle: ScanLifecycle | None = None
        self._completed_lifecycles: set[ScanLifecycle] = set()
        self._checklist = _TV_CHECKLIST if media_type == "tv" else _MOVIE_CHECKLIST
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.setContentsMargins(_scale.px(24), _scale.px(24), _scale.px(24), _scale.px(24))

        card = QFrame()
        card.setProperty("cssClass", "panel")
        card.setFixedWidth(_scale.px(680))
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(_scale.px(10))
        card_layout.setContentsMargins(_scale.px(32), _scale.px(18), _scale.px(32), _scale.px(18))

        kind = "TV Library" if self._media_type == "tv" else "Movie Folder"
        self._title = QLabel(f"Scanning {kind}")
        self._title.setProperty("cssClass", "heading")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._title)

        self._animation = _ConveyorAnimation()
        self._animation.setFixedHeight(_scale.px(200))
        card_layout.addWidget(self._animation)

        phase_row = QHBoxLayout()
        self._phase_label = QLabel("Initializing scan...")
        self._phase_label.setProperty("cssClass", "heading")
        phase_row.addWidget(self._phase_label, stretch=1)
        self._step_label = QLabel("")
        self._step_label.setProperty("cssClass", "caption")
        phase_row.addWidget(
            self._step_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        card_layout.addLayout(phase_row)

        secondary_row = QHBoxLayout()
        self._item_label = ElidedLabel("")
        self._item_label.setProperty("cssClass", "text-dim")
        self._item_label.setFixedHeight(_scale.px(22))
        secondary_row.addWidget(self._item_label, stretch=1)
        self._elapsed_label = QLabel("Elapsed: 0:00")
        self._elapsed_label.setProperty("cssClass", "text-dim")
        self._elapsed_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        secondary_row.addWidget(self._elapsed_label, alignment=Qt.AlignmentFlag.AlignRight)
        card_layout.addLayout(secondary_row)

        bar_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(_scale.px(8))
        self._progress_bar.setTextVisible(False)
        bar_row.addWidget(self._progress_bar, stretch=1)

        self._count_label = QLabel("0/0")
        self._count_label.setFixedWidth(_scale.px(64))
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count_label.setProperty("cssClass", "text-dim")
        bar_row.addWidget(self._count_label)
        card_layout.addLayout(bar_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("cssClass", "secondary")
        self._cancel_btn.setFixedWidth(_scale.px(100))
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        outer.addWidget(card)

    def set_posters(self, pixmaps: list[QPixmap]) -> None:
        self._animation.set_posters(pixmaps)

    def add_poster(self, pixmap: QPixmap) -> None:
        self._animation.add_poster(pixmap)

    def start(self) -> None:
        """Reset the dashboard and start active timers."""
        self._elapsed.start()
        self._elapsed_timer.start()
        self._animation_timer.start()
        self._animation.set_active(True)
        self._animation.set_posters([])
        self._completed_lifecycles.clear()
        self._current_lifecycle = None
        self._step_label.setText("")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._count_label.setText("0/0")
        self._phase_label.setText("Initializing scan...")
        self._set_item_text("Preparing the scanner…")
        self._elapsed_label.setText("Elapsed: 0:00")
        self._text_update_timer.invalidate()
        self._reshuffle_fillers()
        self._filler_timer.start()

    def stop(self) -> None:
        """Stop elapsed and animation timers."""
        self._elapsed_timer.stop()
        self._animation_timer.stop()
        self._filler_timer.stop()
        self._animation.set_active(False)

    def update_progress(
        self,
        lifecycle: str = "",
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str = "",
        message: str = "",
    ) -> None:
        """Update progress display from a ScanProgress payload."""
        parsed_lifecycle = _parse_lifecycle(lifecycle)
        previous_lifecycle = self._current_lifecycle
        if parsed_lifecycle is not None:
            self._set_lifecycle(parsed_lifecycle)
        lifecycle_changed = parsed_lifecycle is not None and parsed_lifecycle != previous_lifecycle

        active = (
            self._checklist.index(self._current_lifecycle)
            if self._current_lifecycle in self._checklist
            else None
        )
        completed = len(self._completed_lifecycles & set(self._checklist))
        fraction = overall_progress_fraction(len(self._checklist), active, done, total, completed)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(int(fraction * 100))
        self._count_label.setText(f"{done}/{total}" if total > 0 else "Working")

        if self._should_update_text(
            lifecycle_changed=lifecycle_changed,
            parsed_lifecycle=parsed_lifecycle,
            done=done,
            total=total,
        ):
            if phase:
                self._phase_label.setText(phase)
            item_text = current_item or message
            if item_text:
                self._set_item_text(item_text)
                if self._elapsed_timer.isActive():
                    self._filler_timer.start()   # restart the 4s no-change window
            self._text_update_timer.restart()

        if parsed_lifecycle in _TERMINAL:
            self.stop()

    def finish(self) -> None:
        """Mark scan as complete."""
        self.stop()
        self._completed_lifecycles.update(self._checklist)
        self._current_lifecycle = None
        self._update_checklist()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._count_label.setText("Done")
        self._phase_label.setText("Scan complete")

    def _set_lifecycle(self, lifecycle: ScanLifecycle) -> None:
        if lifecycle == self._current_lifecycle:
            return
        if lifecycle in _TERMINAL:
            self._completed_lifecycles.update(self._checklist)
            self._current_lifecycle = None
        else:
            self._current_lifecycle = lifecycle
            self._complete_prior_lifecycles(lifecycle)
        self._animation.set_lifecycle(self._current_lifecycle)
        self._update_checklist()

    def _complete_prior_lifecycles(self, lifecycle: ScanLifecycle) -> None:
        if lifecycle not in self._checklist:
            return
        active_index = self._checklist.index(lifecycle)
        self._completed_lifecycles.update(self._checklist[:active_index])

    def _advance_animation(self) -> None:
        self._animation.advance()

    def _set_item_text(self, text: str) -> None:
        self._item_label.setText(text)
        self._item_label.setToolTip(text)

    def _reshuffle_fillers(self, *, avoid_first: int | None = None) -> None:
        order = random.sample(range(len(self._fillers)), len(self._fillers))
        if avoid_first is not None and len(order) > 1 and order[0] == avoid_first:
            order[0], order[-1] = order[-1], order[0]
        self._filler_order = order
        self._filler_pos = 0

    def _rotate_filler(self) -> None:
        if not self._fillers or not self._elapsed_timer.isActive():
            return
        if self._filler_pos >= len(self._filler_order):
            last = self._filler_order[-1] if self._filler_order else None
            self._reshuffle_fillers(avoid_first=last)
        quip = self._fillers[self._filler_order[self._filler_pos]]
        self._filler_pos += 1
        self._item_label.setText(quip)
        self._item_label.setToolTip("")
        # A quip replaced the honest item line, so drop the text throttle:
        # the next real update must reclaim the line immediately.
        self._text_update_timer.invalidate()

    def _should_update_text(
        self,
        *,
        lifecycle_changed: bool,
        parsed_lifecycle: ScanLifecycle | None,
        done: int,
        total: int,
    ) -> bool:
        if lifecycle_changed or parsed_lifecycle in _TERMINAL:
            return True
        if not self._text_update_timer.isValid():
            return True
        if total and done in {0, total}:
            return True
        return self._text_update_timer.elapsed() >= 650

    def _update_elapsed(self) -> None:
        secs = self._elapsed.elapsed() // 1000
        minutes = secs // 60
        seconds = secs % 60
        self._elapsed_label.setText(f"Elapsed: {minutes}:{seconds:02d}")

    def _update_checklist(self) -> None:
        n = len(self._checklist)
        if self._current_lifecycle in self._checklist:
            step = self._checklist.index(self._current_lifecycle) + 1
            self._step_label.setText(f"Step {step} of {n}")
            self._step_label.setToolTip(
                "\n".join(_LIFECYCLE_LABELS.get(lc, str(lc)) for lc in self._checklist)
            )
        else:
            self._step_label.setText("")


def _parse_lifecycle(lifecycle: str | ScanLifecycle) -> ScanLifecycle | None:
    if isinstance(lifecycle, ScanLifecycle):
        return lifecycle
    if not lifecycle:
        return None
    try:
        return ScanLifecycle(lifecycle)
    except ValueError:
        return None

