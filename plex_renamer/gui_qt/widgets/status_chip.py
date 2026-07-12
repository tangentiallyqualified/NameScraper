# plex_renamer/gui_qt/widgets/status_chip.py
"""Season/status chips shared by the roster delegate and (Plan 3) season strip.

Pure spec building is Qt-free so unit tests stay off the GUI stack;
painting helpers take an explicit QPainter and are used inside delegates.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPainter, QPen

from ...engine.models import CompletenessReport, SeasonCompleteness
from .. import _scale, theme

_MISSING_TOOLTIP_LIMIT = 12
_CHIP_HPAD_UNITS = 6
_CHIP_SPACING_UNITS = 4
_CHIP_HEIGHT_UNITS = 18

_TONE_COLORS = {
    "success": "success", "warning": "warning", "muted": "text_dim",
    "info": "info",
}


@dataclass(frozen=True, slots=True)
class ChipSpec:
    text: str
    tone: str  # "success" | "warning" | "muted"
    tooltip: str = ""


def _missing_tooltip(season: SeasonCompleteness) -> str:
    numbers = [num for num, _title in season.missing[:_MISSING_TOOLTIP_LIMIT]]
    listed = ", ".join(f"E{num:02d}" for num in numbers)
    if len(season.missing) > _MISSING_TOOLTIP_LIMIT:
        listed += ", …"
    return f"Season {season.season} missing {listed}"


def _season_clean_complete(season: SeasonCompleteness) -> bool:
    return season.is_complete and season.review == 0


def _specials_tooltip(specials: SeasonCompleteness) -> str:
    """Mirror ``_season_chip``'s tooltip assembly for specials: review-aware
    "awaiting approval" line first, then the missing line, joined."""
    if _season_clean_complete(specials):
        return f"Specials: {specials.matched}/{specials.expected}"
    tooltip_parts = []
    if specials.review:
        tooltip_parts.append(
            f"Specials: {specials.review} mapping(s) awaiting approval"
        )
    if specials.missing:
        tooltip_parts.append(_missing_tooltip(specials).replace(f"Season {specials.season}", "Specials", 1))
    return "\n".join(tooltip_parts)


def _season_chip(season: SeasonCompleteness) -> ChipSpec:
    if _season_clean_complete(season):
        return ChipSpec(
            f"S{season.season} ✓", "success",
            f"Season {season.season}: {season.matched}/{season.expected}",
        )
    shown = season.matched + season.review
    tone = "muted" if shown == 0 else "warning"
    tooltip_parts = []
    if season.review:
        tooltip_parts.append(
            f"Season {season.season}: {season.review} mapping(s) awaiting approval"
        )
    if season.missing:
        tooltip_parts.append(_missing_tooltip(season))
    return ChipSpec(
        f"S{season.season} {shown}/{season.expected}", tone,
        "\n".join(tooltip_parts),
    )


def _collapse_complete_runs(seasons: list[SeasonCompleteness]) -> list[ChipSpec]:
    chips: list[ChipSpec] = []
    run: list[SeasonCompleteness] = []

    def flush_run() -> None:
        if not run:
            return
        if len(run) == 1:
            chips.append(_season_chip(run[0]))
        else:
            first, last = run[0].season, run[-1].season
            chips.append(ChipSpec(f"S{first}–S{last} ✓", "success", f"Seasons {first}–{last} complete"))
        run.clear()

    for season in seasons:
        if _season_clean_complete(season):
            run.append(season)
            continue
        flush_run()
        chips.append(_season_chip(season))
    flush_run()
    return chips


def season_chip_specs(
    report: CompletenessReport | None, *, max_chips: int = 6, drop_empty: bool = False
) -> list[ChipSpec]:
    if report is None:
        return []
    seasons = [report.seasons[n] for n in sorted(report.seasons)]
    if drop_empty:
        seasons = [s for s in seasons if (s.matched + s.review) > 0]
    if len(seasons) > max_chips:
        chips = _collapse_complete_runs(seasons)
    else:
        chips = [_season_chip(season) for season in seasons]
    specials = report.specials
    if (
        specials is not None
        and specials.expected > 0
        and not (drop_empty and (specials.matched + specials.review) == 0)
    ):
        tone = "success" if _season_clean_complete(specials) else "warning"
        tooltip = _specials_tooltip(specials)
        chips.append(ChipSpec(f"SP {specials.matched + specials.review}/{specials.expected}", tone, tooltip))
    return chips


def _strip_season_chip(season: SeasonCompleteness) -> ChipSpec:
    """Like ``_season_chip`` but complete seasons keep their count (season
    strip chips are uncollapsed and always show ``matched``/``expected``)."""
    if _season_clean_complete(season):
        return ChipSpec(
            f"S{season.season} ✓{season.expected}", "success",
            f"Season {season.season}: {season.matched}/{season.expected}",
        )
    shown = season.matched + season.review
    tone = "muted" if shown == 0 else "warning"
    tooltip_parts = []
    if season.review:
        tooltip_parts.append(
            f"Season {season.season}: {season.review} mapping(s) awaiting approval"
        )
    if season.missing:
        tooltip_parts.append(_missing_tooltip(season))
    return ChipSpec(
        f"S{season.season} {shown}/{season.expected}", tone,
        "\n".join(tooltip_parts),
    )


def season_strip_specs(report: CompletenessReport | None) -> list[tuple[int, ChipSpec]]:
    """Season-strip chip specs: one per season (sorted) + specials last as
    season 0. Unlike ``season_chip_specs`` these never collapse complete
    runs — the strip always shows every season with its count."""
    if report is None:
        return []
    specs: list[tuple[int, ChipSpec]] = [
        (season_num, _strip_season_chip(report.seasons[season_num]))
        for season_num in sorted(report.seasons)
    ]
    specials = report.specials
    if specials is not None and specials.expected > 0:
        tone = "success" if _season_clean_complete(specials) else "warning"
        tooltip = _specials_tooltip(specials)
        specs.append((0, ChipSpec(f"SP {specials.matched + specials.review}/{specials.expected}", tone, tooltip)))
    return specs


# ── Painting (delegate-side) ─────────────────────────────────────────


def _chip_font():
    font = QGuiApplication.font()
    font.setPointSizeF(max(6.0, font.pointSizeF() - 1.5))
    return font


def chip_font_metrics() -> QFontMetrics:
    """Metrics for the chip font — hit-testing must use these, not the view
    font, or tooltip rects drift off the painted chips."""
    return QFontMetrics(_chip_font())


def chip_row_height() -> int:
    return _scale.px(_CHIP_HEIGHT_UNITS)


def chip_rects(
    origin_x: int,
    origin_y: int,
    chips: Sequence[ChipSpec],
    font_metrics: QFontMetrics,
) -> list[QRect]:
    rects: list[QRect] = []
    x = origin_x
    height = chip_row_height()
    pad = _scale.px(_CHIP_HPAD_UNITS)
    spacing = _scale.px(_CHIP_SPACING_UNITS)
    for chip in chips:
        width = font_metrics.horizontalAdvance(chip.text) + 2 * pad
        rects.append(QRect(x, origin_y, width, height))
        x += width + spacing
    return rects


def paint_chip_row(painter: QPainter, origin_x: int, origin_y: int, chips: Sequence[ChipSpec]) -> None:
    if not chips:
        return
    painter.save()
    painter.setFont(_chip_font())
    metrics = chip_font_metrics()
    radius = theme.radius("sm")
    for chip, rect in zip(chips, chip_rects(origin_x, origin_y, chips, metrics)):
        tone_token = _TONE_COLORS[chip.tone]
        fill = theme.qcolor(tone_token)
        fill.setAlphaF(0.12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QPen(theme.qcolor(tone_token)))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), chip.text)
    painter.restore()


def chip_rects_wrapped(
    origin_x: int,
    origin_y: int,
    chips: Sequence[ChipSpec],
    font_metrics: QFontMetrics,
    max_width: int,
) -> list[QRect]:
    """Lay chips left-to-right, wrapping to a new row when the next chip would
    exceed ``origin_x + max_width``. The first chip on a row is always placed
    even if it alone exceeds ``max_width`` (never drop a chip)."""
    rects: list[QRect] = []
    x = origin_x
    y = origin_y
    height = chip_row_height()
    pad = _scale.px(_CHIP_HPAD_UNITS)
    spacing = _scale.px(_CHIP_SPACING_UNITS)
    for chip in chips:
        width = font_metrics.horizontalAdvance(chip.text) + 2 * pad
        if x > origin_x and (x + width) > (origin_x + max_width):
            x = origin_x
            y += height + spacing
        rects.append(QRect(x, y, width, height))
        x += width + spacing
    return rects


def chip_wrapped_height(
    chips: Sequence[ChipSpec], font_metrics: QFontMetrics, max_width: int
) -> int:
    if not chips:
        return 0
    rects = chip_rects_wrapped(0, 0, chips, font_metrics, max_width)
    return max(rect.bottom() for rect in rects) - rects[0].top() + 1


def paint_chip_row_wrapped(
    painter: QPainter,
    origin_x: int,
    origin_y: int,
    chips: Sequence[ChipSpec],
    max_width: int,
) -> None:
    if not chips:
        return
    painter.save()
    painter.setFont(_chip_font())
    metrics = chip_font_metrics()
    radius = theme.radius("sm")
    rects = chip_rects_wrapped(origin_x, origin_y, chips, metrics, max_width)
    for chip, rect in zip(chips, rects):
        tone_token = _TONE_COLORS[chip.tone]
        fill = theme.qcolor(tone_token)
        fill.setAlphaF(0.12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QPen(theme.qcolor(tone_token)))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), chip.text)
    painter.restore()
