# GUI V4 Plan 2: Roster Model/Delegate + New Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the roster's per-row live-widget `QListWidget` with a `QListView` + `QAbstractListModel` + `QStyledItemDelegate` (the queue-tab pattern), ship the V4 group taxonomy (incl. the new `Specials & Unmapped Only` group), poster-forward 64×94 rows with season completeness chips, and land the Plan 1 carry-overs (`is_plex_ready_state` rename, dead `history_index` param, TV recent-menu test).

**Architecture:** `RosterModel` holds plain row snapshots (`RosterRowData`) built from `ScanState`; `RosterDelegate` paints everything (toggle, poster, title, status pill, confidence bar+%, chip row, band wash, selection) from theme tokens; a small `RosterListView` subclass routes toggle-clicks without moving selection. The panel keeps its public footer surface (master check / summary / queue button) and gains signals; the six workspace coordinators are rewired from `QListWidgetItem` handles to state-index calls. The preview and detail panels are untouched (3-panel layout still stands until Plan 3).

**Tech Stack:** PySide6 (QListView/QAbstractListModel/QStyledItemDelegate), `gui_qt/theme.py` tokens, `gui_qt/_scale.py` sizing, pytest + existing Qt smoke harness.

## Global Constraints

- Run Python/pytest through the venv: `.venv\Scripts\python.exe -m pytest ...` (Windows).
- `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` must pass at the end of every task.
- No hardcoded `P:\` paths in tests (use `tmp_path`/synthetic fixtures).
- All colors/radii via `gui_qt/theme.py` (`color/qcolor/rgba/radius`) — the no-hex guard test in `tests/test_gui_theme.py` enforces this; never write a hex literal outside `theme.py`. All sizes via `gui_qt/_scale.py` (`px`, `row_height`, `margins`).
- No "Plex" user-facing strings in `gui_qt` (AST guard enforces). The engine constant `PLEX_READY_EPISODE_FLOOR` stays untouched.
- Engine and controller **behavior** unchanged; the only controller/service edits allowed are the mechanical `is_plex_ready_state` → `is_fully_ready_state` rename (Task 2) and view-layer read-model helpers.
- Group keys are settings/test-visible strings — exact values: `queued`, `review-match`, `review-episodes`, `specials-unmapped` *(new)*, `matched`, `fully-ready`, `unmatched`, `duplicate`. Exact group titles: `Queued`, `Needs Review — Match`, `Needs Review — Episodes`, `Specials & Unmapped Only`, `Matched`, `Fully Ready`, `No Match Found`, `Duplicates` (em dash U+2014 in the two review titles).
- Commit after every task with the messages given (append trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`).

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `plex_renamer/gui_qt/widgets/status_chip.py` | create | `ChipSpec` + `season_chip_specs()` builder + chip painting/geometry (shared with Plan 3 season strip) |
| `plex_renamer/gui_qt/widgets/_roster_model.py` | create | `RosterModel`, `RosterRowData`, entry dataclasses, poster fetch/cache |
| `plex_renamer/gui_qt/widgets/_roster_delegate.py` | create | `RosterDelegate` painting + geometry/hit-test helpers, `RosterListView` |
| `plex_renamer/gui_qt/widgets/_media_helpers.py` | modify | new group classifier + taxonomy tables + rename fallout |
| `plex_renamer/app/services/command_gating_service.py` | modify | method rename only |
| `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py` | modify | extract shared `paint_check_indicator` / `paint_mini_progress` statics |
| `plex_renamer/gui_qt/widgets/_media_workspace_roster.py` | rewrite | panel = RosterListView + model + delegate + footer; poster machinery moves to model |
| `plex_renamer/gui_qt/widgets/media_workspace.py` + `_media_workspace_{ui,state,sync,view,refresh,lifecycle}.py` | modify | rewire from item handles to state-index API |
| `plex_renamer/gui_qt/widgets/_workspace_widgets.py` | modify | delete `RosterRowWidget` |
| `tests/test_status_chip.py`, `tests/test_roster_model.py`, `tests/test_roster_delegate.py` | create | unit coverage for the new modules |
| `tests/conftest_qt.py`, `tests/test_qt_media_workspace.py`, `tests/test_qt_queue_history.py`, `tests/test_command_gating_service.py`, `tests/test_media_controller.py`, `tests/test_qt_chrome.py` | modify | helper rewrite + migration + rename fallout + TV recent-menu test |

---

### Task 1: `status_chip.py` — season chip specs + painting

**Files:**
- Create: `plex_renamer/gui_qt/widgets/status_chip.py`
- Test: `tests/test_status_chip.py`

**Interfaces:**
- Consumes: `engine.models.CompletenessReport/SeasonCompleteness`, `gui_qt.theme`, `gui_qt._scale`.
- Produces (used verbatim by Tasks 4–5 and by Plan 3):
  - `ChipSpec(text: str, tone: str, tooltip: str = "")` frozen dataclass; `tone ∈ {"success","warning","muted"}`
  - `season_chip_specs(report: CompletenessReport | None, *, max_chips: int = 6) -> list[ChipSpec]`
  - `chip_row_height() -> int` (physical px)
  - `chip_rects(origin_x: int, origin_y: int, chips: Sequence[ChipSpec], font_metrics: QFontMetrics) -> list[QRect]`
  - `paint_chip_row(painter: QPainter, origin_x: int, origin_y: int, chips: Sequence[ChipSpec]) -> None`

Chip rules (from spec §4): complete season → `S{n} ✓` tone `success`; incomplete → `S{n} {matched}/{expected}` tone `warning`; fully-missing (matched == 0, expected > 0) → `S{n} 0/{expected}` tone `muted`; specials (when `report.specials` present with expected > 0) → `SP {matched}/{expected}` last, `success` when complete else `warning`. When more than `max_chips` season chips would render, collapse **consecutive complete-season runs of length ≥ 2** into `S{a}–S{b} ✓` (en dash U+2013); problem seasons always stay explicit. Incomplete-season tooltips list missing episodes: `Season {n} missing E03, E07` (first 12, then `…`); complete tooltips `Season {n}: {matched}/{expected}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_status_chip.py
"""Season chip spec builder rules (GUI V4 spec §4)."""
from __future__ import annotations

from plex_renamer.engine.models import CompletenessReport, SeasonCompleteness
from plex_renamer.gui_qt.widgets.status_chip import ChipSpec, season_chip_specs


def _season(n, expected, matched, missing=()):
    return SeasonCompleteness(
        season=n, expected=expected, matched=matched,
        missing=[(num, f"Ep {num}") for num in missing],
    )


def _report(seasons, specials=None):
    return CompletenessReport(
        seasons={s.season: s for s in seasons},
        specials=specials,
        total_expected=sum(s.expected for s in seasons),
        total_matched=sum(s.matched for s in seasons),
        total_missing=[],
    )


def test_none_report_yields_no_chips():
    assert season_chip_specs(None) == []


def test_complete_incomplete_and_missing_tones():
    report = _report([
        _season(1, 10, 10),
        _season(2, 10, 9, missing=(4,)),
        _season(3, 8, 0, missing=tuple(range(1, 9))),
    ])
    chips = season_chip_specs(report)
    assert chips[0] == ChipSpec("S1 ✓", "success", "Season 1: 10/10")
    assert chips[1].text == "S2 9/10"
    assert chips[1].tone == "warning"
    assert chips[1].tooltip == "Season 2 missing E04"
    assert chips[2] == ChipSpec("S3 0/8", "muted", "Season 3 missing E01, E02, E03, E04, E05, E06, E07, E08")


def test_specials_chip_appended_last():
    report = _report([_season(1, 5, 5)], specials=_season(0, 3, 2, missing=(3,)))
    chips = season_chip_specs(report)
    assert chips[-1].text == "SP 2/3"
    assert chips[-1].tone == "warning"


def test_complete_runs_collapse_when_over_max():
    seasons = [_season(n, 10, 10) for n in range(1, 7)] + [_season(7, 10, 3, missing=tuple(range(4, 11)))]
    chips = season_chip_specs(_report(seasons), max_chips=6)
    assert chips[0].text == "S1–S6 ✓"
    assert chips[0].tone == "success"
    assert chips[1].text == "S7 3/10"


def test_no_collapse_at_or_under_max():
    seasons = [_season(n, 10, 10) for n in range(1, 6)]
    chips = season_chip_specs(_report(seasons), max_chips=6)
    assert [chip.text for chip in chips] == ["S1 ✓", "S2 ✓", "S3 ✓", "S4 ✓", "S5 ✓"]


def test_missing_tooltip_truncates_after_twelve():
    season = _season(1, 20, 4, missing=tuple(range(5, 21)))
    chips = season_chip_specs(_report([season]))
    assert chips[0].tooltip.endswith(", …")
    assert chips[0].tooltip.count("E") == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_status_chip.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plex_renamer.gui_qt.widgets.status_chip'`.

