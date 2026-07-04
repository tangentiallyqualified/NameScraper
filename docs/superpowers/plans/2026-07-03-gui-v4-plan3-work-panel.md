# GUI V4 Plan 3: Work Panel (Episode Table + Expansion + 2-Panel Cutover) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the middle preview panel and right detail panel with one work panel — show header / season strip / toolbar / delegate-painted episode table with in-place expansion / footer — completing the 2-panel workspace for both TV and movie modes (spec §3.2/§3.3/§4/§5/§7).

**Architecture:** `EpisodeTableModel` (flat `QAbstractListModel`, same pattern as Plan 2's `RosterModel`) composes section/season-header/episode/ghost/unmapped/duplicate/orphan/folder rows from `ScanState` + `EpisodeGuide`; `EpisodeTableDelegate` paints everything; the expanded row is the single live widget via `openPersistentEditor` (`EpisodeExpansionCard`). `MediaWorkPanel` assembles header/strip/toolbar/table/footer and exposes the same button aliases the existing action-bar system drives, so queue/fix-match orchestration is untouched. The guide builder, `EpisodeMappingService` actions, and `handle_episode_row_action` are reused verbatim — this plan is view-layer only.

**Tech Stack:** PySide6 (QListView/QAbstractListModel/QStyledItemDelegate/persistent editors), theme tokens, `_scale`, `status_chip`, existing `SegmentedControl`, pytest + Qt smoke harness.

## Global Constraints

- Run Python/pytest through the venv: `.venv\Scripts\python.exe -m pytest ...` (Windows).
- `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` must pass at the end of every task; new Qt test files get added to the runner classification lists in `scripts/` (NOT `tests/` — Plan 2 confirmed the location) following the existing pattern.
- No hardcoded `P:\` paths in tests. No hex literals outside `theme.py` (guard enforced). No "Plex" strings in gui_qt (AST guard). All sizes via `_scale`.
- Engine, controllers, and services unchanged: `EpisodeMappingService`, `episode_guide_for_state` / `refresh_episode_guide` (controller projection cache), `build_queue_preflight`, `EpisodeAssignDialog` are consumed as-is. Guide building stays synchronous this plan (async + BusyOverlay = Plan 5).
- Episode row action ids are frozen API: `approve`, `reassign`, `assign_to_more`, `unassign`, `keep_this`, `assign_file` — `MediaWorkspaceActionCoordinator.handle_episode_row_action(state, row, action_id)` handles all of them already.
- Status→tone mapping for pills/bands (V4 semantics; "Review" is warning, not accent): `Mapped→success`, `Review→warning`, `Conflict→error`, `Missing File→muted`, `Unassigned→warning`, `Duplicate→muted`, `Orphan Companion→muted`.
- Footer breakdown format (spec §3.2.5, exact): `{total} files · {mapped} mapped · {companions} companions · {unmapped} unmapped · {duplicates} duplicates` — omit any ` · N <noun>` segment whose count is 0, but always show `{total} files` and `{mapped} mapped`.
- Bulk Assign and the Unassign-All danger treatment are Plan 4 — this plan wires `Unassign All` as a plain secondary button with today's behavior.
- Commit after every task with the messages given (trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`).

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `plex_renamer/gui_qt/widgets/_episode_table_model.py` | create | `EpisodeTableModel`, `EpisodeRowData`, role constants; TV + movie row composition, filters, search, expansion bookkeeping |
| `plex_renamer/gui_qt/widgets/_episode_table_delegate.py` | create | `EpisodeTableDelegate` (paints all row kinds, chevron, flash) + `EpisodeTableView` (hit-testing, Enter-to-expand) |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py` | create | `EpisodeExpansionCard` persistent-editor widget + `episode_row_actions(row)` (moved from the preview panel) |
| `plex_renamer/gui_qt/widgets/_work_panel.py` | create | `MediaWorkPanel`: show header (async overview), season strip, toolbar, table hosting, footer |
| `plex_renamer/gui_qt/widgets/status_chip.py` | modify | add `season_strip_specs(report)` (uncollapsed, `S1 ✓28`-style complete chips) |
| `media_workspace.py` + `_media_workspace_{ui,state,sync,view,refresh}.py` | modify | 2-panel cutover, table/expansion wiring, alias rebinding |
| `_media_workspace_preview.py`, `media_detail_panel.py`, `_media_detail_{artwork,payloads,state,workflow}.py`, `_workspace_widgets.py` | **delete** | replaced by the above |
| `tests/test_episode_table_model.py`, `tests/test_episode_table_delegate.py`, `tests/test_episode_expansion.py`, `tests/test_work_panel.py` | create | unit coverage |
| `tests/conftest_qt.py`, `tests/test_qt_media_workspace.py`, others per grep | modify | helper rewrite + preview/detail test migration |

---

### Task 1: `EpisodeTableModel` — read-model over ScanState + EpisodeGuide

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_episode_table_model.py`
- Test: `tests/test_episode_table_model.py`

**Interfaces:**
- Consumes: `EpisodeGuide`/`EpisodeGuideRow` (`app/models/state_models.py`), `EpisodeMappingService.build_episode_guide` (fallback when no provider), `_media_helpers` (`season_label`, `preview_status_label`, `preview_status_tone`, `is_state_queue_approvable`, `state_key`), `_formatting.clamped_percent`.
- Produces (Tasks 2–5 build on these exact names):

```python
ROW_KIND_ROLE      = Qt.ItemDataRole.UserRole + 1   # str, see kinds below
SECTION_KEY_ROLE   = Qt.ItemDataRole.UserRole + 2   # str | None (headers + their member rows)
PREVIEW_INDEX_ROLE = Qt.ItemDataRole.UserRole + 3   # int | None (index into state.preview_items)
GUIDE_ROW_ROLE     = Qt.ItemDataRole.UserRole + 4   # EpisodeGuideRow | None
ROW_DATA_ROLE      = Qt.ItemDataRole.UserRole + 5   # EpisodeRowData
EXPANDED_ROLE      = Qt.ItemDataRole.UserRole + 6   # bool

# Row kinds: "section-header" (collapsible season or FOLDER header),
# "section-label" (non-collapsible: Unmapped/Duplicates/Orphans),
# "episode" (incl. ghost rows — status "Missing File"), "unmapped",
# "duplicate", "orphan", "folder", "movie-file".

@dataclass(frozen=True, slots=True)
class EpisodeRowData:
    kind: str
    title: str
    status_text: str = ""
    status_tone: str = ""          # success|warning|error|muted
    filename: str = ""             # inline filename line ("" hides it)
    target: str = ""
    confidence_pct: int | None = None
    checked: bool | None = None    # movie-file rows only
    checkable: bool = False
    collapsed: bool = False        # section-header rows
    companion_count: int = 0
    tooltip: str = ""

class EpisodeTableModel(QAbstractListModel):
    def __init__(self, *, media_type: str, settings_service=None, guide_provider=None, parent=None): ...
    def show_state(self, state: ScanState | None, *, collapsed_sections: set[str],
                   folder_preview: tuple[str, str] | None = None) -> None
    def state(self) -> ScanState | None
    def guide(self) -> EpisodeGuide | None              # None for movies/empty
    def set_filter_mode(self, mode: str) -> None        # "all" | "problems" | "unmapped"
    def filter_mode(self) -> str
    def set_search_text(self, text: str) -> None        # casefold substring; "" = off
    def search_text(self) -> str
    def toggle_section(self, section_key: str) -> None  # mutates the collapsed set passed to show_state, rebuilds
    def summary_text(self) -> str                       # footer breakdown per Global Constraints format
    def row_kind_at(self, row: int) -> str | None
    def preview_index_at(self, row: int) -> int | None
    def guide_row_at(self, row: int) -> "EpisodeGuideRow | None"
    def row_for_preview_index(self, preview_index: int) -> int          # -1 when absent
    def section_header_row(self, section_key: str) -> int               # -1 when absent
    def season_section_key(self, season: int) -> str                    # f"episode-guide-season:{season}"
    def first_problem_row_in_season(self, season: int) -> int           # first non-Mapped row; -1
    def set_expanded_row(self, row: int | None) -> None                 # dataChanged on old+new with [EXPANDED_ROLE]
    def expanded_row(self) -> int | None
    def refresh_checks(self) -> None                    # movie: re-snapshot checked flags, dataChanged whole span with [ROW_DATA_ROLE]
```

Composition contract (TV, in order — matches today's preview panel exactly): FOLDER collapsible section (when `folder_preview_data` yields a plan — the model takes `folder_preview: tuple[str, str] | None` as a `show_state` keyword); `Unmapped Primary Files (N)` label + rows (filters: all/problems/unmapped); `Duplicate Copies (N)` label + rows (all/problems); per-season collapsible sections sorted by season number — header title `season_label(season, name=state.season_names.get(season, "")) + f" — {mapped}/{expected}"` (ratio only when completeness has the season with expected > 0) + `" · missing E03, E07"` (first 3 missing episode numbers + `, …` when more, only when incomplete); season rows honor filter (`problems` drops `Mapped`, `unmapped` drops all guide rows) and the auto-collapse rule (a season whose rows are ALL `Missing File` gets `section_key` added to the collapsed set once, guarded by the `f"{section_key}:auto-collapsed"` sentinel — copy the logic from `_media_workspace_preview.py:414-425` verbatim); `Orphan Companion Files (N)` label + rows (all/problems/unmapped). Ghost rows are simply guide rows with status `Missing File` (the guide builder already emits them) — no synthesis. When `state.scan_error` is set, the model renders exactly one `section-label` row titled `f"Scan failed: {state.scan_error}"` (tone `error` in its `EpisodeRowData.status_tone`) instead of guide content — the §17 inline-error surface (async failures wire into the same row in Plan 5). Search text filters episode/unmapped/duplicate/orphan/movie rows by casefold substring over title, filename, and target (section headers stay; empty sections are dropped entirely). Episode row `EpisodeRowData`: `title=f"S{row.season:02d}E{row.episode:02d} · {row.title}"` (no ` · ` suffix when `row.title` is empty), `filename=row.primary_file.original.name if row.primary_file is not None and settings view_mode != "compact" else ""`, `target=row.target_rename`, `confidence_pct` parsed from `row.confidence_label` (reuse `_percent_from_label` — move it into this module from `_workspace_widgets.py`), `companion_count=len(row.companions)`. Movie composition: FOLDER section then one `movie-file` row per preview item (`title=preview.original.name`, `status_text=preview_status_label(preview)`, `status_tone` per Global Constraints mapping of `preview_status_tone` (map `accent→warning`), `target=preview.new_name or ""`, `checked=state.check_vars[str(i)].get()` when actionable+approvable else `None`, `checkable` accordingly, `confidence_pct=clamped_percent(preview.episode_confidence)`). `summary_text()`: TV from `guide.summary` (`total = mapped_primary_files + companion_files + unmapped_primary_files + duplicate_files`); movie from preview items (`total=len(items)`, `mapped=#actionable`, `companions=sum(len(p.companions))`, `unmapped=0`, `duplicates=#is_duplicate`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_episode_table_model.py
"""EpisodeTableModel row composition, filters, search, expansion."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _guide_state():
    """Synthetic TV state with a real assignment table + completeness."""
    from plex_renamer.engine.models import (
        CompletenessReport, ScanState, SeasonCompleteness,
    )
    from plex_renamer.app.models.state_models import (
        EpisodeGuide, EpisodeGuideRow, EpisodeGuideSummary, UnmappedFileRow,
    )
    from plex_renamer.engine.models import PreviewItem

    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 7, "name": "Show", "year": "2020"})
    state.scanned = True
    p1 = PreviewItem(original=Path("C:/lib/Show/s01e01.mkv"), new_name="Show - S01E01 - One.mkv",
                     target_dir=None, season=1, episodes=[1], status="OK")
    p2 = PreviewItem(original=Path("C:/lib/Show/s01e02.mkv"), new_name="Show - S01E02 - Two.mkv",
                     target_dir=None, season=1, episodes=[2], status="REVIEW: episode confidence below threshold")
    state.preview_items = [p1, p2]
    state.completeness = CompletenessReport(
        seasons={1: SeasonCompleteness(season=1, expected=3, matched=2, missing=[(3, "Three")])},
        specials=None, total_expected=3, total_matched=2, total_missing=[(1, 3, "Three")],
    )
    guide = EpisodeGuide(rows=[
        EpisodeGuideRow(season=1, episode=1, title="One", primary_file=p1,
                        target_rename="Show - S01E01 - One.mkv", status="Mapped",
                        confidence_label="96%", overview="Ep one.", air_date="2020-01-01"),
        EpisodeGuideRow(season=1, episode=2, title="Two", primary_file=p2,
                        target_rename="Show - S01E02 - Two.mkv", status="Review",
                        confidence_label="61%"),
        EpisodeGuideRow(season=1, episode=3, title="Three", status="Missing File"),
    ], unmapped_primary_files=[UnmappedFileRow(original=Path("C:/lib/Show/extra.mkv"), reason="no episode parsed")],
       summary=EpisodeGuideSummary(mapped_episodes=2, mapped_primary_files=2, companion_files=0,
                                   missing_episodes=1, unmapped_primary_files=1))
    return state, guide


class EpisodeTableModelTests(QtSmokeBase):
    def _model(self, state, guide, collapsed=None, folder_preview=None):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=collapsed if collapsed is not None else set(),
                         folder_preview=folder_preview)
        return model

    def test_tv_composition_order_and_kinds(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        kinds = [model.row_kind_at(row) for row in range(model.rowCount())]
        # unmapped label+row, season header, 3 episode rows (incl. ghost)
        self.assertEqual(kinds, ["section-label", "unmapped", "section-header",
                                 "episode", "episode", "episode"])

    def test_ghost_row_is_missing_file_episode(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        data = model.index(5, 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.status_text, "Missing File")
        self.assertEqual(data.status_tone, "muted")
        self.assertEqual(data.title, "S01E03 · Three")

    def test_season_header_shows_ratio_and_missing(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        header_row = model.section_header_row(model.season_section_key(1))
        text = model.index(header_row, 0).data()
        self.assertIn("Season 1", text)
        self.assertIn("2/3", text)
        self.assertIn("missing E03", text)

    def test_problems_filter_drops_mapped_keeps_review_and_ghost(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        model.set_filter_mode("problems")
        titles = [model.index(r, 0).data() for r in range(model.rowCount())
                  if model.row_kind_at(r) == "episode"]
        self.assertEqual(len(titles), 2)
        self.assertNotIn("S01E01 · One", titles)

    def test_search_filters_by_filename(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        model.set_search_text("s01e02")
        episode_rows = [r for r in range(model.rowCount()) if model.row_kind_at(r) == "episode"]
        self.assertEqual(len(episode_rows), 1)
        model.set_search_text("")
        self.assertEqual(len([r for r in range(model.rowCount()) if model.row_kind_at(r) == "episode"]), 3)

    def test_collapse_hides_member_rows(self):
        state, guide = _guide_state()
        collapsed: set[str] = set()
        model = self._model(state, guide, collapsed=collapsed)
        key = model.season_section_key(1)
        model.toggle_section(key)
        self.assertIn(key, collapsed)
        self.assertEqual([model.row_kind_at(r) for r in range(model.rowCount())],
                         ["section-label", "unmapped", "section-header"])

    def test_expanded_row_roundtrip_emits_expanded_role(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EXPANDED_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        events: list[tuple[int, int]] = []
        model.dataChanged.connect(lambda tl, br, roles=(): events.append((tl.row(), br.row())))
        model.set_expanded_row(3)
        self.assertTrue(model.index(3, 0).data(EXPANDED_ROLE))
        model.set_expanded_row(4)
        self.assertFalse(model.index(3, 0).data(EXPANDED_ROLE))
        self.assertIn((3, 3), events)
        self.assertIn((4, 4), events)

    def test_summary_text_breakdown(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        self.assertEqual(model.summary_text(), "3 files · 2 mapped · 1 unmapped")

    def test_movie_rows_carry_checks(self):
        from plex_renamer.engine.models import PreviewItem, ScanState
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE, EpisodeTableModel
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import _CheckBinding

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        preview = PreviewItem(original=Path("C:/lib/Movie/movie.mkv"), new_name="Movie (2021).mkv",
                              target_dir=None, season=None, episodes=[], status="OK", media_type="movie")
        state.preview_items = [preview]
        state.check_vars["0"] = _CheckBinding(True)
        model = EpisodeTableModel(media_type="movie")
        model.show_state(state, collapsed_sections=set())
        rows = [r for r in range(model.rowCount()) if model.row_kind_at(r) == "movie-file"]
        self.assertEqual(len(rows), 1)
        data = model.index(rows[0], 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.title, "movie.mkv")
        self.assertTrue(data.checked)
        self.assertEqual(data.status_text, "OK")
```

- [ ] **Step 2: Run to verify FAIL** — `.venv\Scripts\python.exe -m pytest tests\test_episode_table_model.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `_episode_table_model.py`** per the interface contract. Key mechanics: `show_state` = `beginResetModel` → build `list[_Entry]` (each entry stores kind, section_key, display text, preview_index, guide_row ref, `EpisodeRowData` snapshot) → `endResetModel`; keep `state`/`guide`/`collapsed_sections` references. Header DisplayRole text = `f"{'▸' if collapsed else '▾'} {TITLE}"` (keep today's prefix glyphs for test-helper parity). `guide_provider` defaults to a lazily-created `EpisodeMappingService().build_episode_guide`. `toggle_section` mutates the caller-owned collapsed set, then rebuilds via `show_state` with the same state/folder_preview (cache them). `set_expanded_row` clamps to valid rows and re-anchors to `None` on `show_state` (reset closes expansion). `_percent_from_label` moves here (delete from `_workspace_widgets.py` in Task 5). No `processEvents` anywhere.

- [ ] **Step 4: Run to verify PASS** — 9 passed.

- [ ] **Step 5: Suites + commit**

Run `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` (add the new test file to the runner lists in `scripts/`).

```bash
git add plex_renamer/gui_qt/widgets/_episode_table_model.py tests/test_episode_table_model.py scripts
git commit -m "feat(gui): EpisodeTableModel - sectioned episode/ghost/unmapped rows, filters, search, expansion bookkeeping"
```

---

### Task 2: `EpisodeTableDelegate` + `EpisodeTableView`

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_episode_table_delegate.py`
- Test: `tests/test_episode_table_delegate.py`

**Interfaces:**
- Consumes: Task 1 roles + `EpisodeRowData`, `paint_check_indicator`/`paint_mini_progress` (primitives), theme + `_scale`.
- Produces:

```python
class EpisodeTableDelegate(QStyledItemDelegate):
    expansion_requested = Signal(QModelIndex)     # chevron click or Enter (view forwards)
    def __init__(self, view: QListView, *, media_type: str, parent=None): ...
    def chevron_rect(self, option_rect: QRect) -> QRect
    def toggle_rect(self, option_rect: QRect) -> QRect          # movie-file rows
    def flash_row(self, row: int) -> None                       # 700ms background pulse, single QTimer
    # Expansion editor mechanics live HERE but are wired in Task 5:
    expansion_card_provider: "Callable[[QModelIndex], QWidget] | None" = None
    # createEditor(): returns expansion_card_provider(index) when set AND
    # index.data(EXPANDED_ROLE) is True, else None. updateEditorGeometry():
    # full row width. sizeHint(): when EXPANDED_ROLE, return the open
    # editor's sizeHint().height() (fall back to px(220) before the editor
    # exists); emit sizeHintChanged when the expanded row changes.

_ROW_HEADER_U, _ROW_SINGLE_U, _ROW_DOUBLE_U, _ROW_MOVIE_U = 30, 34, 52, 52
_CHEVRON_U, _TOGGLE_U, _PILL_H_U, _BAR_W_U, _MARGIN_U = 16, 20, 18, 70, 8
_TONE_COLOR = {"success": "success", "warning": "warning", "error": "error", "muted": "text_dim"}

class EpisodeTableView(QListView):
    chevron_clicked = Signal(QModelIndex)
    toggle_clicked = Signal(QModelIndex)          # movie-file rows
    header_clicked = Signal(str)                  # section_key of a collapsible header
    expand_key_pressed = Signal(QModelIndex)      # Enter/Return on current row
```

Geometry/painting contract (all `_scale.px`): row heights — `section-header`/`section-label` `px(30)`, `episode`/`unmapped`/`duplicate`/`orphan`/`folder` single-line `px(34)`, two-line (when `row_data.filename` non-empty) `px(52)`, `movie-file` `px(52)`, expanded row height is the editor's (Task 5). Episode row layout: chevron `px(16)` square at left (episode + movie-file rows only), then title (ElideRight), right-aligned status pill (same pill painter approach as the roster delegate: tone wash 0.12 bg, tone fg, `radius("pill")`), optional second line: filename in `text_dim` ElideMiddle + `→ target` in `text_dim`; companion count suffix `+N companions` caption when `companion_count > 0`; confidence: `paint_mini_progress` bar `px(70)` wide right of the title block when `confidence_pct is not None` and row status is `Review` (keep visual noise down — mapped rows don't need a bar; the pill carries state). Ghost rows (`status_text == "Missing File"`): no chevron, title painted `text_muted`, dashed 1px `border_light` rounded outline instead of fill, pill muted. Section headers: `section_header_bg` fill, `accent` bold text (keep the model's `▸/▾` prefix in the text itself). `movie-file` rows: toggle indicator (paint_check_indicator) at left when `checkable`, then chevron, title, pill, second line `→ target`. Flash: `flash_row` stores the row + starts a 700ms single-shot timer; while active, `paint` overlays `rgba(accent, 0.18)`; timer clears + `viewport().update()`. Backgrounds/hover/selection identical precedence to the roster delegate (card base is `surface` here — the table sits on the panel, rows are flush, no rounded card per row except ghosts' dashed outline; hover `card_hover`, selected `selection_bg` + 1px `accent` border). View: `mousePressEvent` routes chevron-rect presses on episode/movie-file rows → `chevron_clicked` (swallow press+release, selection must not move), toggle-rect presses on checkable movie rows → `toggle_clicked` (swallow), header rows → `header_clicked(section_key)` on release via `clicked`; `keyPressEvent` Enter/Return on a current episode/movie-file row → `expand_key_pressed`. Mouse tracking on; SingleSelection; per-pixel scroll; non-uniform sizes; headers/labels/ghosts/folder rows are NOT selectable (model flags already say so for headers/labels — the delegate does not override flags; ghost rows ARE selectable per spec's "row click selects" but not expandable... DECISION: ghost rows selectable and expandable — their expansion card shows the missing episode's overview/air date + the `Assign file...` action, which today exists on Missing File rows).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_episode_table_delegate.py
"""EpisodeTableDelegate/View painting smoke, size hints, hit-testing."""
from __future__ import annotations

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class EpisodeTableDelegateTests(QtSmokeBase):
    def _view(self, state, guide):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(700, 500)
        return view, model, delegate

    def test_size_hints_by_kind(self):
        from plex_renamer.gui_qt import _scale

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        self.assertEqual(view.sizeHintForRow(0), _scale.px(30))     # section label
        self.assertEqual(view.sizeHintForRow(2), _scale.px(30))     # season header
        self.assertEqual(view.sizeHintForRow(3), _scale.px(52))     # episode w/ filename line
        self.assertEqual(view.sizeHintForRow(5), _scale.px(34))     # ghost (no filename)

    def test_render_grab(self):
        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        self.assertFalse(view.grab().toImage().isNull())
        view.close()

    def test_chevron_click_emits_without_selection(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        hits: list[int] = []
        view.chevron_clicked.connect(lambda index: hits.append(index.row()))
        rect = view.visualRect(model.index(3, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, delegate.chevron_rect(rect).center())
        self.assertEqual(hits, [3])
        self.assertNotEqual(view.currentIndex().row(), 3)
        view.close()

    def test_header_click_emits_section_key(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        keys: list[str] = []
        view.header_clicked.connect(keys.append)
        rect = view.visualRect(model.index(2, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(keys, ["episode-guide-season:1"])
        view.close()

    def test_enter_emits_expand_on_current_row(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        expanded: list[int] = []
        view.expand_key_pressed.connect(lambda index: expanded.append(index.row()))
        view.setCurrentIndex(model.index(3, 0))
        QTest.keyClick(view, Qt.Key.Key_Return)
        self.assertEqual(expanded, [3])
        view.close()
```

- [ ] **Step 2: Run to verify FAIL** (ModuleNotFoundError), **Step 3: implement** per the contract, **Step 4: run to verify PASS** (5 passed).

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets/_episode_table_delegate.py tests/test_episode_table_delegate.py scripts
git commit -m "feat(gui): episode table delegate + view - painted rows, ghosts, chevron/toggle hit-testing, flash"
```

---

### Task 3: `EpisodeExpansionCard` (persistent-editor detail card)

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_episode_expansion.py`
- Test: `tests/test_episode_expansion.py`

**Interfaces:**
- Consumes: `EpisodeGuideRow`, `PreviewItem`, theme/_scale, `QApplication.clipboard()`.
- Produces:

```python
def episode_row_actions(row) -> list[tuple[str, str]]:
    # MOVED VERBATIM from MediaWorkspacePreviewPanel._episode_row_actions
    # (Missing File -> assign_file; Conflict -> keep_this/reassign/assign_to_more/unassign;
    #  Review -> approve + reassign/assign_to_more/unassign; else reassign/assign_to_more/unassign)

class EpisodeExpansionCard(QFrame):
    action_requested = Signal(str)      # action id
    collapse_requested = Signal()       # chevron/collapse button in the card
    def show_episode(self, state: ScanState, row: "EpisodeGuideRow") -> None
    def show_movie(self, state: ScanState, preview: PreviewItem) -> None
```

Card content (spec §3.2.4, top to bottom): **Files section** — for each source file (primary + companions): full path (`QLabel` word-wrapped with `setTextInteractionFlags(TextSelectableByMouse)`, NEVER elided) + a type badge for companions (painted pill text `SUB`/`NFO`/`ART` from `CompanionFile.file_type[:3].upper()`) + one copy button per path (`QToolButton` "⧉", tooltip "Copy path", `QApplication.clipboard().setText(str(path))`); when the assignment table holds more than one non-conflict claim on this row's slot, prefix the primaries with `Part 1 · Part 2` chips (paint via `status_chip.paint_chip_row` specs tone `muted`) — the §13 multi-part seam. **Target line** — `→ {row.target_rename}` full, wrapped, copy button. **Overview + air date** — `row.overview` (word-wrapped, `text_dim`) and `Air date: {row.air_date}` caption when non-empty; movie mode shows nothing here (movie overview lives in the header). **Actions row** — one `QPushButton` per `episode_row_actions(row)` entry (id → `action_requested.emit(id)`; "approve" styled `cssClass=primary`, others `secondary`), plus a permanently disabled `Merge…` button (`setEnabled(False)`, tooltip "Merge support arrives with mkvmerge integration") — the §13 UI seam; movie mode shows no actions row (single-file fixes don't apply). A slim collapse affordance (`QToolButton` "▴", `collapse_requested`) sits top-right.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_episode_expansion.py
"""Expansion card content, actions, copy behavior."""
from __future__ import annotations

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class EpisodeExpansionCardTests(QtSmokeBase):
    def test_episode_content_and_actions(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard, episode_row_actions,
        )

        state, guide = _guide_state()
        review_row = guide.rows[1]
        card = EpisodeExpansionCard()
        card.show_episode(state, review_row)
        texts = [label.text() for label in card.findChildren(type(card._target_label))]
        self.assertTrue(any("s01e02.mkv" in text for text in texts))
        self.assertTrue(any("Show - S01E02 - Two.mkv" in text for text in texts))
        action_ids = [action_id for action_id, _label in episode_row_actions(review_row)]
        self.assertEqual(action_ids, ["approve", "reassign", "assign_to_more", "unassign"])
        from PySide6.QtWidgets import QPushButton

        merge_buttons = [b for b in card.findChildren(QPushButton) if b.text() == "Merge…"]
        self.assertEqual(len(merge_buttons), 1)
        self.assertFalse(merge_buttons[0].isEnabled())

    def test_action_button_emits_id(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[1])
        fired: list[str] = []
        card.action_requested.connect(fired.append)
        approve = next(b for b in card._action_buttons if b.property("actionId") == "approve")
        approve.click()
        self.assertEqual(fired, ["approve"])

    def test_copy_button_sets_clipboard(self):
        from PySide6.QtWidgets import QApplication
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        card._copy_buttons[0].click()
        self.assertIn("s01e01.mkv", QApplication.clipboard().text())

    def test_missing_file_row_offers_assign(self):
        from plex_renamer.gui_qt.widgets._episode_expansion import episode_row_actions

        _state, guide = _guide_state()
        ghost = guide.rows[2]
        self.assertEqual(episode_row_actions(ghost), [("assign_file", "Assign file...")])
```

Implementation detail for testability: keep `self._action_buttons: list[QPushButton]` (each with `setProperty("actionId", action_id)`), `self._copy_buttons: list[QToolButton]` (rebuilt per `show_*` call), `self._target_label` as a named attribute.

- [ ] **Step 2: FAIL** (ModuleNotFoundError) → **Step 3: implement** → **Step 4: PASS** (4 passed).

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets/_episode_expansion.py tests/test_episode_expansion.py scripts
git commit -m "feat(gui): episode expansion card - full paths with copy, overview/air date, actions, merge seam"
```

---

### Task 4: `MediaWorkPanel` (header / strip / toolbar / footer assembly)

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_work_panel.py`
- Modify: `plex_renamer/gui_qt/widgets/status_chip.py` (add `season_strip_specs`)
- Test: `tests/test_work_panel.py` (+ extend `tests/test_status_chip.py`)

**Interfaces:**
- Consumes: Tasks 1–3 (`EpisodeTableModel/View/Delegate`, card wired in Task 5), `status_chip`, `SegmentedControl`, `thread_pool.submit`, theme/_scale.
- Produces:

```python
# status_chip.py addition — strip chips are uncollapsed and complete chips carry counts:
def season_strip_specs(report: CompletenessReport | None) -> list[tuple[int, ChipSpec]]:
    # per season (sorted) + specials last as season 0:
    # complete -> ChipSpec(f"S{n} ✓{expected}", "success", tooltip f"Season {n}: {m}/{e}")
    # incomplete/missing -> same text/tone/tooltip rules as season_chip_specs, NO run collapse
    # specials -> ("SP {m}/{e}", tone) with season number 0

class MediaWorkPanel(QFrame):
    filter_changed = Signal(str)          # "all"|"problems"|"unmapped"
    search_changed = Signal(str)
    approve_all_clicked = Signal()
    unassign_all_clicked = Signal()
    season_chip_clicked = Signal(int)     # season number (0 = specials)
    master_check_changed = Signal(int)    # movie mode master
    overview_toggled = Signal(bool)

    # Consumed by the action-bar system via workspace aliases:
    @property fix_match_button -> QPushButton
    @property primary_action_button -> QPushButton
    @property queue_preflight_label -> QLabel
    @property master_check -> MasterCheckBox        # movie mode; hidden for tv
    @property check_summary -> QLabel
    @property table_view -> EpisodeTableView
    @property model -> EpisodeTableModel
    @property search_box -> QLineEdit
    @property segmented_filter -> SegmentedControl
    @property approve_all_button / unassign_all_button -> QPushButton
    @property summary_label -> QLabel                # footer breakdown

    def __init__(self, *, media_type, settings_service=None, tmdb_provider=None,
                 guide_provider=None, parent=None): ...
    def show_state(self, state, *, collapsed_sections: set[str], folder_preview) -> None
    def clear(self, message: str = "Select a roster item to begin.") -> None
    def refresh_header(self, state) -> None          # pills + strip only (no overview refetch when token unchanged)
    def update_footer(self) -> None                  # summary_label from model.summary_text()
    def update_toolbar(self, state) -> None          # approve-all/unassign-all visibility per rules below
    def scroll_to_season(self, season: int) -> None  # header row PositionAtTop + delegate.flash_row; fully-missing season -> first_problem_row_in_season
```

Header: row 1 — title `QLabel` (`cssClass="heading"`, `{display_name}`), source/confidence painted pill (`f"{(state.active_episode_source or 'tmdb').upper()} · {clamped_percent(state.confidence)}%"`, tone `info`), status pill (`state_status(state)` text upper, tone via `state_status_tone` with `accent→warning` mapping). Row 2 — overview label word-wrapped, clamped to 2 lines by `setMaximumHeight(2 * fontMetrics().lineSpacing() + px(4))`, with a `more`/`less` link-button toggling the max-height off/on (`overview_toggled`); overview text fetched async exactly like the old detail workflow but minimal: token = `f"{state.show_id}:{media_type}"`, LRU dict (max 64), worker `tmdb.get_movie_details/get_tv_details → details.get("overview", "")`, bridge `Signal(str, str)` (token, text), stale tokens dropped; no TMDB → `""` and the label hides. Row 3 — discovery caption (`f"Discovery: {state.discovery_reason}"`) only when `settings.show_discovery_info` and the reason is non-empty (§5's one-line survivor). Season strip: horizontal row of flat `QPushButton`s (one per `season_strip_specs` entry, text = chip text, `cssClass="season-strip-chip"`, tooltip = chip tooltip, property `tone` set for QSS) inside a horizontal scroll area, hidden entirely for movies or when there are no specs; click → `season_chip_clicked(season)`. (QSS additions for `season-strip-chip` tones go in `theme.qss.tmpl` using existing tokens: bg `rgba` washes 0.12 per tone, fg tone color, radius `${radius_sm}px` — colors only via tokens.) Toolbar: TV = `SegmentedControl(["All", "Problems", "Unmapped"])` (map label→mode lowercase), `QLineEdit` search (`setPlaceholderText("Filter filenames…")`, `setClearButtonEnabled(True)`, `textChanged` → `search_changed`), stretch, `Approve All` (primary, visible only when the current guide has any `Review` row), `Unassign All` (secondary, visible/enabled per the existing `_sync_unassign_all_button` rules — copy that logic). Movie = master check + check summary + stretch (filters/search hidden; approve/unassign hidden). Footer: breakdown `summary_label` (caption), `queue_preflight_label` (caption, hidden when empty), stretch, `Fix Match` (secondary) + primary button. `scroll_to_season`: resolve `model.section_header_row(model.season_section_key(season))`; if the season is fully missing (header exists but every member row is `Missing File`) scroll to `first_problem_row_in_season(season)` instead; `table_view.scrollTo(index, PositionAtTop)` + `delegate.flash_row(row)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_work_panel.py
"""Work panel assembly: header, strip, toolbar rules, footer, scroll-to-season."""
from __future__ import annotations

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class WorkPanelTests(QtSmokeBase):
    def _panel(self, state, guide):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="tv", guide_provider=lambda _s: guide)
        panel.resize(760, 640)
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        return panel

    def test_header_title_and_strip_chips(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertEqual(panel._title_label.text(), "Show (2020)")
        chip_texts = [b.text() for b in panel._strip_buttons]
        self.assertEqual(chip_texts, ["S1 2/3"])

    def test_toolbar_rules_review_present(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertTrue(panel.approve_all_button.isVisible() or not panel.isVisible())
        panel.show()
        self.assertTrue(panel.approve_all_button.isVisible())   # guide has a Review row
        panel.close()

    def test_filter_and_search_signals(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        modes: list[str] = []
        panel.filter_changed.connect(modes.append)
        panel.segmented_filter.setCurrentText("Problems")
        self.assertEqual(modes, ["problems"])
        searches: list[str] = []
        panel.search_changed.connect(searches.append)
        panel.search_box.setText("abc")
        self.assertEqual(searches, ["abc"])

    def test_footer_breakdown(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.update_footer()
        self.assertEqual(panel.summary_label.text(), "3 files · 2 mapped · 1 unmapped")

    def test_scroll_to_season_flashes_header(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel.scroll_to_season(1)
        header_row = panel.model.section_header_row("episode-guide-season:1")
        self.assertEqual(panel._delegate._flash_row_index, header_row)
        panel.close()

    def test_movie_mode_hides_tv_toolbar(self):
        from pathlib import Path
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        panel = MediaWorkPanel(media_type="movie")
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        self.assertFalse(panel.segmented_filter.isVisible())
        self.assertFalse(panel.search_box.isVisible())
        self.assertIsNotNone(panel.master_check)   # shown/hidden by update_master_state (Task 5 wiring)
        self.assertEqual(len(panel._strip_buttons), 0)
        panel.close()
```

Plus extend `tests/test_status_chip.py`:

```python
def test_season_strip_specs_uncollapsed_with_counts():
    seasons = [_season(n, 10, 10) for n in range(1, 8)]
    specs = season_strip_specs(_report(seasons, specials=_season(0, 3, 1, missing=(2, 3))))
    assert len(specs) == 8                       # 7 seasons + SP, no collapse
    assert specs[0] == (1, ChipSpec("S1 ✓10", "success", "Season 1: 10/10"))
    assert specs[-1][0] == 0
    assert specs[-1][1].text == "SP 1/3"
```

Implementation detail for testability: `self._title_label`, `self._strip_buttons: list[QPushButton]`, `self._delegate._flash_row_index` (int, -1 idle) are named attributes.

- [ ] **Step 2: FAIL** → **Step 3: implement** (`season_strip_specs` in status_chip.py + the panel; add the `season-strip-chip` QSS block to `theme.qss.tmpl` with token-only colors) → **Step 4: PASS** (6 + 1 passed).

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets/_work_panel.py plex_renamer/gui_qt/widgets/status_chip.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_work_panel.py tests/test_status_chip.py scripts
git commit -m "feat(gui): MediaWorkPanel - show header with async overview, season strip, toolbar, footer"
```

---

### Task 5: The 2-panel cutover

The suite is red mid-task and green before the single commit. Wire the work panel into the workspace, delete the preview + detail panels, rewire coordinators, migrate tests.

**Files:**
- Modify: `media_workspace.py`, `_media_workspace_ui.py`, `_media_workspace_state.py`, `_media_workspace_sync.py`, `_media_workspace_view.py`, `_media_workspace_refresh.py`, `_media_workspace_lifecycle.py:36` (detail cache line), `_media_workspace_action_bar.py` (only if an alias name changes — target: none)
- Delete: `_media_workspace_preview.py`, `media_detail_panel.py`, `_media_detail_artwork.py`, `_media_detail_payloads.py`, `_media_detail_state.py`, `_media_detail_workflow.py`, `_workspace_widgets.py`
- Modify tests: `tests/conftest_qt.py`, `tests/test_qt_media_workspace.py` (bulk), any file matching the Step 5 greps

**Interfaces:** consumes Tasks 1–4. Produces the 2-panel workspace; the workspace-level aliases (`_fix_match_btn`, `_queue_inline_btn`, `_queue_preflight_label`) now point at the work panel's buttons so `_media_workspace_action_bar.py` and `_media_workspace_action_state.py` run UNCHANGED.

- [ ] **Step 1: Wire the panel (ui coordinator + workspace)**

`_media_workspace_ui.py`: replace `_build_preview_panel` + `_build_detail_panel` with `_build_work_panel`:

```python
    def _build_work_panel(self) -> None:
        workspace = self._workspace
        workspace._work_panel = MediaWorkPanel(
            media_type=workspace._media_type,
            settings_service=workspace._settings,
            tmdb_provider=workspace._tmdb_provider,
            guide_provider=(
                workspace._media_ctrl.episode_guide_for_state
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "episode_guide_for_state")
                else None
            ),
        )
        panel = workspace._work_panel
        panel.setProperty("panelVariant", "square")
        workspace._fix_match_btn = panel.fix_match_button
        workspace._queue_inline_btn = panel.primary_action_button
        workspace._queue_preflight_label = panel.queue_preflight_label
        workspace._fix_match_btn.clicked.connect(workspace._fix_match)
        workspace._queue_inline_btn.clicked.connect(workspace._activate_selected_primary_action)
        workspace._queue_inline_btn.setText(workspace._queue_selected_label())
        workspace._sync_action_button_metrics()

        panel.filter_changed.connect(workspace._on_episode_filter_changed)
        panel.search_changed.connect(workspace._on_episode_search_changed)
        panel.approve_all_clicked.connect(workspace._approve_all_episode_mappings)
        panel.unassign_all_clicked.connect(workspace._unassign_all_episode_mappings)
        panel.season_chip_clicked.connect(panel.scroll_to_season)
        panel.master_check_changed.connect(workspace._on_preview_master_changed)
        panel.table_view.chevron_clicked.connect(workspace._on_table_expand_requested)
        panel.table_view.expand_key_pressed.connect(workspace._on_table_expand_requested)
        panel.table_view.toggle_clicked.connect(workspace._on_movie_row_toggled)
        panel.table_view.header_clicked.connect(workspace._on_table_section_toggled)
        panel.table_view.selectionModel().currentChanged.connect(workspace._on_table_current_changed)
```

Splitter: two widgets `[roster, work_panel]`, `setSizes([380, 860])`; `_restore_splitter_positions` only applies persisted positions when `len(positions) == 2` (old 3-value persists are ignored — first resize re-persists 2 values; do NOT migrate them numerically).

`media_workspace.py`: new thin handlers delegating to coordinators (exact bodies in Step 2): `_on_episode_filter_changed(mode)`, `_on_episode_search_changed(text)`, `_on_table_current_changed(current, previous)`, `_on_table_expand_requested(index)`, `_on_movie_row_toggled(index)`, `_on_table_section_toggled(section_key)`. Delete: `_populate_preview`/`_warm_preview_cache`/`_on_preview_item_clicked`/`_update_sticky_header`/`_on_preview_current_item_changed`/`_on_preview_item_changed`/`_attach_preview_widget`/`_attach_folder_preview_widget`/`_set_preview_summary`/`_render_detail` (see mapping) and the `_PreviewRowWidget` import. `_preview_group_state` dict STAYS (it now feeds `collapsed_sections` per state key).

- [ ] **Step 2: Rewire coordinators (touchpoint map)**

| Site | Old | New |
|---|---|---|
| state coord `populate_preview(state)` | preview panel populate + master state | `show_in_work_panel(state)`: `collapsed = workspace._preview_group_state.setdefault(_state_key(state), set())`; `workspace._work_panel.show_state(state, collapsed_sections=collapsed, folder_preview=workspace._folder_preview_data(state))`; `workspace._work_panel.update_toolbar(state)`; `workspace._work_panel.update_footer()`; movie: `update_master_state(state)` logic moves onto the panel (`panel.update_master_state(state)` — port the method body from the old preview panel verbatim, minus the TV branch which just hides) |
| state coord `warm_preview_cache` | dead cache warmer | DELETE (method + `media_workspace._warm_preview_cache` delegate) — spec assigned this to Plan 5 but its subject (the preview panel) is deleted here; note in the commit body |
| state coord `on_preview_item_clicked` | header toggle via item roles | `on_table_section_toggled(section_key)`: `workspace._work_panel.model.toggle_section(section_key)` (model mutates the shared collapsed set + rebuilds) then `workspace._work_panel.update_footer()` |
| state coord `update_preview_master_state` | preview panel master | panel-owned; keep a thin delegate for `refresh_from_controller` parity |
| sync coord `on_preview_current_item_changed` | item→preview index | `on_table_current_changed(current)`: `preview_index = model.preview_index_at(current.row())` when valid; same body otherwise (`state.selected_index = index`, `update_action_bar`) — `render_detail` call is DELETED (no detail panel; header/footer refresh happens in `update_action_bar` → see below) |
| sync coord `on_preview_item_changed` + `set_item_check_state(..., preview=True)` | item roles + widget sync | `on_movie_row_toggled(index)`: resolve `preview_index`; guard `_preview_syncing`; flip the binding (`binding.set(not binding.get())`); recompute `state.checked = any(actionable bindings)`; `panel.model.refresh_checks()`; `_sync_current_roster_row_checked(state.checked)`; `panel.update_master_state(state)`; `update_action_bar()` — the `preview` parameter and the whole item-based `set_item_check_state` DIE (Plan-2 review's "vestigial preview param" resolved) |
| sync coord `on_preview_master_changed` | walks list items | same binding loop, then `panel.model.refresh_checks()` instead of per-item widget sync |
| sync coord `sync_row_selection` | preview widgets set_selected | DELETE (both views are delegate-painted now); remove remaining callers (`state coord populate`, refresh coord) |
| view coord `render_detail` | detail panel set_selection | DELETE. `_media_workspace_action_bar.update_action_bar` line 30-31 (`workspace._render_detail(...)`) becomes `workspace._work_panel.refresh_header(selected_state)` guarded by `selected_state is not None`; `_update_queue_preflight` already writes the footer label |
| view coord `selected_preview` | preview list currentItem | `current = workspace._work_panel.table_view.currentIndex()`; `model.preview_index_at(...)` → `state.preview_items[i]` |
| refresh coord `refresh_from_controller` | populate_preview + render_detail + selected_preview | `show_in_work_panel(selected_state)` (via `workspace._populate_preview` alias — keep the workspace method NAME `_populate_preview` delegating to `show_in_work_panel` to minimize churn); drop the `_render_detail` call |
| refresh coord `_reset_empty_ready_state` | preview list/labels/detail clear | `workspace._work_panel.clear()`; keep roster/queue-button resets; `_fix_match_btn`/`_queue_inline_btn` lines unchanged (aliases now live on the panel) |
| lifecycle `show_scanning` (`:36`) | `_detail_panel.clear_metadata_cache()` | `workspace._work_panel.clear()` (the overview LRU lives in the panel; add `clear()` also resetting it) |
| lifecycle `apply_settings` | `_detail_panel.refresh_current()` | re-show current state via `workspace._populate_preview(workspace._selected_state())` when not None (re-snapshots filename-line visibility on view_mode change) |
| workspace `toggle_focused_check` (Space) | unchanged | unchanged (roster-scoped) |
| expansion | — | `on_table_expand_requested(index)` in state coord: if `model.expanded_row() == index.row()` → close (`set_expanded_row(None)`, `closePersistentEditor`); else close previous, `set_expanded_row(row)`, `openPersistentEditor(index)`. Delegate `createEditor` returns `EpisodeExpansionCard` populated from `guide_row_at(row)`/movie preview, `card.action_requested` → `workspace._action_coordinator.handle_episode_row_action(state, guide_row, action_id)` (movie rows: no actions), `card.collapse_requested` → close; `sizeHint` for the expanded row returns the card's `sizeHint().height()` (delegate consults `EXPANDED_ROLE`); second click on the already-current row also expands: in `on_table_current_changed`, if `previous == current` do nothing (Qt won't refire) — instead `table_view.state_clicked`-equivalent is unnecessary: bind `table_view.clicked` → if `index == currentIndex()` and kind in `{"episode","movie-file"}` and not already expanded → expand |

Delete the six files listed in **Files**. `_workspace_widgets.py` imports fallout: `_CheckBinding` is re-exported from there — change importers (`_media_workspace_refresh.py:13`) to `from ._workspace_widget_primitives import _CheckBinding`. Verify deletions: `grep -rn "_workspace_widgets\|PreviewRowWidget\|EpisodeGuideRowWidget\|FolderPreviewRowWidget\|MediaDetailPanel\|_media_detail\|MediaWorkspacePreviewPanel\|_preview_list\|_detail_panel\|sticky_header\|warm_preview_cache\|_PREVIEW_ENTRY_KIND_ROLE" plex_renamer` → zero hits.

- [ ] **Step 3: Rewrite conftest helpers**

Replace `_preview_widget_for_index`, `_preview_header_texts`, and add expansion access:

```python
    def _episode_row_data_for_preview_index(self, workspace, index: int):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        model = workspace._work_panel.model
        row = model.row_for_preview_index(index)
        if row < 0:
            return None
        return model.index(row, 0).data(ROW_DATA_ROLE)

    def _episode_section_titles(self, workspace) -> list[str]:
        model = workspace._work_panel.model
        titles: list[str] = []
        for row in range(model.rowCount()):
            if model.row_kind_at(row) in {"section-header", "section-label"}:
                text = (model.index(row, 0).data() or "").strip()
                for prefix in ("▸ ", "▾ "):
                    text = text.removeprefix(prefix)
                titles.append(text)
        return titles

    def _open_expansion_card(self, workspace, row: int):
        view = workspace._work_panel.table_view
        model = workspace._work_panel.model
        workspace._on_table_expand_requested(model.index(row, 0))
        return view.indexWidget(model.index(row, 0))
```

- [ ] **Step 4: Migrate `tests/test_qt_media_workspace.py` (pattern table)**

| Old pattern | New pattern |
|---|---|
| `workspace._preview_list.count()` / `.item(n)` iteration | `workspace._work_panel.model.rowCount()` / role queries |
| `_preview_widget_for_index(ws, i)` + `EpisodeGuideRowWidget`/`PreviewRowWidget` isinstance + widget attrs (`_title.text()`, `_status.text()`, `_target.text()`) | `_episode_row_data_for_preview_index(ws, i)` + `data.title/status_text/target` |
| `_preview_header_texts(ws)` season/section titles | `_episode_section_titles(ws)` (same strings minus the arrow prefix — ratio/missing suffixes now include `missing E..` text; loosen equality to `startswith`/`in` where the assertion targeted the ratio) |
| guide-row ⋯ menu / approve-button interaction (`widget.actions_menu()`, `widget.approve_button().click()`) | open the expansion card (`self._open_expansion_card(ws, row)`) and click `card._action_buttons` by `actionId` property |
| filter button asserts (`_episode_filter_buttons["problems"].click()`) | `ws._work_panel.segmented_filter.setCurrentText("Problems")` |
| Approve All / Unassign All visibility (`_approve_all_button`, `unassign_all_button`) | `ws._work_panel.approve_all_button` / `.unassign_all_button` (same visibility rules) |
| detail panel asserts (`_detail_panel._title.text()`, facts rows, overview, poster) | header asserts: `ws._work_panel._title_label.text()`; facts-grid and detail-poster assertions are DELETED (spec §5 removed the surface); episode overview/air-date assertions move to the expansion card labels |
| `_queue_preflight_label` asserts | unchanged (alias points at the footer label) |
| sticky header tests (`_sticky_header`) | DELETE tests (feature removed by design — season strip + in-place ghosts replace it; list each deletion in the report) |
| folder plan label / folder preview widget | folder section rows: `model.row_kind_at(r) == "folder"` + `ROW_DATA_ROLE` title/target |
| master check (movie) via preview panel | `ws._work_panel.master_check` / `check_summary` (same MasterCheckBox semantics) |
| `_set_item_check_state(item, checked, preview=True)` movie toggles | `ws._on_movie_row_toggled(model.index(row, 0))` or direct binding flips + `refresh_checks()` |

Also run: `grep -rn "_preview_list\|_detail_panel\|_preview_panel\|EpisodeGuideRowWidget\|PreviewRowWidget\|MediaDetailPanel\|sticky" tests\` and migrate every hit (includes `conftest_qt.py` leftovers and any queue/history test references).

- [ ] **Step 5: Converge and commit**

Run `tests\test_qt_media_workspace.py` class-by-class while migrating; then the four new test files; then full `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → all green, zero new skips.

```bash
git add -A plex_renamer/gui_qt tests scripts
git commit -m "feat(gui): 2-panel cutover - work panel replaces preview+detail, persistent-editor expansion, panels deleted"
```

---

### Task 6: §5 removal sweep + opportunistic cleanups

**Files:**
- Modify: `tests/test_gui_theme.py` (extend), `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py` (identifier rename)
- Test: `tests/test_gui_theme.py`

- [ ] **Step 1: Write the failing guard test (extend `tests/test_gui_theme.py`)**

```python
_DELETED_GUI_MODULES = (
    "_media_workspace_preview", "media_detail_panel", "_media_detail_artwork",
    "_media_detail_payloads", "_media_detail_state", "_media_detail_workflow",
    "_workspace_widgets",
)


def test_deleted_panel_modules_stay_deleted():
    present = [name for name in _DELETED_GUI_MODULES
               if (_GUI_ROOT / "widgets" / f"{name}.py").exists()]
    assert present == [], f"GUI V4 deleted these modules; they came back: {present}"
```

(Fails only if run before Task 5 — on this plan's ordering it passes immediately; keep it as permanent armor.)

- [ ] **Step 2: Rename `_clear_plex_ready_checks`**

In `_media_workspace_queue_actions.py` rename the function to `_clear_fully_ready_checks` and update its callers in the same file (`grep -n "_clear_plex_ready_checks" plex_renamer tests` → then zero hits). Final repo sweep: `grep -rni "plex" plex_renamer --include=*.py` → only `plex_renamer` package identifiers and `PLEX_READY_EPISODE_FLOOR` (engine).

- [ ] **Step 3: Suites + commit**

```bash
git add plex_renamer tests
git commit -m "chore(gui): deleted-module guard + rename _clear_fully_ready_checks"
```

---

### Task 7: Verification + bookkeeping

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass; skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: Visual sanity** — offscreen grab (throwaway test in `tests/`, mirroring the Plan 2 pattern): build a `MediaWorkPanel` with the synthetic `_guide_state()` (plus a second season and an orphan companion for richness), themed stylesheet applied, grab to PNG at 1000×700, inspect: header title + two pills + clamped overview, season strip chips, segmented filter + search, season header with ratio + missing text, single-line mapped row with pill, two-line review row, dashed ghost row, footer breakdown + two buttons. Open an expansion card (`_on_table_expand_requested`-equivalent direct call) and grab again: full paths + copy buttons + actions + disabled Merge…. Delete the throwaway test after inspection.

- [ ] **Step 3: Update roadmap + handoff, commit**

Roadmap row 3 → Landed (with commit range); handoff status/current + "next step: write Plan 4 (bulk assign, spec §6)" + note for Plan 5 that `warm_preview_cache` died with the preview panel (Plan 5 scope shrinks to async guide + BusyOverlay + perf test); session log entry.

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 3 landed; next up plan 4 (bulk assign)"
```

---

## Self-review notes (kept for the record)

- **Spec coverage:** §3.2 zones 1–5 all present (header Task 4, strip Task 4 + scroll/flash Task 2/4, toolbar Task 4 incl. Approve All/Unassign All relocation, table Tasks 1–2 with ghost rows in place + sections after seasons + Problems filter inclusion, footer Task 4 + preflight line reuse); §3.2 expansion contract Task 3 (full filenames never elided + copy, overview/air date from guide rows, companions with badges, action set + conflict Keep-this + disabled Merge… + Part chips = §13 seams); §3.3 movie parity (model movie-file rows Task 1, master-check toolbar Task 4, same footer/buttons Task 5, `MediaDetailPanel` deleted both modes); §4 strip chips (`season_strip_specs`, counts always visible, click-to-scroll, fully-missing → jump to missing block); §5 removals (facts grid/backdrop/meta-summary die with the detail panel; discovery info survives as one caption; prose preview summary → footer breakdown; Task 6 guard keeps modules dead); §7 episode-table portion (models over dataclasses, delegate painting, persistent editor = exactly one live widget, no `processEvents` in the new path, `dataChanged` granularity for expansion/checks). Async guide/BusyOverlay/perf-budget test remain Plan 5 by design.
- **Deliberate scope choices:** sticky season header dropped (strip + in-place ghosts supersede; migration table deletes its tests, documented); "filenames inline" view option bound to existing `view_mode != "compact"` instead of a new setting (YAGNI); confidence bar painted only on Review rows (pill carries state elsewhere); ghost rows selectable + expandable (assign_file action lives there); `warm_preview_cache` deletion pulled forward from Plan 5 because its host file dies here; Unassign All keeps plain styling until Plan 4.
- **Type consistency check:** role constants/`EpisodeRowData` fields consistent across Tasks 1/2/5 and conftest helpers; `episode_row_actions` ids match the frozen action-id list and `handle_episode_row_action`; `MediaWorkPanel` property names in Task 4 match every Task 5 alias/connection; `season_strip_specs` return shape `(season, ChipSpec)` matches strip-builder usage and its test; `_guide_state()` fixture is shared via import by Tasks 2–4 tests (kept in `test_episode_table_model.py`).