- [ ] **Step 3: Implement `status_chip.py`**

```python
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

_TONE_COLORS = {"success": "success", "warning": "warning", "muted": "text_dim"}


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


def _season_chip(season: SeasonCompleteness) -> ChipSpec:
    if season.is_complete:
        return ChipSpec(
            f"S{season.season} ✓", "success",
            f"Season {season.season}: {season.matched}/{season.expected}",
        )
    tone = "muted" if season.matched == 0 else "warning"
    return ChipSpec(
        f"S{season.season} {season.matched}/{season.expected}", tone,
        _missing_tooltip(season),
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
        if season.is_complete:
            run.append(season)
            continue
        flush_run()
        chips.append(_season_chip(season))
    flush_run()
    return chips


def season_chip_specs(report: CompletenessReport | None, *, max_chips: int = 6) -> list[ChipSpec]:
    if report is None:
        return []
    seasons = [report.seasons[n] for n in sorted(report.seasons)]
    if len(seasons) > max_chips:
        chips = _collapse_complete_runs(seasons)
    else:
        chips = [_season_chip(season) for season in seasons]
    specials = report.specials
    if specials is not None and specials.expected > 0:
        tone = "success" if specials.is_complete else "warning"
        tooltip = (
            f"Specials: {specials.matched}/{specials.expected}"
            if specials.is_complete
            else _missing_tooltip(specials).replace(f"Season {specials.season}", "Specials", 1)
        )
        chips.append(ChipSpec(f"SP {specials.matched}/{specials.expected}", tone, tooltip))
    return chips


# ── Painting (delegate-side) ─────────────────────────────────────────


def _chip_font():
    font = QGuiApplication.font()
    font.setPointSizeF(max(6.0, font.pointSizeF() - 1.5))
    return font


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
    font = _chip_font()
    painter.setFont(font)
    metrics = QFontMetrics(font)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_status_chip.py -q`
Expected: 6 passed. (Painting helpers get exercised by Task 5's delegate render tests; they need a QGuiApplication, which the smoke base provides.)

- [ ] **Step 5: Run suites, commit**

Run: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass (new module is not yet imported anywhere; if the fast/smoke runner classification tests flag the new test file, add `tests/test_status_chip.py` to the fast list in the same pattern as existing entries).

```bash
git add plex_renamer/gui_qt/widgets/status_chip.py tests/test_status_chip.py tests/test_fast_runner.py
git commit -m "feat(gui): season completeness chip specs + painter (roster/strip shared)"
```

(If the runner-classification tests required no change, commit without those files.)

---

### Task 2: New grouping taxonomy + `Specials & Unmapped Only` + `is_fully_ready_state` rename

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_helpers.py` (classifier + `roster_group`), `plex_renamer/app/services/command_gating_service.py:16` (rename), `plex_renamer/app/controllers/_tv_batch_helpers.py:363` (call site), `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py:12,90` (import/call), `plex_renamer/gui_qt/widgets/_media_workspace_roster.py:218-227` (group table — old widget roster, still standing this task), `plex_renamer/gui_qt/widgets/_media_workspace_refresh.py:57-63,140-144` (group preference tuples)
- Modify tests: `tests/test_command_gating_service.py` (9 refs), `tests/test_media_controller.py:1748`, plus title/order assertions in `tests/test_qt_media_workspace.py` (grep-driven, Step 5)
- Test: `tests/test_qt_media_workspace.py` (new grouping test), `tests/test_command_gating_service.py`

**Interfaces:**
- Consumes: `ScanState.completeness/preview_items/assignments` (existing), `CommandGatingService`.
- Produces: `_media_helpers.is_specials_unmapped_only_state(state) -> bool`; `roster_group` may now return `"specials-unmapped"`; `CommandGatingService.is_fully_ready_state` (old name gone repo-wide); `_media_helpers.is_fully_ready_state`; group order/titles per Global Constraints. Tasks 4–6 build the model on these exact keys/titles.

- [ ] **Step 1: Write the failing classifier tests (append to `tests/test_command_gating_service.py` or a new class in `tests/test_qt_media_workspace.py` if it has a synthetic-state factory — put them wherever `ScanState` fixtures with `completeness`/`preview_items` already exist; `test_qt_media_workspace.py` has `_make_state`-style helpers, check with `grep -n "def _make_state\|ScanState(" tests\test_qt_media_workspace.py | head -20`)**

The test needs three synthetic TV states (build with the file's existing state factory, adding `completeness`):

```python
def test_specials_unmapped_only_grouping(self):
    from plex_renamer.engine.models import CompletenessReport, SeasonCompleteness
    from plex_renamer.gui_qt.widgets._media_helpers import roster_group

    complete_s1 = SeasonCompleteness(season=1, expected=2, matched=2, missing=[])
    incomplete_s1 = SeasonCompleteness(season=1, expected=3, matched=2, missing=[(3, "Three")])

    # A) regular seasons complete; one unmatched specials-ish extra file -> specials-unmapped
    state_a = self._make_review_episode_state()          # existing factory producing has_episode_problems=True
    state_a.completeness = CompletenessReport(
        seasons={1: complete_s1}, specials=None,
        total_expected=2, total_matched=2, total_missing=[],
    )
    for item in state_a.preview_items:                    # force problems onto non-regular rows
        if item.is_episode_review or item.is_unmatched or item.is_conflict:
            item.season = None
    self.assertEqual(roster_group(state_a, media_type="tv"), "specials-unmapped")

    # B) same problems but a regular season is incomplete -> stays review-episodes
    state_b = self._make_review_episode_state()
    state_b.completeness = CompletenessReport(
        seasons={1: incomplete_s1}, specials=None,
        total_expected=3, total_matched=2, total_missing=[(1, 3, "Three")],
    )
    self.assertEqual(roster_group(state_b, media_type="tv"), "review-episodes")

    # C) a problem row on a regular season -> stays review-episodes
    state_c = self._make_review_episode_state()
    state_c.completeness = CompletenessReport(
        seasons={1: complete_s1}, specials=None,
        total_expected=2, total_matched=2, total_missing=[],
    )
    for item in state_c.preview_items:
        if item.is_episode_review or item.is_unmatched or item.is_conflict:
            item.season = 1
    self.assertEqual(roster_group(state_c, media_type="tv"), "review-episodes")
```

Adapt `_make_review_episode_state()` to whatever existing helper builds a state in the review-episodes group (the file has several such tests around lines 2256/2384 — reuse their construction; do NOT invent a new fixture style). Run to verify FAIL (returns `"review-episodes"` for A).

- [ ] **Step 2: Implement the classifier + `roster_group` branch in `_media_helpers.py`**

```python
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
```

In `roster_group`, replace the `has_episode_problems` branch:

```python
    if has_episode_problems(state):
        if is_specials_unmapped_only_state(state):
            return "specials-unmapped"
        return "review-episodes"
```

(`scan_error` keeps returning `"review-episodes"` before this branch, unchanged.)

- [ ] **Step 3: Apply the rename (mechanical, repo-wide)**

`CommandGatingService.is_plex_ready_state` → `is_fully_ready_state` (docstring already de-Plexed in Plan 1). Update every reference:
- `plex_renamer/app/services/command_gating_service.py:16`
- `plex_renamer/app/controllers/_tv_batch_helpers.py:363`
- `plex_renamer/gui_qt/widgets/_media_helpers.py:101-102` — rename the module-level wrapper to `is_fully_ready_state` and its 4 same-file callers (lines 76, 96, 110, 151)
- `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py:12,90` — import/alias
- `tests/test_command_gating_service.py` (9 refs), `tests/test_media_controller.py:1748`

Verify zero stragglers: `grep -rn "is_plex_ready_state" plex_renamer tests` → no hits. `grep -rn "plex" plex_renamer --include=*.py -i` → only `plex_renamer` package identifiers + `PLEX_READY_EPISODE_FLOOR` in `engine/_episode_resolution.py`.

- [ ] **Step 4: New group order/titles in the (still-widget) roster + focus preferences**

`_media_workspace_roster.py` `_desired_entries` groups list becomes (exact order and titles from Global Constraints):

```python
        groups = [
            ("queued", "Queued"),
            ("review-match", "Needs Review — Match"),
            ("review-episodes", "Needs Review — Episodes"),
            ("specials-unmapped", "Specials & Unmapped Only"),
            ("matched", "Matched"),
            ("fully-ready", "Fully Ready"),
            ("unmatched", "No Match Found"),
            ("duplicate", "Duplicates"),
        ]
```

`_media_workspace_refresh.py`: in `refresh_from_controller` the auto-focus group guard set `{"matched", "review-match", "review-episodes"}` gains `"specials-unmapped"`; in `preferred_batch_focus_index` the preference tuple `("matched", "review-match", "review-episodes")` becomes `("matched", "review-match", "review-episodes", "specials-unmapped")`.

- [ ] **Step 5: Migrate title/order assertions, run suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py tests\test_command_gating_service.py tests\test_media_controller.py -q` and fix fallout mechanically:
- `grep -n "REVIEW EPISODE MATCHING\|REVIEW MATCH" tests\test_qt_media_workspace.py` — `_assert_roster_section_title` expectations become `"NEEDS REVIEW — EPISODES"` / `"NEEDS REVIEW — MATCH"` (helper strips arrow + `(count)`; headers render uppercase).
- Order-sensitive row indices: review groups now render **before** `MATCHED` and `FULLY READY` renders after `MATCHED` (e.g. the test around line 3808 asserting `MATCHED` at row 0 and review at row 2 swaps to review at 0, `MATCHED` at 2). Fix each failure by reading the test's states and applying the new order — do not blindly swap.
- Status pill strings ("Review Episode Matching") are NOT renamed — only group titles. If a test asserts a *status* string, leave it.

Then: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer tests
git commit -m "feat(gui): V4 roster taxonomy - Specials & Unmapped Only group, new titles/order, is_fully_ready_state rename"
```

---

### Task 3: Extract shared paint statics from the primitive widgets

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`
- Test: `tests/test_qt_workspace_widgets.py` (extend — this file already renders primitives)

**Interfaces:**
- Consumes: theme tokens.
- Produces (Task 5 paints with these):
  - `paint_check_indicator(painter: QPainter, rect: QRectF, state: Qt.CheckState) -> None` — the rounded-square + check glyph drawing currently duplicated in `MasterCheckBox.paintEvent` and `ToggleSwitch.paintEvent`
  - `paint_mini_progress(painter: QPainter, rect: QRect, *, value: int, color: QColor) -> None` — the track+fill drawing from `MiniProgressBar.paintEvent`

- [ ] **Step 1: Write the failing test (append to `tests/test_qt_workspace_widgets.py`)**

```python
def test_paint_statics_render_without_error(self):
    from PySide6.QtCore import QRect, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from plex_renamer.gui_qt import theme
    from plex_renamer.gui_qt.widgets._workspace_widget_primitives import (
        paint_check_indicator,
        paint_mini_progress,
    )

    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    for state in (Qt.CheckState.Unchecked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Checked):
        paint_check_indicator(painter, QRectF(2, 2, 20, 20), state)
    paint_mini_progress(painter, QRect(2, 40, 60, 4), value=55, color=theme.qcolor("success"))
    painter.end()
    self.assertFalse(image.isNull())
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q` → FAIL (ImportError).

- [ ] **Step 2: Implement — extract, then delegate the widget paintEvents**

Add module-level functions to `_workspace_widget_primitives.py`:

```python
def _check_palette(state: Qt.CheckState) -> tuple[QColor, QColor]:
    if state == Qt.CheckState.Checked:
        return theme.qcolor("success"), theme.qcolor("success_dim")
    if state == Qt.CheckState.PartiallyChecked:
        return theme.qcolor("info"), theme.qcolor("info")
    return theme.qcolor("border_light"), theme.qcolor("border_light")


def paint_check_indicator(painter: QPainter, rect: QRectF, state: Qt.CheckState) -> None:
    """Rounded check indicator shared by MasterCheckBox, ToggleSwitch, and the roster delegate."""
    bg, border = _check_palette(state)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(bg)
    painter.setPen(QPen(border, 1.5))
    painter.drawRoundedRect(rect, 4, 4)
    pen = QPen(theme.qcolor("on_accent"), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    size = rect.width()
    left, top = rect.x(), rect.y()
    if state == Qt.CheckState.Checked:
        painter.drawLine(int(left + size * 0.25), int(top + size * 0.50), int(left + size * 0.43), int(top + size * 0.68))
        painter.drawLine(int(left + size * 0.43), int(top + size * 0.68), int(left + size * 0.75), int(top + size * 0.32))
    elif state == Qt.CheckState.PartiallyChecked:
        y = int(top + size / 2)
        painter.drawLine(int(left + size * 0.28), y, int(left + size * 0.72), y)
    painter.restore()


def paint_mini_progress(painter: QPainter, rect: QRect, *, value: int, color: QColor) -> None:
    """4px track+fill bar shared by MiniProgressBar and the roster delegate."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.qcolor("border"))
    painter.drawRoundedRect(rect, 2, 2)
    clamped = max(0, min(100, value))
    fill_width = int(rect.width() * (clamped / 100.0))
    if fill_width > 0:
        fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
        painter.setBrush(color)
        painter.drawRoundedRect(fill_rect, 2, 2)
    painter.restore()
```

Then rewrite `ToggleSwitch.paintEvent` and `MiniProgressBar.paintEvent` bodies to call the statics (`ToggleSwitch`: build `QRectF(1.5, 1.5, size-3, size-3)` and call `paint_check_indicator`; `MiniProgressBar`: `paint_mini_progress(painter, self.rect(), value=self._value, color=self._color)`). `MasterCheckBox.paintEvent` keeps its own text drawing but uses `paint_check_indicator` for the box. Delete the now-unused per-class `_BG_*`/`_BORDER_*`/`_CHECK_COLOR` constants **only if** nothing else references them (`grep -rn "_BG_ON\|_BG_OFF\|_BG_PARTIAL\|_BORDER_ON\|_BORDER_OFF\|_CHECK_COLOR" plex_renamer tests`).

- [ ] **Step 3: Run suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q` → pass.
Run: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass (visual parity: same drawing code, now shared).

- [ ] **Step 4: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py tests/test_qt_workspace_widgets.py
git commit -m "refactor(gui): extract shared check/progress paint statics for delegate reuse"
```

---

### Task 4: `RosterModel` — read-model over ScanStates

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_roster_model.py`
- Test: `tests/test_roster_model.py`

**Interfaces:**
- Consumes: `_media_helpers` (`roster_group`, `roster_item_key`, `state_status`, `state_status_tone`, `confidence_band`, `confidence_fill_color`, `is_state_queue_approvable`, `placeholder_initials`), `status_chip.season_chip_specs`, `_formatting.clamped_percent`, `_image_utils.pil_to_raw/raw_to_pixmap`, `RosterPosterBridge`, `thread_pool.submit`.
- Produces (Task 5 paints from, Task 6 wires to):

```python
KIND_ROLE          = Qt.ItemDataRole.UserRole + 1   # "header" | "state"
GROUP_ROLE         = Qt.ItemDataRole.UserRole + 2   # group key str (headers)
STATE_INDEX_ROLE   = Qt.ItemDataRole.UserRole + 3   # int (state rows)
ENTRY_KEY_ROLE     = Qt.ItemDataRole.UserRole + 4   # stable identity str
ROW_DATA_ROLE      = Qt.ItemDataRole.UserRole + 5   # RosterRowData (state rows)
POSTER_ROLE        = Qt.ItemDataRole.UserRole + 6   # QPixmap | None

@dataclass(frozen=True, slots=True)
class RosterRowData:
    title: str
    status_text: str          # e.g. "FULLY READY" (upper)
    status_tone: str          # "success"|"info"|"error"|"muted"|"accent"
    band: str                 # "high"|"medium"|"low"|"muted"|"error"
    confidence_pct: int       # 0..100
    confidence_color: str     # hex str from theme via confidence_fill_color
    checked: bool
    checkable: bool
    chips: tuple[ChipSpec, ...]
    tooltip: str              # "" or duplicate-of note
    poster_key: tuple[str, int] | None
    placeholder_initials: str
    placeholder_accent: str   # hex str (status color) for placeholder pixmap

class RosterModel(QAbstractListModel):
    poster_loaded = Signal()  # emitted after any poster lands (tests/interest)
    def __init__(self, *, media_type: str, settings_service=None, tmdb_provider=None, parent=None): ...
    def set_states(self, states: list[ScanState], *, collapsed_groups: dict[str, bool]) -> None
    def refresh_state(self, state_index: int) -> None
    def entry_kind_at(self, row: int) -> str | None                 # "header"|"state"|None
    def group_at(self, row: int) -> str | None
    def state_index_at(self, row: int) -> int | None
    def row_for_state_index(self, state_index: int) -> int          # -1 when absent/collapsed
    def header_row_before(self, row: int) -> int                    # -1 when none
    def set_compact(self, compact: bool) -> None                    # re-snapshot + layoutChanged
    def is_compact(self) -> bool
```

Behavior contract: `set_states` = `beginResetModel`/`endResetModel`, rebuilding an internal entry list in the Task 2 group order (header entry per non-empty group with `(count)` and collapse arrow; state entries omitted while collapsed — exactly `_desired_entries` semantics). Header DisplayRole text = `f"{arrow}  {title.upper()} ({count})"` with `arrow = "▶" if collapsed else "▼"` (keeps the section-title test helper convention). `refresh_state` rebuilds that one row's `RosterRowData` and emits `dataChanged` for just that row with `[ROW_DATA_ROLE, Qt.ItemDataRole.DisplayRole]`. `flags`: headers → `ItemIsEnabled`; state rows → `ItemIsEnabled | ItemIsSelectable` (no `ItemIsUserCheckable` — the delegate owns the toggle). Poster pipeline (moved verbatim from the old panel): LRU cache (`OrderedDict`, max 128) keyed `(media_type, show_id)`, in-flight set, `RosterPosterBridge` + `thread_pool.submit` worker calling `tmdb.fetch_poster(show_id, media_type=..., target_width=...)`, `target_width = max(220, min(420, _scale.px(64) * 2))`; on arrival emit `dataChanged` with `[POSTER_ROLE]` for every row whose key matches + `poster_loaded`. Requests fire for all state entries during `set_states` (parity with today's behavior of building every row). `RosterRowData` snapshots: `status_text = state_status(state)[0].upper()`, tooltip = `f"Same match as {state.duplicate_of_relative_folder or state.duplicate_of}"` when `state.duplicate_of` else `""`, `chips = tuple(season_chip_specs(state.completeness))` for tv non-compact, `()` for movies or compact mode, `checkable = is_state_queue_approvable(state, media_type=...)`, `checked = state.checked`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roster_model.py
"""RosterModel row composition, roles, and dataChanged granularity."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _make_state(name: str, *, queued=False, checked=True):
    from plex_renamer.engine.models import ScanState

    state = ScanState(folder=Path(f"C:/lib/{name}"), media_info={"id": hash(name) % 100000, "name": name, "year": "2020"})
    state.scanned = True
    state.queued = queued
    state.checked = checked
    state.confidence = 0.9
    return state


class RosterModelTests(QtSmokeBase):
    def _model(self, states, collapsed=None):
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        model = RosterModel(media_type="tv")
        model.set_states(states, collapsed_groups=collapsed or {})
        return model

    def test_header_and_state_rows_in_group_order(self):
        from plex_renamer.gui_qt.widgets import _roster_model as rm

        queued = _make_state("Queued Show", queued=True)
        matched = _make_state("Matched Show")
        model = self._model([matched, queued])
        # queued group renders before matched
        self.assertEqual(model.entry_kind_at(0), "header")
        self.assertEqual(model.group_at(0), "queued")
        self.assertIn("QUEUED (1)", model.index(0, 0).data())
        self.assertEqual(model.entry_kind_at(1), "state")
        self.assertEqual(model.state_index_at(1), 1)
        self.assertEqual(model.group_at(2), "matched")
        self.assertEqual(model.state_index_at(3), 0)
        self.assertEqual(model.rowCount(), 4)

    def test_collapsed_group_hides_state_rows_and_flips_arrow(self):
        matched = _make_state("Matched Show")
        model = self._model([matched], collapsed={"matched": True})
        self.assertEqual(model.rowCount(), 1)
        self.assertTrue(model.index(0, 0).data().startswith("▶"))
        self.assertEqual(model.row_for_state_index(0), -1)

    def test_row_data_snapshot_fields(self):
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        state = _make_state("Frieren")
        model = self._model([state])
        data = model.index(1, 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.title, "Frieren (2020)")
        self.assertEqual(data.confidence_pct, 90)
        self.assertTrue(data.checked)
        self.assertEqual(data.chips, ())   # no completeness -> no chips

    def test_refresh_state_emits_single_row_datachanged(self):
        state = _make_state("Frieren")
        model = self._model([state])
        seen: list[tuple[int, int]] = []
        model.dataChanged.connect(lambda tl, br, roles=(): seen.append((tl.row(), br.row())))
        state.checked = False
        model.refresh_state(0)
        self.assertEqual(seen, [(1, 1)])
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE
        self.assertFalse(model.index(1, 0).data(ROW_DATA_ROLE).checked)

    def test_header_row_before(self):
        states = [_make_state("A"), _make_state("B")]
        model = self._model(states)
        self.assertEqual(model.header_row_before(2), 0)
        self.assertEqual(model.header_row_before(0), -1)

    def test_headers_not_selectable(self):
        from PySide6.QtCore import Qt

        model = self._model([_make_state("A")])
        self.assertFalse(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsSelectable)
        self.assertTrue(model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsSelectable)
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_roster_model.py -q` → FAIL (module missing).

- [ ] **Step 2: Implement `_roster_model.py`**

Full implementation per the interface block above. Skeleton (fill in the poster pipeline by MOVING the code from `_media_workspace_roster.py:344-398` — same logic, model-owned):

```python
# plex_renamer/gui_qt/widgets/_roster_model.py
"""Read-model exposing ScanStates to the roster QListView (GUI V4 §7)."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QPixmap

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from .. import _scale
from ._formatting import clamped_percent
from ._image_utils import pil_to_raw, raw_to_pixmap
from ._media_helpers import (
    confidence_band as _confidence_band,
    confidence_fill_color as _confidence_fill_color,
    is_state_queue_approvable as _is_state_queue_approvable,
    placeholder_initials as _placeholder_initials,
    roster_group as _roster_group,
    roster_item_key as _roster_item_key,
    state_status as _state_status,
    state_status_tone as _state_status_tone,
)
from ._workspace_widget_primitives import RosterPosterBridge
from .status_chip import ChipSpec, season_chip_specs

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
GROUP_ROLE = Qt.ItemDataRole.UserRole + 2
STATE_INDEX_ROLE = Qt.ItemDataRole.UserRole + 3
ENTRY_KEY_ROLE = Qt.ItemDataRole.UserRole + 4
ROW_DATA_ROLE = Qt.ItemDataRole.UserRole + 5
POSTER_ROLE = Qt.ItemDataRole.UserRole + 6

_MAX_POSTER_CACHE = 128

ROSTER_GROUPS: tuple[tuple[str, str], ...] = (
    ("queued", "Queued"),
    ("review-match", "Needs Review — Match"),
    ("review-episodes", "Needs Review — Episodes"),
    ("specials-unmapped", "Specials & Unmapped Only"),
    ("matched", "Matched"),
    ("fully-ready", "Fully Ready"),
    ("unmatched", "No Match Found"),
    ("duplicate", "Duplicates"),
)
```

then `RosterRowData`, `_HeaderEntry(group, title_text)` / `_StateEntry(state_index, key, row_data)` internal dataclasses, and `RosterModel` implementing the contract. `_build_row_data(state)`:

```python
    def _build_row_data(self, state: ScanState) -> RosterRowData:
        status_text, status_color = _state_status(state, media_type=self._media_type)
        chips: tuple[ChipSpec, ...] = ()
        if self._media_type == "tv" and not self._compact:
            chips = tuple(season_chip_specs(state.completeness))
        tooltip = ""
        if state.duplicate_of is not None:
            tooltip = f"Same match as {state.duplicate_of_relative_folder or state.duplicate_of}"
        poster_key = (self._media_type, state.show_id) if state.show_id is not None else None
        return RosterRowData(
            title=state.display_name,
            status_text=status_text.upper(),
            status_tone=_state_status_tone(state, media_type=self._media_type),
            band=_confidence_band(state.confidence, state=state, media_type=self._media_type),
            confidence_pct=clamped_percent(state.confidence),
            confidence_color=_confidence_fill_color(state.confidence, state=state, media_type=self._media_type),
            checked=bool(state.checked),
            checkable=_is_state_queue_approvable(state, media_type=self._media_type),
            chips=chips,
            tooltip=tooltip,
            poster_key=poster_key,
            placeholder_initials=_placeholder_initials(state.display_name),
            placeholder_accent=status_color.name(),
        )
```

`set_states` keeps a reference to the live `states` list (for `refresh_state`), builds entries per `ROSTER_GROUPS`, requests posters for every state entry with a `poster_key` not already cached. `data()` returns: DisplayRole → header text or state title; `ToolTipRole` → row_data.tooltip; the custom roles per the table; `POSTER_ROLE` → cached pixmap or `None`. `set_compact` re-snapshots all state entries (chips on/off) and emits `layoutChanged`.

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_roster_model.py -q` → 6 passed.

- [ ] **Step 4: Run suites, commit**

Run: `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass (model not yet wired; add `tests/test_roster_model.py` to the smoke/fast runner classification lists following the existing pattern — it constructs a QApplication via `QtSmokeBase`, so classify it with the Qt files).

```bash
git add plex_renamer/gui_qt/widgets/_roster_model.py tests/test_roster_model.py tests/test_fast_runner.py tests/test_smoke_runner.py
git commit -m "feat(gui): RosterModel read-model with group taxonomy, snapshots, poster cache"
```

---

### Task 5: `RosterDelegate` + `RosterListView`

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_roster_delegate.py`
- Test: `tests/test_roster_delegate.py`

**Interfaces:**
- Consumes: Task 4 roles + `RosterRowData`, Task 3 paint statics, Task 1 `paint_chip_row/chip_rects/chip_row_height`, `_image_utils.build_placeholder_pixmap/scale_pixmap_for_device`, theme + `_scale`.
- Produces:

```python
class RosterDelegate(QStyledItemDelegate):
    def __init__(self, view: QListView, *, media_type: str, parent=None): ...
    def set_compact(self, compact: bool) -> None
    # geometry helpers (used by the view's hit-testing and by tests):
    def toggle_rect(self, option_rect: QRect, row_data: RosterRowData) -> QRect
    def sizeHint(...), paint(...), helpEvent(...)   # chip tooltips via chip_rects

class RosterListView(QListView):
    toggle_clicked = Signal(QModelIndex)      # pressed inside a checkable row's toggle rect
    header_clicked = Signal(str)              # group key
```

Geometry contract (all `_scale.px`, logical units given): outer margin 8; toggle 20×20 top-left; poster 64×94 after toggle+8 (normal tv/movie mode; movie rows vertically center the poster); body starts after poster+8. Normal row height = `px(110)`; compact row height = `px(56)` (no poster, no chips); header row height = `px(34)`. Body: title (up to 2 lines, `ElideRight` on the second) with the status pill right-aligned on the first line (pill: uppercase `status_text`, height `px(18)`, h-padding `px(8)`, radius `theme.radius("pill")`, bg = tone wash 0.12 alpha, fg = tone color); confidence row = 4px bar (`paint_mini_progress`, width `px(110)`) + `f"{pct}%"` caption in `text_dim`; chip row at bottom via `paint_chip_row`. Tone→color mapping (matches the Plan 1 QSS pill remap where `tone="accent"` renders warning): `{"success": "success", "info": "info", "error": "error", "muted": "text_dim", "accent": "warning", "warning": "warning"}`. Backgrounds: base rounded-rect `radius_md` filled `card`; band washes over it — high → `rgba(success, 0.05)`, medium → `rgba(warning, 0.05)`, low/error → `rgba(error, 0.06)`, muted → none; hover (State_MouseOver) → `card_hover`; selected → `selection_bg` fill + 1px `accent` border (selected wins over band/hover). Headers: full-width `section_header_bg` fill (no radius), bold uppercase `accent` text, left padding `px(12)`. Poster: `POSTER_ROLE` pixmap via `scale_pixmap_for_device`, else `build_placeholder_pixmap(size, title=row_data.placeholder_initials, subtitle="", accent=row_data.placeholder_accent, device_pixel_ratio=...)` (no shimmer in delegate — static placeholder until the pixmap lands). Toggle: `paint_check_indicator`, drawn only when `row_data.checkable`.

`RosterListView.mousePressEvent`: resolve index; if state row and checkable and press inside `toggle_rect` → emit `toggle_clicked(index)`, remember the index, and **return without calling super()** (selection must not move — parity with today's separate ToggleSwitch widget); if header row → emit `header_clicked(group)` and return; else default handling. `mouseReleaseEvent`: if the release matches a remembered intercepted press, clear it and return without calling super() (so the release can't move selection either). Enable `setMouseTracking(True)` in `__init__`, `setSelectionMode(SingleSelection)`, `setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)`, `setVerticalScrollMode(ScrollPerPixel)`, `setUniformItemSizes(False)`, `setProperty("cssClass", "row-host-list")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roster_delegate.py
"""RosterDelegate geometry, painting smoke, and RosterListView hit-testing."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _make_state(name: str):
    from plex_renamer.engine.models import ScanState

    state = ScanState(folder=Path(f"C:/lib/{name}"), media_info={"id": 7, "name": name, "year": "2020"})
    state.scanned = True
    state.confidence = 0.9
    return state


class RosterDelegateTests(QtSmokeBase):
    def _view(self, states, collapsed=None):
        from plex_renamer.gui_qt.widgets._roster_delegate import RosterDelegate, RosterListView
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        model = RosterModel(media_type="tv")
        model.set_states(states, collapsed_groups=collapsed or {})
        view = RosterListView()
        delegate = RosterDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(380, 600)
        return view, model, delegate

    def test_size_hints_differ_by_kind_and_mode(self):
        from plex_renamer.gui_qt import _scale

        view, model, delegate = self._view([_make_state("A")])
        header_h = view.sizeHintForRow(0)
        state_h = view.sizeHintForRow(1)
        self.assertEqual(header_h, _scale.px(34))
        self.assertEqual(state_h, _scale.px(110))
        delegate.set_compact(True)
        model.set_compact(True)
        self.assertEqual(view.sizeHintForRow(1), _scale.px(56))

    def test_render_grab_produces_pixels(self):
        view, model, delegate = self._view([_make_state("A")])
        view.show()
        pixmap = view.grab()
        self.assertFalse(pixmap.toImage().isNull())
        view.close()

    def test_toggle_click_emits_without_moving_selection(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        view, model, delegate = self._view([_make_state("A")])
        view.show()
        toggled: list[int] = []
        view.toggle_clicked.connect(lambda index: toggled.append(index.row()))
        index = model.index(1, 0)
        rect = view.visualRect(index)
        row_data = index.data(ROW_DATA_ROLE)
        target = delegate.toggle_rect(rect, row_data).center()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
        self.assertEqual(toggled, [1])
        self.assertNotEqual(view.currentIndex().row(), 1)
        view.close()

    def test_header_click_emits_group(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        view, model, delegate = self._view([_make_state("A")])
        view.show()
        groups: list[str] = []
        view.header_clicked.connect(groups.append)
        rect = view.visualRect(model.index(0, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(groups, ["matched"])
        view.close()
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_roster_delegate.py -q` → FAIL (module missing).

- [ ] **Step 2: Implement `_roster_delegate.py`**

Implement per the contract. Key excerpts the implementer must match exactly:

```python
_MARGIN_U = 8
_TOGGLE_U = 20
_POSTER_W_U, _POSTER_H_U = 64, 94
_ROW_NORMAL_U, _ROW_COMPACT_U, _ROW_HEADER_U = 110, 56, 34
_PILL_H_U, _PILL_HPAD_U = 18, 8
_BAR_W_U = 110

_TONE_COLOR = {
    "success": "success", "info": "info", "error": "error",
    "muted": "text_dim", "accent": "warning", "warning": "warning",
}

_BAND_WASH = {"high": ("success", 0.05), "medium": ("warning", 0.05),
              "low": ("error", 0.06), "error": ("error", 0.06)}
```

`paint` order for state rows: card base → band wash → hover/selected overlay (+accent border when selected, 1px, radius `md`) → toggle (if checkable) → poster → title (QTextOption wrap, max 2 lines: compute with `QFontMetrics.elidedText` on the second line) → pill → confidence bar + pct → chips. `helpEvent`: if the point is inside a chip rect (via `chip_rects` with the same origin used in paint) show that chip's tooltip, else fall back to the row tooltip (`ToolTipRole`). `sizeHint` returns `QSize(0, px(...))` per kind/mode. Poster device-pixel handling copies `scale_pixmap_for_device(pixmap, QSize(px(64), px(94)), device_pixel_ratio=view.devicePixelRatioF())`.

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_roster_delegate.py -q` → 4 passed.
If `QTest` is unavailable in the environment, replace `QTest.mouseClick` with synthesized `QMouseEvent`s posted via `QApplication.sendEvent` — check how existing smoke tests simulate clicks first (`grep -n "QTest\|mouseClick\|sendEvent" tests\test_qt_media_workspace.py | head`) and follow that convention.

- [ ] **Step 4: Run suites, commit**

Run: `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass (add `tests/test_roster_delegate.py` to runner classification lists like Task 4 did).

```bash
git add plex_renamer/gui_qt/widgets/_roster_delegate.py tests/test_roster_delegate.py tests/test_fast_runner.py tests/test_smoke_runner.py
git commit -m "feat(gui): roster delegate + list view - painted rows, chips, toggle hit-testing"
```

---

### Task 6: Panel cutover + coordinator rewiring + test migration

This is the cutover task: the roster panel swaps to model/view, `RosterRowWidget` dies, and every coordinator/test touchpoint moves to the state-index API. The suite is red mid-task and green again before the commit.

**Files:**
- Rewrite: `plex_renamer/gui_qt/widgets/_media_workspace_roster.py`
- Modify: `plex_renamer/gui_qt/widgets/media_workspace.py` (lines 26, 31-34, 137-149, 189-196, 213-220, 298-311), `_media_workspace_ui.py:76-98` (+ splitter sizes line 70), `_media_workspace_state.py` (roster methods), `_media_workspace_sync.py` (roster methods + imports), `_media_workspace_view.py:70-94`, `_media_workspace_refresh.py:28-32,70-79`, `_media_workspace_lifecycle.py:45-53`, `_workspace_widgets.py` (delete `RosterRowWidget` + its helper fns if unused elsewhere)
- Modify tests: `tests/conftest_qt.py` (helpers), `tests/test_qt_media_workspace.py` (~85 sites, mechanical per the migration table), `tests/test_qt_queue_history.py` (1 site)

**Interfaces:**
- Consumes: Tasks 4–5.
- Produces the rebuilt panel API (everything else in the app talks to the roster through this):

```python
class MediaWorkspaceRosterPanel(QFrame):
    state_selected = Signal(int)          # view current changed onto a state row
    check_toggled = Signal(int, bool)     # (state_index, new_checked)
    group_toggled = Signal(str)           # group key
    # kept from today: master_check / selection_summary / queue_button properties,
    # update_selection_header(states), set_queue_button_text(text)
    @property
    def model(self) -> RosterModel
    @property
    def view(self) -> RosterListView
    def sync_items(self, states, *, collapsed_groups) -> None
    def refresh_state(self, state_index: int) -> None
    def current_state_index(self) -> int | None
    def set_current_state(self, state_index: int) -> bool          # False when row absent (collapsed)
    def scroll_state_into_context(self, state_index: int) -> None  # header-anchored PositionAtTop
    def set_compact(self, compact: bool) -> None
    def is_compact(self) -> bool
```

- [ ] **Step 1: Rebuild `_media_workspace_roster.py`**

Delete the QListWidget/`setItemWidget`/poster/`processEvents` machinery (poster code moved to the model in Task 4). New panel:

```python
"""Roster panel: RosterListView + RosterModel + RosterDelegate (GUI V4 §3.1/§7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QSize

from ...engine import ScanState
from .. import _scale
from ._media_helpers import is_state_queue_approvable as _is_state_queue_approvable
from ._roster_delegate import RosterDelegate, RosterListView
from ._roster_model import KIND_ROLE, ROW_DATA_ROLE, RosterModel
from ._workspace_widget_primitives import MasterCheckBox as _MasterCheckBox

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService


class MediaWorkspaceRosterPanel(QFrame):
    state_selected = Signal(int)
    check_toggled = Signal(int, bool)
    group_toggled = Signal(str)

    def __init__(self, *, media_type: str, settings_service: "SettingsService | None" = None,
                 tmdb_provider=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._syncing = False
        self._model = RosterModel(
            media_type=media_type, settings_service=settings_service, tmdb_provider=tmdb_provider,
        )
        self._build_ui()

    # footer properties (master_check/selection_summary/queue_button),
    # set_queue_button_text, update_selection_header: copied UNCHANGED from
    # the old panel (they operate on states, not items).

    def _build_ui(self) -> None:
        self.setProperty("cssClass", "panel")
        self.setProperty("panelVariant", "square")
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._view = RosterListView()
        self._delegate = RosterDelegate(self._view, media_type=self._media_type)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.toggle_clicked.connect(self._on_toggle_clicked)
        self._view.header_clicked.connect(self._on_header_clicked)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self._view, stretch=1)
        # Footer block (master check + selection summary + queue button):
        # copy the `footer = QHBoxLayout()` block verbatim from the old
        # panel's _build_ui, then `layout.addLayout(footer)`.

    @property
    def model(self) -> RosterModel:
        return self._model

    @property
    def view(self) -> RosterListView:
        return self._view

    def sync_items(self, states: list[ScanState], *, collapsed_groups: dict[str, bool]) -> None:
        previous = self.current_state_index()
        self._syncing = True
        try:
            self._model.set_states(states, collapsed_groups=collapsed_groups)
        finally:
            self._syncing = False
        if previous is not None:
            self.set_current_state(previous)

    def refresh_state(self, state_index: int) -> None:
        self._model.refresh_state(state_index)

    def current_state_index(self) -> int | None:
        index = self._view.currentIndex()
        if not index.isValid():
            return None
        return self._model.state_index_at(index.row())

    def set_current_state(self, state_index: int) -> bool:
        row = self._model.row_for_state_index(state_index)
        if row < 0:
            return False
        self._syncing = True
        try:
            self._view.setCurrentIndex(self._model.index(row, 0))
        finally:
            self._syncing = False
        return True

    def scroll_state_into_context(self, state_index: int) -> None:
        row = self._model.row_for_state_index(state_index)
        if row < 0:
            return
        anchor_row = self._model.header_row_before(row)
        anchor = self._model.index(anchor_row if anchor_row >= 0 else row, 0)
        self._view.scrollTo(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

    def set_compact(self, compact: bool) -> None:
        self._delegate.set_compact(compact)
        self._model.set_compact(compact)

    def is_compact(self) -> bool:
        return self._model.is_compact()

    # ── internal slots ────────────────────────────────────────────
    def _on_toggle_clicked(self, index: QModelIndex) -> None:
        state_index = self._model.state_index_at(index.row())
        row_data = index.data(ROW_DATA_ROLE)
        if state_index is None or row_data is None or not row_data.checkable:
            return
        self.check_toggled.emit(state_index, not row_data.checked)

    def _on_header_clicked(self, group: str) -> None:
        self.group_toggled.emit(group)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        state_index = self._model.state_index_at(current.row())
        if state_index is not None:
            self.state_selected.emit(state_index)
```

**Selection restore on `sync_items`** (capture + `set_current_state`) replaces the old item-identity survival; the panel's `_syncing` guard prevents feedback loops — the workspace-level `_roster_syncing` flag keeps its role for coordinator-side suppression.

- [ ] **Step 2: Rewire the coordinators (exact touchpoint map)**

| Site | Old | New |
|---|---|---|
| `_media_workspace_ui.py:70` | `setSizes([320, 540, 380])` | `setSizes([380, 500, 360])` (spec §3.1 wider roster) |
| `_media_workspace_ui.py:76-98` | ctor callbacks + 3 `_roster_list` signal connects + `workspace._roster_list` alias | ctor loses `set_item_check_state_callback`/`prompt_assign_season_callback`; connect `panel.state_selected → workspace._on_roster_state_selected`, `panel.check_toggled → workspace._on_roster_check_toggled`, `panel.group_toggled → workspace._on_roster_group_toggled`; delete the `workspace._roster_list` alias entirely |
| `media_workspace.py:26,31-34` | imports of `_ROSTER_ENTRY_KIND_ROLE`, `_RosterRowWidget` | delete (keep `_PreviewRowWidget` import) |
| `media_workspace.py:137-149` `toggle_focused_check` | currentItem + item roles | `state_index = self._roster_panel.current_state_index()`; guard `None`/range; `self._set_roster_check_state(state_index, not states[state_index].checked)` |
| `media_workspace.py:192-196` | `_find_roster_item_by_index`, `_set_roster_current_item` | replace with `_set_roster_current_state(self, state_index, *, auto_selected)` delegating to the state coordinator |
| `media_workspace.py:213-220` | `_on_roster_item_clicked/_on_roster_current_item_changed/_on_roster_item_changed` | `_on_roster_group_toggled(group)` → state coordinator; `_on_roster_state_selected(state_index)` → sync coordinator; `_on_roster_check_toggled(state_index, checked)` → sync coordinator |
| `media_workspace.py:307-311` | `_set_item_check_state(item, checked, preview=False)` roster path | new `_set_roster_check_state(self, state_index, checked)` → sync coordinator; preview path keeps the item-based method |
| `_media_workspace_state.py` | `find_roster_item_by_index`, `set_roster_current_item` (pending-auto dance), `on_roster_item_clicked`, `selected_state` via currentItem | `set_roster_current_state(state_index, *, auto_selected)` — same pending-auto logic but `panel.set_current_state(state_index)`; `selected_state()` reads `panel.current_state_index()`; `on_roster_group_toggled(group)` = old `on_roster_item_clicked` body from the `group =` line down (flip `_roster_collapsed`, resync under `_roster_syncing`) **plus** capture/restore handled inside `panel.sync_items` |
| `_media_workspace_sync.py` | `on_roster_current_item_changed(current)` | `on_roster_state_selected(state_index)`: keep the pending-auto/auto bookkeeping and the `select_show → ensure_check_bindings → populate_preview → render_detail → update_action_bar` body; drop `sync_row_selection(_roster_list)` (delegate paints selection) |
| `_media_workspace_sync.py` | `on_roster_item_changed(item)` | `on_roster_check_toggled(state_index, checked)`: guard `_roster_syncing`; range-check; `set_state_checked(state, checked)`; `workspace._roster_panel.refresh_state(state_index)`; `update_action_bar`; `render_detail(state)` when `state_index == panel.current_state_index()` |
| `_media_workspace_sync.py` `_sync_current_roster_row_checked(checked)` | item data + widget set_checked | `current = panel.current_state_index()`; if not None → `panel.refresh_state(current)` |
| `_media_workspace_sync.py` `sync_row_selection` | touches roster + preview widgets | keep ONLY the preview branch; remove `_RosterRowWidget` import |
| `_media_workspace_sync.py` `set_item_check_state` | dual roster/preview | preview-only now; add `set_roster_check_state(state_index, checked)` implementing the roster branch semantics (guard `_roster_syncing`, then `on_roster_check_toggled`) |
| `_media_workspace_view.py:70-94` | `restore_roster_selection_by_key` + `scroll_roster_item_into_context` | restore: find index by key, then `workspace._set_roster_current_state(index, auto_selected=...)` + `panel.scroll_state_into_context(index)`; delete `scroll_roster_item_into_context` (panel owns it); remove role import |
| `_media_workspace_refresh.py:28-32` | `_roster_list.setUpdatesEnabled` | `workspace._roster_panel.view.setUpdatesEnabled(...)` |
| `_media_workspace_refresh.py:70-79` | `find_roster_item_by_index` + `_set_roster_current_item` + trailing `sync_row_selection(_roster_list)` | `workspace._set_roster_current_state(selected_index, auto_selected=selection_is_auto)`; delete the trailing roster `sync_row_selection` call |
| `_media_workspace_lifecycle.py:45-53` | `_roster_list.setIconSize(...)` | `workspace._roster_panel.set_compact(compact)` |
| `_workspace_widgets.py` | `RosterRowWidget` class | delete; delete `_should_show_season_assignment`/`_state_spans_multiple_seasons`/`_known_non_special_season_count`/`_percent_from_label` **only if** unreferenced after deletion (`grep -rn "<name>" plex_renamer tests`); remove unused imports |

The `prompt_assign_season` roster affordance is dead UI (the old widget declared `season_assign_requested` but no longer builds the button that emitted it — nothing fires) — the callback wiring is dropped with the panel rebuild; season assignment stays reachable via the detail panel's inline action. Note this in the commit body.

Verify nothing references the removed surface: `grep -rn "_roster_list\|RosterRowWidget\|_ROSTER_ENTRY\|_CHECKED_ROLE\|find_roster_item_by_index\|set_roster_current_item\|scroll_roster_item_into_context" plex_renamer` → only `_CHECKED_ROLE` hits allowed are preview-related definitions (move `_CHECKED_ROLE` into `_media_workspace_preview.py` if it lived in the roster module — preview still uses it).

- [ ] **Step 3: Rewrite the conftest helpers, migrate tests**

`tests/conftest_qt.py` — replace `_roster_widget_for_index` and `_assert_roster_section_title`:

```python
    def _roster_row_data_for_index(self, workspace, index: int):
        """RosterRowData snapshot for the state at controller index, or None."""
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        model = workspace._roster_panel.model
        row = model.row_for_state_index(index)
        if row < 0:
            return None
        return model.index(row, 0).data(ROW_DATA_ROLE)

    def _assert_roster_section_title(self, workspace, row: int, expected: str) -> None:
        model = workspace._roster_panel.model
        text = (model.index(row, 0).data() or "").strip()
        normalized = text.removeprefix("▼").removeprefix("▶").strip()
        if " (" in normalized:
            normalized = normalized.split(" (", 1)[0]
        self.assertEqual(normalized, expected)
```

Migration table for `tests/test_qt_media_workspace.py` (~85 sites) and `tests/test_qt_queue_history.py` (1 site) — apply mechanically, running the file per class to converge:

| Old pattern | New pattern |
|---|---|
| `self._roster_widget_for_index(ws, i)` + `assertIsInstance(w, _RosterRowWidget)` | `data = self._roster_row_data_for_index(ws, i)` + `assertIsNotNone(data)` |
| widget attr reads: `w._check.isChecked()` / `w._title.text()` | `data.checked` / `data.title` |
| meta-line asserts (`w._meta.text()`, "file(s)", match summary) | delete the assertion (meta line removed by spec §5); if the test's purpose was duplicate labeling, assert `data.tooltip` instead |
| `ws._roster_list.count()` | `ws._roster_panel.model.rowCount()` |
| `ws._roster_list.item(n)` header checks (`.data(CheckStateRole) is None`) | `ws._roster_panel.model.entry_kind_at(n) == "header"` |
| `ws._roster_list.setCurrentItem(item_for_index_i)` / `find_item_by_index` | `ws._roster_panel.set_current_state(i)` |
| `ws._roster_list.currentItem()`-based selected checks | `ws._roster_panel.current_state_index()` |
| `ws._roster_list.iconSize().width() == 32` (compact test, line ~1381) | `self.assertTrue(ws._roster_panel.is_compact())` |
| `ws._roster_list.mapTo(...)` geometry probe (line ~97) | `ws._roster_panel.view.mapTo(...)` |
| `from ...media_workspace import ..., _RosterRowWidget` | drop the symbol from the import |
| `ws._roster_list.itemWidget(...)` poster/refresh asserts (~3308, 4213-4219) | poster: assert `model.index(row,0).data(POSTER_ROLE)` transitions None→pixmap after `model.poster_loaded`; refresh-identity tests: assert `row_for_state_index` stability + `ROW_DATA_ROLE` content change |

Preview-panel helpers (`_preview_widget_for_index`, `_preview_header_texts`) are untouched.

- [ ] **Step 4: Run the full suites and converge**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py -q` repeatedly while migrating (it's the bulk); then `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py tests\test_roster_model.py tests\test_roster_delegate.py -q`; then `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → all pass, zero skips introduced.

- [ ] **Step 5: Commit**

```bash
git add -A plex_renamer/gui_qt tests
git commit -m "feat(gui): roster cutover to model/view - delegate-painted rows, poster-forward layout, no per-row widgets"
```

---

### Task 7: Carry-overs, verification, bookkeeping

**Files:**
- Modify: `plex_renamer/gui_qt/_main_window_shell.py:17,22` + `plex_renamer/gui_qt/main_window.py:94` (dead `history_index`), `tests/test_qt_chrome.py` (TV recent-menu test), `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Drop the dead `history_index` ctor param**

In `_main_window_shell.py` remove the `history_index` parameter and `self._history_index` assignment (sole reader was deleted in Plan 1); update the `main_window.py:94` construction call site. Verify: `grep -rn "history_index" plex_renamer tests` → zero hits (History-tab index handling elsewhere uses different names — if the grep shows unrelated hits, leave those and only remove the shell coordinator's).

- [ ] **Step 2: Add the symmetric TV recent-menu test (extend `tests/test_qt_chrome.py`)**

Mirror `test_recent_movie_folder_switches_to_movies_tab` exactly, with `add_recent_tv_folder`, `window._recent_tv_menu`, `window._tv_workspace.load_folder` mocked, starting from the Movies tab (`setCurrentIndex(2)`), asserting `currentIndex() == 1` and the load call. Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_chrome.py -q` → all pass (new test fails only if the TV path is actually broken — it isn't; this is regression armor, watch it pass on first run and confirm the movie-path test still passes too).

- [ ] **Step 3: Full verification**

Run: `scripts\test-fast.cmd` → pass. `scripts\test-smoke.cmd` → pass (skim `.pytest_cache/smoke/latest.log`).
Manual sanity launch: `.venv\Scripts\python.exe -m plex_renamer --qt` → roster shows poster-forward rows (64×94), chips under titles on TV shows with completeness data, status pills visible, group headers in the new order with `Needs Review — *` titles, Fully Ready collapsed, toggle click checks without changing selection, group header click collapses, selection = blue border card. Close. (Headless alternative: offscreen `window.grab()` screenshot via a throwaway test, inspected, then deleted — as done for Plan 1.)

- [ ] **Step 4: Update roadmap + handoff, commit**

Mark Plan 2 landed in the roadmap table (update the row-2 filename link to `2026-07-03-gui-v4-plan2-roster.md`); handoff: status + next step → "write Plan 3 (work panel) via superpowers:writing-plans", note the roster now renders via model/view and `RosterRowWidget` is gone (Plan 3 does the same to the preview/detail panels).

```bash
git add plex_renamer tests docs/superpowers/plans
git commit -m "chore(gui): plan-2 carry-overs (history_index, TV recent-menu test) + docs"
```

---

## Self-review notes (kept for the record)

- **Spec coverage:** §3.1 wider roster (splitter 380) ✓, poster 64×94 ✓, meta clutter removed ✓, confidence bar+% ✓, pill shown ✓, chips row ✓ (Task 1+5), taxonomy + order + Specials & Unmapped Only ✓ (Task 2), review groups float above the fold ✓ (order), Fully Ready collapsed default ✓ (existing `_roster_collapsed` init), selection accent border, no fringe ✓ (delegate); §4 roster chips ✓ (strip = Plan 3); §7 roster model/delegate ✓, dataChanged granularity ✓ (Task 4 test), no `processEvents` in the new roster path ✓ (old loop deleted with the panel rewrite; preview's remains until Plan 5).
- **Deliberate scope choices:** status pill *strings* unchanged (spec renames groups, not statuses); `warm_preview_cache` deletion stays in Plan 5 (preview-side); `hide_already_named` setting untouched (upstream of the roster); shimmer not replicated inside the delegate (static placeholder until poster lands — widget-based overlay can't live in a delegate); roster-side season-assign affordance dropped as dead UI (documented in Task 6).
- **Type consistency check:** `RosterRowData` fields match between Task 4 (definition/build) and Task 5/6 consumers; `ChipSpec` signature identical across Tasks 1/4/5; panel API names identical across Task 6's table and the panel code block.
