# GUI V4 Plan 7 — Queue/History Restyle + Companion Surfacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the queue/history tabs per spec §11 — painted status pills + accent selection title + taller rows in the job table, a merged `3 files (2 comp.)` Files column, companion renames nested under their video with type badges in the job detail tree (the §13 merge-grouping seam), a warning-banner revert confirmation, danger-outline destructive buttons, and illustrated empty states.

**Architecture:** All changes are view-layer. `JobTableModel` reshapes its columns (read-model only); `_HoverRowDelegate` in `_job_list_tab.py` grows pill/accent painting (same painted-pill idiom as `_episode_table_delegate._paint_pill`); companion↔video pairing is a pure read-model helper in `_job_detail_preview.py` (RenameOp has no persisted linkage and §16 forbids job-store schema changes — pairing is heuristic: same target dir + target-stem prefix). No new files except one new fast-test module.

**Tech Stack:** PySide6 (QPainter delegate, QSS via `theme.qss.tmpl` tokens), `_scale.px` sizing, existing model/proxy/detail-splitter architecture (spec: "architecture is already right; this is a facelift").

## Global Constraints

- No engine/controller/service/job-store behavior changes (spec §16). Companion pairing is a **view-side read-model helper**; no new persisted fields on `RenameOp`/`RenameJob` ("no schema change ships in V4", §13).
- All colors through `gui_qt/theme.py` tokens — the Plan 1 no-hex guard runs repo-wide; no new hex anywhere outside theme.py. QSS washes that need alpha use hand-derived `rgba(...)` per the tmpl header comment (success=63,185,80 · warning=210,153,34 · error=229,83,75 · info=88,166,255 · accent=0,164,220 · text_dim=155,155,155) — copy those RGB triples exactly.
- All sizing through `gui_qt/_scale.py` `px()`/`icon()`.
- No `"Plex"` user-facing strings (AST guard); no `processEvents` in `gui_qt`; no inline `setStyleSheet` added (Task 4 removes one).
- Public seams unchanged: `JobTableModel.set_jobs/jobs/checked_jobs/checked_job_ids/set_checked_job_ids/set_jobs_checked/clear_checked/job_at/is_checkable_job` + `SORT_ROLE`; `QueueTab.queue_changed`/`execute_focused`/`remove_focused_checked`; `HistoryTab.history_changed`; `_JobListTab.select_job`. The status-pill painting must match the workspace pill idiom (`_episode_table_delegate._paint_pill`: tone-token `qcolor`, `setAlphaF(0.12)` wash, `theme.radius("pill")`, no border, tone-colored UPPERCASE text).
- Suites must pass at the end of every task: `scripts\test-fast.cmd` + `scripts\test-smoke.cmd`, zero skips. Run Python via `.venv\Scripts\python.exe`. New smoke files would need both runner-classification lists under `scripts/` updated — this plan adds **no** new smoke file (the new test module is pure-Python fast; Qt tests extend existing smoke files).

**Recorded deviations (decided at plan time — do not silently "fix"):**
1. Spec §11's "drop the 4px selected-row stripe; selection = selection_bg full-row; alternating rows off in favor of hover" **already landed in Plan 1** — `_HoverRowDelegate` paints full-row `selection_bg`/`card_hover` today and nothing enables alternation. This plan's remaining §11-bullet-1 scope is: painted status pill, accent title on the highlighted row, row height up. (Task 2 pins alternation-off with a test instead of re-implementing it.)
2. "Segmented filters restyled per theme" — `SegmentedControl` + its QSS landed in Plan 1 and is already the themed control. No-op here.
3. "Start/Run buttons follow the primary/secondary scheme" — default `QPushButton` **is** the primary (accent) style in this theme and `Run Selected` already carries `cssClass="secondary"`. The only real button change is `Remove Selected` (and History's `Revert Selected`) → `danger-outline`.
4. Companion↔video pairing is heuristic (same `target_dir_relative` + companion `new_name` starts with the video's target stem + `"."`; longest stem wins). Companions that match no video stay in a residual "Companion Files (N)" group — never silently dropped.
5. The detail panel's facts card keeps its separate Files / Companions cells — §11's merged `3 files (2 comp.)` format applies to the **table column**; the facts card has room for both and stays.

---

### Task 1: JobTableModel — merged Files column + token-derived transition tints

**Files:**
- Modify: `plex_renamer/gui_qt/models/job_table_model.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_list_tab.py:203-211` (header section modes for the new column count)
- Test: `tests/test_qt_queue_history.py` (adapt `test_job_table_file_and_companion_columns_do_not_double_count`)

**Interfaces:**
- Consumes: `RenameJob.selected_video_count` / `selected_companion_count` (existing properties), `theme.qcolor`.
- Produces: 7-column model `["", "Status", "Name", "Type", "Action", "Files", "When"]`; module function `files_cell_text(job) -> str` (used by the adapted test); `SORT_ROLE` for the Files column = `int(selected_video_count)`; When moves to column 6. Task 2 relies on the column layout (Status=1, Name=2).

- [ ] **Step 1: Adapt the failing test** — in `tests/test_qt_queue_history.py`, replace the body of `test_job_table_file_and_companion_columns_do_not_double_count` (line ~22; keep the 4-op job fixture — 2 video + 2 subtitle ops, one pair selected, one pair not) and rename it:

```python
    def test_job_table_files_column_merges_selected_counts(self):
        from plex_renamer.gui_qt.models.job_table_model import (
            SORT_ROLE,
            JobTableModel,
            files_cell_text,
        )
        from plex_renamer.job_store import RenameJob, RenameOp

        # ... keep the existing `job = RenameJob(...)` fixture verbatim ...

        model = JobTableModel(history=False)
        model.set_jobs([job])

        self.assertEqual(model.columnCount(), 7)
        self.assertEqual(
            model.headerData(5, Qt.Orientation.Horizontal), "Files"
        )
        self.assertEqual(model.headerData(6, Qt.Orientation.Horizontal), "When")
        # Only the selected pair counts: 1 video + 1 companion.
        self.assertEqual(
            model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole),
            "1 file (1 comp.)",
        )
        self.assertEqual(model.data(model.index(0, 5), SORT_ROLE), 1)
        self.assertEqual(files_cell_text(job), "1 file (1 comp.)")
        # When column renders a formatted date, not a count.
        self.assertNotEqual(
            model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole), "1"
        )
```

Also add, in the same class:

```python
    def test_job_table_files_column_omits_companion_suffix_when_none(self):
        from plex_renamer.gui_qt.models.job_table_model import files_cell_text
        from plex_renamer.job_store import RenameJob, RenameOp

        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            rename_ops=[
                RenameOp(
                    original_relative="Show/a.mkv", new_name="A.mkv",
                    target_dir_relative="Show", status="OK",
                    selected=True, file_type="video",
                ),
                RenameOp(
                    original_relative="Show/b.mkv", new_name="B.mkv",
                    target_dir_relative="Show", status="OK",
                    selected=True, file_type="video",
                ),
                RenameOp(
                    original_relative="Show/c.mkv", new_name="C.mkv",
                    target_dir_relative="Show", status="OK",
                    selected=True, file_type="video",
                ),
            ],
        )
        self.assertEqual(files_cell_text(job), "3 files")
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py -q`
Expected: FAIL — `ImportError: cannot import name 'files_cell_text'` (and the old 8-column shape).

- [ ] **Step 3: Implement the model reshape** in `job_table_model.py`:
  - Replace the `_HEADERS` line:

```python
_HEADERS = ["", "Status", "Name", "Type", "Action", "Files", "When"]
```

  - Add directly under `_fmt_dt`:

```python
def files_cell_text(job: RenameJob) -> str:
    """Spec §11 Files column: '3 files (2 comp.)'; companion suffix drops at 0."""
    videos = job.selected_video_count
    noun = "file" if videos == 1 else "files"
    text = f"{videos} {noun}"
    companions = job.selected_companion_count
    if companions:
        text += f" ({companions} comp.)"
    return text
```

  - Replace the `_TRANSITION_COLORS` class attribute (the three raw `QColor(r, g, b, a)` literals) with token-derived values — add a module helper above the class and rewrite the attribute:

```python
def _transition_tint(token: str, alpha: int) -> QColor:
    color = _theme_qcolor(token)
    color.setAlpha(alpha)
    return color
```

```python
    _TRANSITION_COLORS = {
        JobStatus.COMPLETED: _transition_tint("success", 50),
        JobStatus.FAILED: _transition_tint("error", 50),
        JobStatus.REVERTED: _transition_tint("info", 40),
    }
```

  - In `data()`, replace the `DisplayRole` branches for `value_column` 4/5/6 with:

```python
            if value_column == 4:
                return files_cell_text(job)
            if value_column == 5:
                return _fmt_dt(job.updated_at if self._history else job.created_at)
```

  - Replace the `SORT_ROLE` branches for `value_column` 4/5/6 with:

```python
            if value_column == 4:
                return int(job.selected_video_count or 0)
            if value_column == 5:
                return job.updated_at if self._history else job.created_at
```

  - In the `TextAlignmentRole` branch, replace the column tuple `(0, 1, 3, 4, 5, 6, 7)` with `(0, 1, 3, 4, 5, 6)`.
  - Leave the `ForegroundRole` column-1 branch alone in this task (Task 2 removes it when the delegate takes over pill painting).

- [ ] **Step 4: Adjust the header section modes** in `_job_list_tab.py` — replace the block at lines ~205-211:

```python
        self._header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._header.resizeSection(6, 92)
        for column in (1, 3, 4, 5):
            self._header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
```

(The section-0 fixed/36 lines above it stay.)

- [ ] **Step 5: Sweep for stale column users** — run `grep -rn "index(0, 7)\|index(row, 7)\|Companions" plex_renamer/gui_qt tests` and fix any hit that reads the old 8-column table shape. Expected legitimate survivors: the detail panel facts card ("Companions" cell — deviation 5) and `_job_detail_preview.py`'s "Companion Files" group label. Anything indexing model column 6/7 as counts must be adapted.

- [ ] **Step 6: Run the covering files**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py tests\test_qt_job_detail_panel.py -q`
Expected: PASS.

- [ ] **Step 7: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` green, zero skips.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/gui_qt/models/job_table_model.py plex_renamer/gui_qt/widgets/_job_list_tab.py tests/test_qt_queue_history.py
git commit -m "feat(gui): queue/history Files column merges companion counts; transition tints via tokens"
```

---

### Task 2: Painted status pills, accent selection title, taller rows, danger-outline buttons

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_job_list_tab.py` (`_HoverRowDelegate` + row height)
- Modify: `plex_renamer/gui_qt/models/job_table_model.py` (drop the now-dead `ForegroundRole` branch + `_STATUS_COLOR` dict)
- Modify: `plex_renamer/gui_qt/widgets/_queue_tab_state.py:52-53` (`remove_button_css_class`)
- Modify: `plex_renamer/gui_qt/widgets/queue_tab.py:68-69` (Remove button construction class)
- Modify: `plex_renamer/gui_qt/widgets/history_tab.py:57` (Revert Selected → danger-outline)
- Test: `tests/test_qt_queue_history.py` (extend)

**Interfaces:**
- Consumes: Task 1's column layout (Status=1, Name=2), `Qt.ItemDataRole.UserRole` → `RenameJob` (existing model role), `theme.qcolor/radius`, `_scale.px`.
- Produces: `_job_list_tab.py` module dict `_JOB_STATUS_TONE: dict[str, str]` (status → tone token; tests import it), delegate method `_paint_status_pill`, table default row height `_scale.px(36)`. `remove_button_css_class(enabled=...)` returns `"danger-outline"` for both states (QSS already has the `:disabled` variant).

- [ ] **Step 1: Write the failing tests** — append to `QtQueueHistoryTests` in `tests/test_qt_queue_history.py`:

```python
    def test_job_status_tone_map_covers_every_status(self):
        from plex_renamer.gui_qt.widgets._job_list_tab import _JOB_STATUS_TONE

        for status in (
            JobStatus.PENDING, JobStatus.RUNNING, JobStatus.COMPLETED,
            JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.REVERTED,
            JobStatus.REVERT_FAILED,
        ):
            self.assertIn(status, _JOB_STATUS_TONE)

    def test_queue_table_row_height_and_no_alternation(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            tab = QueueTab(controller)
            self.assertEqual(
                tab._table.verticalHeader().defaultSectionSize(), _scale.px(36)
            )
            self.assertFalse(tab._table.alternatingRowColors())
            tab.close()
            controller.close()

    def test_status_pill_paints_without_error(self):
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            store.add_job(RenameJob(
                library_root="C:/library", source_folder="Show",
                media_name="Example Show",
            ))
            controller = QueueController(store)
            tab = QueueTab(controller)
            index = tab._proxy.index(0, 1)
            self.assertTrue(index.isValid())
            pixmap = QPixmap(200, 40)
            painter = QPainter(pixmap)
            option = QStyleOptionViewItem()
            option.rect = pixmap.rect()
            try:
                tab._hover_delegate._paint_status_pill(painter, option, index)
            finally:
                painter.end()
            tab.close()
            controller.close()

    def test_remove_and_revert_buttons_use_danger_outline(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets._queue_tab_state import remove_button_css_class
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab

        self.assertEqual(remove_button_css_class(enabled=True), "danger-outline")
        self.assertEqual(remove_button_css_class(enabled=False), "danger-outline")
        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            self.assertEqual(queue_tab._remove_btn.property("cssClass"), "danger-outline")
            self.assertEqual(history_tab._revert_btn.property("cssClass"), "danger-outline")
            queue_tab.close()
            history_tab.close()
            controller.close()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py -q`
Expected: FAIL — `_JOB_STATUS_TONE` / `_paint_status_pill` don't exist; row height is the Qt default; css classes are `"secondary"`/none.

- [ ] **Step 3: Implement the delegate restyle** in `_job_list_tab.py`:
  - Add imports: `_scale` joins the `from .. import theme` line (`from .. import _scale, theme`); add `QPalette` to the `PySide6.QtGui` import list; add `JobStatus` (`from ...constants import JobStatus`).
  - Add module constants under `_SELECTED_ROW_COLOR`:

```python
_STATUS_COLUMN = 1
_NAME_COLUMN = 2
# Painted-pill tones (workspace idiom: 12% wash + tone text, radius "pill").
_JOB_STATUS_TONE = {
    JobStatus.PENDING: "text_dim",
    JobStatus.RUNNING: "accent",
    JobStatus.COMPLETED: "success",
    JobStatus.FAILED: "error",
    JobStatus.CANCELLED: "text_dim",
    JobStatus.REVERTED: "info",
    JobStatus.REVERT_FAILED: "error",
}
```

  - In `_HoverRowDelegate.paint`, replace the tail (from the `paint_option.state &= ...` line to the end of the method) with:

```python
        paint_option.state &= ~(
            QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_HasFocus
        )
        paint_option.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)

        if index.column() == 0:
            self._paint_checkbox(painter, paint_option, index)
            return
        if index.column() == _STATUS_COLUMN:
            self._paint_status_pill(painter, paint_option, index)
            return
        if index.column() == _NAME_COLUMN and index.row() == highlight_row:
            paint_option.palette.setColor(
                QPalette.ColorRole.Text, theme.qcolor("accent")
            )

        super().paint(painter, paint_option, index)
```

  - Add the pill painter to `_HoverRowDelegate` (below `_paint_checkbox`), mirroring `_episode_table_delegate._paint_pill`:

```python
    def _paint_status_pill(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        job = index.data(Qt.ItemDataRole.UserRole)
        if not text or job is None:
            return
        tone_token = _JOB_STATUS_TONE.get(job.status, "text_dim")
        color = theme.qcolor(tone_token)
        label = str(text).upper()
        metrics = option.fontMetrics
        pill_width = min(
            metrics.horizontalAdvance(label) + _scale.px(16),
            max(_scale.px(24), option.rect.width() - _scale.px(4)),
        )
        pill_height = metrics.height() + _scale.px(4)
        pill_rect = QRect(0, 0, pill_width, pill_height)
        pill_rect.moveCenter(option.rect.center())
        wash = QColor(color)
        wash.setAlphaF(0.12)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(wash)
        radius = theme.radius("pill")
        painter.drawRoundedRect(pill_rect, radius, radius)
        painter.setPen(color)
        painter.drawText(pill_rect, int(Qt.AlignmentFlag.AlignCenter), label)
        painter.restore()
```

  - In `_JobListTab.__init__`, directly after `self._table.verticalHeader().setVisible(False)`:

```python
        self._table.verticalHeader().setDefaultSectionSize(_scale.px(36))
```

- [ ] **Step 4: Remove the dead model color path** — in `job_table_model.py`, delete the `ForegroundRole` branch (`if role == Qt.ItemDataRole.ForegroundRole and column == 1: return _STATUS_COLOR.get(job.status)`) and the `_STATUS_COLOR` dict (the delegate owns status coloring now). Verify with `grep -n "_STATUS_COLOR" plex_renamer tests` — no remaining users.

- [ ] **Step 5: Button scheme** —
  - `_queue_tab_state.py`: `remove_button_css_class` becomes:

```python
def remove_button_css_class(*, enabled: bool) -> str:
    del enabled  # danger-outline has its own :disabled QSS variant
    return "danger-outline"
```

  - `queue_tab.py`: the `self._remove_btn.setProperty("cssClass", "secondary")` construction line becomes `self._remove_btn.setProperty("cssClass", "danger-outline")`.
  - `history_tab.py`: after `self._revert_btn = QPushButton("Revert Selected")` add `self._revert_btn.setProperty("cssClass", "danger-outline")`. (`Confirm Revert` keeps `"danger"`; `Start Queue` stays classless = primary — deviation 3.)

- [ ] **Step 6: Run the covering files** — `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py tests\test_qt_job_detail_panel.py tests\test_qt_main_window.py -q`
Expected: PASS (main-window queue-badge tests exercise refresh paths; nothing pins the old foreground color — verified by the Step-4 grep).

- [ ] **Step 7: Full suites** — green, zero skips.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_job_list_tab.py plex_renamer/gui_qt/models/job_table_model.py plex_renamer/gui_qt/widgets/_queue_tab_state.py plex_renamer/gui_qt/widgets/queue_tab.py plex_renamer/gui_qt/widgets/history_tab.py tests/test_qt_queue_history.py
git commit -m "feat(gui): queue/history painted status pills, accent selection title, taller rows, danger-outline removals"
```

---

### Task 3: Companion↔video pairing in the job preview data layer

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_job_detail_preview.py`
- Create: `tests/test_job_preview_grouping.py` (pure Python — fast suite picks it up automatically; do NOT touch the runner lists)

**Interfaces:**
- Consumes: `RenameOp` (`new_name`, `target_dir_relative`, `file_type`, `original_relative`), existing `build_job_preview_entries` structure.
- Produces: `JobPreviewRow` gains `badge: str = ""` and `children: tuple[JobPreviewRow, ...] = ()`; module functions `pair_companions_with_videos(video_ops, companion_ops) -> tuple[dict[int, list[RenameOp]], list[RenameOp]]` (dict keyed by `id(video_op)`) and `type_badge(file_type: str) -> str`. Task 4 renders `badge`/`children`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_job_preview_grouping.py`:

```python
# tests/test_job_preview_grouping.py
"""Companion↔video pairing for the job detail tree (Plan 7, spec §11/§13)."""
import unittest

from plex_renamer.job_store import RenameJob, RenameOp


def _video(stem: str, target_dir: str = "Show/Season 01") -> RenameOp:
    return RenameOp(
        original_relative=f"Show/{stem}.mkv",
        new_name=f"{stem}.mkv",
        target_dir_relative=target_dir,
        status="OK",
        file_type="video",
    )


def _subtitle(name: str, target_dir: str = "Show/Season 01") -> RenameOp:
    return RenameOp(
        original_relative=f"Show/{name}",
        new_name=name,
        target_dir_relative=target_dir,
        status="OK",
        file_type="subtitle",
    )


class PairCompanionsTests(unittest.TestCase):
    def test_companion_pairs_with_stem_prefix_video_in_same_dir(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            pair_companions_with_videos,
        )

        video = _video("Show - S01E01 - Pilot")
        sub = _subtitle("Show - S01E01 - Pilot.eng.srt")
        paired, unpaired = pair_companions_with_videos([video], [sub])
        self.assertEqual(paired, {id(video): [sub]})
        self.assertEqual(unpaired, [])

    def test_longest_stem_wins_when_one_title_prefixes_another(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            pair_companions_with_videos,
        )

        short = _video("Show - S01E01 - Part")
        long = _video("Show - S01E01 - Part Two")
        sub = _subtitle("Show - S01E01 - Part Two.eng.srt")
        paired, unpaired = pair_companions_with_videos([short, long], [sub])
        self.assertEqual(paired, {id(long): [sub]})
        self.assertEqual(unpaired, [])

    def test_dir_mismatch_and_no_prefix_stay_unpaired(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            pair_companions_with_videos,
        )

        video = _video("Show - S01E01 - Pilot")
        other_dir = _subtitle("Show - S01E01 - Pilot.eng.srt", target_dir="Show/Season 02")
        no_prefix = _subtitle("Totally Different.eng.srt")
        paired, unpaired = pair_companions_with_videos([video], [other_dir, no_prefix])
        self.assertEqual(paired, {})
        self.assertEqual(unpaired, [other_dir, no_prefix])

    def test_type_badge_names(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import type_badge

        self.assertEqual(type_badge("subtitle"), "SUB")
        self.assertEqual(type_badge("nfo"), "NFO")


class PreviewEntriesGroupingTests(unittest.TestCase):
    def _job(self, ops) -> RenameJob:
        return RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            media_type="tv",
            rename_ops=ops,
        )

    def test_video_rows_carry_companion_children_with_badges(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Show - S01E01 - Pilot")
        video.season = 1
        sub = _subtitle("Show - S01E01 - Pilot.eng.srt")
        entries = build_job_preview_entries(self._job([video, sub]))
        season_groups = [
            e for e in entries
            if isinstance(e, JobPreviewGroup) and e.label.startswith("Season")
        ]
        self.assertEqual(len(season_groups), 1)
        video_row = season_groups[0].rows[0]
        self.assertEqual(len(video_row.children), 1)
        self.assertEqual(video_row.children[0].badge, "SUB")
        self.assertEqual(video_row.children[0].after, "Show - S01E01 - Pilot.eng.srt")
        # Paired companions do NOT also appear in a flat residual group.
        self.assertFalse(
            any(
                isinstance(e, JobPreviewGroup) and e.label.startswith("Companion Files")
                for e in entries
            )
        )

    def test_unpaired_companions_keep_the_residual_group(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Show - S01E01 - Pilot")
        video.season = 1
        orphan = _subtitle("Unrelated Name.eng.srt")
        entries = build_job_preview_entries(self._job([video, orphan]))
        residual = [
            e for e in entries
            if isinstance(e, JobPreviewGroup) and e.label == "Companion Files (1)"
        ]
        self.assertEqual(len(residual), 1)
        self.assertEqual(residual[0].rows[0].badge, "SUB")

    def test_movie_rows_carry_children_too(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Movie (2021)", target_dir="Movie (2021)")
        sub = _subtitle("Movie (2021).eng.srt", target_dir="Movie (2021)")
        job = self._job([video, sub])
        job.media_type = "movie"
        entries = build_job_preview_entries(job)
        file_groups = [
            e for e in entries
            if isinstance(e, JobPreviewGroup) and e.label == "File Rename"
        ]
        self.assertEqual(len(file_groups), 1)
        self.assertEqual(len(file_groups[0].rows[0].children), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_preview_grouping.py -q`
Expected: FAIL — `ImportError` (`pair_companions_with_videos`, `type_badge` don't exist; `JobPreviewRow` has no `children`).

- [ ] **Step 3: Implement** in `_job_detail_preview.py`:
  - Extend `JobPreviewRow` (frozen dataclass — use a tuple default, not a list):

```python
@dataclass(frozen=True)
class JobPreviewRow:
    before: str
    after: str
    before_label: str = "Original"
    after_label: str = "New"
    badge: str = ""
    children: tuple["JobPreviewRow", ...] = ()
```

  - Add module helpers above `build_job_preview_entries`:

```python
_TYPE_BADGES = {"subtitle": "SUB"}


def type_badge(file_type: str) -> str:
    return _TYPE_BADGES.get(file_type, (file_type[:4] or "file").upper())


def pair_companions_with_videos(
    video_ops: list[RenameOp],
    companion_ops: list[RenameOp],
) -> tuple[dict[int, list[RenameOp]], list[RenameOp]]:
    """Pair each companion with the video whose target stem prefixes the
    companion's ``new_name`` in the same target dir (longest stem wins).

    Read-model heuristic only — ``RenameOp`` persists no linkage and §16
    forbids job-store schema changes.  Unmatched companions are returned
    for the residual "Companion Files" group, never dropped.
    """
    paired: dict[int, list[RenameOp]] = {}
    unpaired: list[RenameOp] = []
    for companion in companion_ops:
        best: RenameOp | None = None
        best_stem_len = -1
        for video in video_ops:
            if video.target_dir_relative != companion.target_dir_relative:
                continue
            stem = Path(video.new_name).stem
            if not stem or not companion.new_name.startswith(stem + "."):
                continue
            if len(stem) > best_stem_len:
                best, best_stem_len = video, len(stem)
        if best is None:
            unpaired.append(companion)
        else:
            paired.setdefault(id(best), []).append(companion)
    return paired, unpaired
```

  - Rework `build_job_preview_entries`'s tail (from the `ops = ...` line down) to pair first and route only the unpaired companions to the residual group:

```python
    ops = job.selected_ops or job.rename_ops
    if not ops:
        return entries

    video_ops = [op for op in ops if op.file_type == "video"]
    companion_ops = [op for op in ops if op.file_type != "video"]
    paired, unpaired = pair_companions_with_videos(video_ops, companion_ops)

    entries.extend(_build_video_preview_entries(job, video_ops, paired))

    if unpaired:
        entries.append(
            JobPreviewGroup(
                label=f"Companion Files ({len(unpaired)})",
                rows=[_preview_row_for_op(op) for op in unpaired],
                expanded=False,
            )
        )

    return entries
```

  - `_build_video_preview_entries` gains the `paired` parameter and threads it into every `_preview_row_for_op(op)` call for video ops — change its signature to `_build_video_preview_entries(job, video_ops, paired)` and each `rows=[_preview_row_for_op(op) for op in season_ops]` / `rows=[_preview_row_for_op(op) for op in video_ops]` list comprehension to `rows=[_video_preview_row(op, paired) for op in ...]`.
  - Replace `_preview_row_for_op` with the pair:

```python
def _video_preview_row(op: RenameOp, paired: dict[int, list[RenameOp]]) -> JobPreviewRow:
    children = tuple(_preview_row_for_op(c) for c in paired.get(id(op), ()))
    return JobPreviewRow(
        before=Path(op.original_relative).name,
        after=op.new_name,
        children=children,
    )


def _preview_row_for_op(op: RenameOp) -> JobPreviewRow:
    badge = type_badge(op.file_type) if op.file_type != "video" else ""
    return JobPreviewRow(
        before=Path(op.original_relative).name,
        after=op.new_name,
        badge=badge,
    )
```

- [ ] **Step 4: Run the new file + existing panel tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_preview_grouping.py tests\test_qt_job_detail_panel.py -q`
Expected: PASS (the panel renders `JobPreviewRow`s by named field — new defaulted fields are invisible to it until Task 4).

- [ ] **Step 5: Full suites** — green, zero skips (the new file lands in the fast sweep automatically; confirm its tests appear in the fast count).

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_job_detail_preview.py tests/test_job_preview_grouping.py
git commit -m "feat(gui): pair companion renames with their videos in job preview data (spec s11/s13 seam)"
```

---

### Task 4: Detail tree renders companion children with type badges

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/job_detail_panel.py` (`_RenamePreviewWidget` badge chip; `_add_preview_row` recursion; error-label inline stylesheet removal)
- Modify: `plex_renamer/gui_qt/resources/theme.qss.tmpl` (new `type-badge` + `job-detail-error` selectors, inserted directly after the `job-preview-target` rule ~line 765)
- Test: `tests/test_qt_job_detail_panel.py` (extend)

**Interfaces:**
- Consumes: Task 3's `JobPreviewRow.badge`/`.children`.
- Produces: `_RenamePreviewWidget(badge: str = "", ...)` with `_badge_label` attribute when badge is non-empty; `_add_preview_row(..., badge="", children=())` recurses; video items with children are expanded by default. QSS classes `type-badge`, `job-detail-error`.

- [ ] **Step 1: Write the failing tests** — append to the existing test class in `tests/test_qt_job_detail_panel.py` (match the file's existing fixture idioms for constructing a `JobDetailPanel` and a `RenameJob` — grep `set_job(` in-file and reuse the neighboring test's construction):

```python
    def test_preview_tree_nests_companions_under_their_video_with_badges(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            media_type="tv",
            rename_ops=[
                RenameOp(
                    original_relative="Show/ep1.mkv",
                    new_name="Show - S01E01 - Pilot.mkv",
                    target_dir_relative="Show/Season 01",
                    status="OK", season=1, file_type="video",
                ),
                RenameOp(
                    original_relative="Show/ep1.eng.srt",
                    new_name="Show - S01E01 - Pilot.eng.srt",
                    target_dir_relative="Show/Season 01",
                    status="OK", file_type="subtitle",
                ),
            ],
        )
        panel = JobDetailPanel()
        panel.resize(520, 700)
        panel.show()
        panel.set_job(job)
        self._app.processEvents()

        tree = panel._preview_tree
        season_header = None
        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if "Season" in item.text(0):
                season_header = item
        self.assertIsNotNone(season_header)
        video_item = season_header.child(0)
        self.assertEqual(video_item.childCount(), 1)           # companion nested
        self.assertTrue(video_item.isExpanded())               # visible by default
        companion_widget = tree.itemWidget(video_item.child(0), 0)
        self.assertIsNotNone(companion_widget)
        self.assertEqual(companion_widget._badge_label.text(), "SUB")
        panel.close()

    def test_error_label_uses_css_class_not_inline_stylesheet(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob

        panel = JobDetailPanel()
        job = RenameJob(
            library_root="C:/library", source_folder="Show",
            media_name="Example Show", error_message="boom",
        )
        panel.set_job(job)
        self.assertEqual(panel._error.styleSheet(), "")
        self.assertEqual(panel._error.property("cssClass"), "job-detail-error")
        self.assertEqual(panel._error.text(), "boom")
        panel.close()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_job_detail_panel.py -q`
Expected: FAIL — video item has `childCount() == 0`, `_badge_label` missing, error label carries an inline stylesheet.

- [ ] **Step 3: QSS selectors** — in `theme.qss.tmpl`, directly after the `QLabel[cssClass="job-preview-target"]` rule:

```css
/* Job preview companion type badge (spec §11/§13 grouping seam). */
QLabel[cssClass="type-badge"] {
    background-color: rgba(155, 155, 155, 0.15);
    color: ${text_dim};
    border: 1px solid ${border_light};
    border-radius: ${radius_sm}px;
    padding: 0px 6px;
    font-size: 10px;
    font-weight: 600;
}
QLabel[cssClass="job-detail-error"] {
    color: ${error};
}
```

- [ ] **Step 4: Implement the panel rendering** in `job_detail_panel.py`:
  - `_RenamePreviewWidget.__init__` gains `badge: str = ""` (keyword-only, beside the label kwargs). When truthy, add a badge chip in a third grid column so it tops-right the row:

```python
        if badge:
            self._badge_label = QLabel(badge)
            self._badge_label.setProperty("cssClass", "type-badge")
            self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._badge_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            layout.addWidget(
                self._badge_label, 0, 2,
                alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            )
```

    (place after the `self._after` block; no `_badge_label` attribute when badge is empty).
  - `_add_preview_entry`: group branch passes the row through — change the inner loop body to call `self._add_preview_row(header, row=row)`; the flat branch becomes `self._add_preview_row(self._preview_tree, row=entry)`.
  - Replace `_add_preview_row` with a row-object signature that recurses:

```python
    def _add_preview_row(self, parent, *, row: JobPreviewRow) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [""])
        widget = _RenamePreviewWidget(
            before=row.before,
            after=row.after,
            before_label=row.before_label,
            after_label=row.after_label,
            badge=row.badge,
            parent=self._preview_tree,
        )
        item.setSizeHint(0, widget.sizeHint())
        self._preview_tree.setItemWidget(item, 0, widget)
        for child in row.children:
            self._add_preview_row(item, row=child)
        if row.children:
            item.setExpanded(True)
        return item
```

    Update the one other caller (`_populate_preview_tree` flows through `_add_preview_entry` only — verify with an in-file grep for `_add_preview_row(`).
  - Error label: at construction (after `self._error = QLabel("")`) add `self._error.setProperty("cssClass", "job-detail-error")`; in `set_job`, replace the whole `if job.error_message: ... else: ...` stylesheet block with:

```python
        self._error.setText(job.error_message or "")
```

    Remove the now-unused `theme` import **only if** nothing else in the file uses `theme` (grep in-file first — the file imports `_scale, theme`; keep `_scale`).

- [ ] **Step 5: Run the covering files** — `.venv\Scripts\python.exe -m pytest tests\test_qt_job_detail_panel.py tests\test_job_preview_grouping.py tests\test_qt_queue_history.py -q`
Expected: PASS (existing panel tests exercise `_populate_preview_tree` through `set_job` — the row-object refactor must keep their tree shapes; season/companion group headers unchanged for unpaired fixtures).

- [ ] **Step 6: Full suites** — green, zero skips.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/widgets/job_detail_panel.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_qt_job_detail_panel.py
git commit -m "feat(gui): job detail tree nests companions with type badges under each rename"
```

---

### Task 5: History revert confirmation becomes a warning banner

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/history_tab.py` (banner frame hosts info + confirm/cancel)
- Modify: `plex_renamer/gui_qt/widgets/_history_tab_banner.py` (helpers take the banner frame)
- Modify: `plex_renamer/gui_qt/resources/theme.qss.tmpl` (revert-banner selectors, after the Task-4 block)
- Test: `tests/test_qt_queue_history.py` (adapt `test_history_tab_revert_uses_inline_confirmation_banner`, extend)

**Interfaces:**
- Consumes: existing `begin_revert_banner_state` / `sync_pending_revert_job_ids` state helpers (unchanged).
- Produces: `HistoryTab._revert_banner` (QFrame, cssClass `revert-banner`) containing `_revert_info`, `_confirm_revert_btn`, `_cancel_revert_btn`; helper signatures `show_revert_banner(banner, revert_button, info_label, *, info_text)` and `hide_revert_banner(banner, revert_button)`.

- [ ] **Step 1: Adapt + write the failing tests** — in `tests/test_qt_queue_history.py`:
  - In `test_history_tab_revert_uses_inline_confirmation_banner` (line ~88): keep the whole fixture and flow; wherever it asserts visibility of `_confirm_revert_btn`/`_cancel_revert_btn`/`_revert_info`/`_revert_btn` (read the in-file assertions and re-anchor them), add the banner-frame assertions alongside: after `_revert_selected` runs, `self.assertTrue(history_tab._revert_banner.isVisibleTo(history_tab))`; after confirm/cancel completes, `self.assertFalse(history_tab._revert_banner.isVisibleTo(history_tab))`. The child-widget assertions keep working because the same attributes now live inside the banner.
  - Append:

```python
    def test_revert_banner_is_a_styled_frame_between_table_and_actions(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            tab = HistoryTab(controller)
            banner = tab._revert_banner
            self.assertEqual(banner.property("cssClass"), "revert-banner")
            self.assertFalse(banner.isVisibleTo(tab))          # hidden until armed
            self.assertIs(tab._revert_info.parent(), banner)
            self.assertIs(tab._confirm_revert_btn.parent(), banner)
            self.assertIs(tab._cancel_revert_btn.parent(), banner)
            layout_index = tab._list_layout.indexOf(banner)
            actions_index = tab._list_layout.indexOf(tab._actions_bar)
            self.assertGreaterEqual(layout_index, 0)
            self.assertEqual(layout_index, actions_index - 1)  # directly above actions
            tab.close()
            controller.close()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py -q`
Expected: FAIL — `_revert_banner` doesn't exist.

- [ ] **Step 3: QSS** — after the Task-4 `job-detail-error` rule add:

```css
/* History revert confirmation banner (spec §11). */
QFrame[cssClass="revert-banner"] {
    background-color: rgba(210, 153, 34, 0.10);
    border: 1px solid ${warning};
    border-radius: ${radius_md}px;
}
QLabel[cssClass="revert-banner-text"] {
    color: ${warning};
    background: transparent;
}
```

- [ ] **Step 4: Implement** —
  - `_history_tab_banner.py` becomes:

```python
"""Revert-banner presentation helpers for HistoryTab."""

from __future__ import annotations


def show_revert_banner(banner, revert_button, info_label, *, info_text: str) -> None:
    info_label.setText(info_text)
    revert_button.hide()
    banner.show()


def hide_revert_banner(banner, revert_button) -> None:
    banner.hide()
    revert_button.show()
```

  - `history_tab.py`: add imports `QFrame`, `QHBoxLayout` to the QtWidgets import list and `from .. import _scale`. Replace the construction block (from `self._confirm_revert_btn = ...` through the `hide_revert_banner(...)` call, keeping `self._revert_btn` where it is in the actions layout) with:

```python
        self._revert_banner = QFrame()
        self._revert_banner.setProperty("cssClass", "revert-banner")
        banner_layout = QHBoxLayout(self._revert_banner)
        banner_layout.setContentsMargins(
            _scale.px(12), _scale.px(8), _scale.px(12), _scale.px(8)
        )
        banner_layout.setSpacing(_scale.px(8))

        self._revert_info = QLabel("")
        self._revert_info.setProperty("cssClass", "revert-banner-text")
        self._revert_info.setWordWrap(True)
        banner_layout.addWidget(self._revert_info, stretch=1)

        self._confirm_revert_btn = QPushButton("Confirm Revert")
        self._confirm_revert_btn.setProperty("cssClass", "danger")
        self._confirm_revert_btn.clicked.connect(self._confirm_revert)
        banner_layout.addWidget(self._confirm_revert_btn)

        self._cancel_revert_btn = QPushButton("Cancel")
        self._cancel_revert_btn.setProperty("cssClass", "secondary")
        self._cancel_revert_btn.clicked.connect(self._cancel_revert)
        banner_layout.addWidget(self._cancel_revert_btn)

        hide_revert_banner(self._revert_banner, self._revert_btn)
```

    and after `self._finish_list_pane()` insert the banner directly above the actions bar:

```python
        self._list_layout.insertWidget(
            self._list_layout.count() - 1, self._revert_banner
        )
```

  - Update the two call sites: `_revert_selected` → `show_revert_banner(self._revert_banner, self._revert_btn, self._revert_info, info_text=banner_state.info_text)`; `_cancel_revert` → `hide_revert_banner(self._revert_banner, self._revert_btn)`.

- [ ] **Step 5: Run the covering file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py -q` → PASS.

- [ ] **Step 6: Full suites** — green, zero skips.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/widgets/history_tab.py plex_renamer/gui_qt/widgets/_history_tab_banner.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_qt_queue_history.py
git commit -m "feat(gui): history revert confirmation becomes a warning banner"
```

---

### Task 6: Illustrated empty states for the queue/history tables

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_job_list_tab.py` (`_TableEmptyState` widget + table stack + `_sync_empty_state`)
- Modify: `plex_renamer/gui_qt/widgets/queue_tab.py` / `history_tab.py` (`refresh()` calls the sync)
- Modify: `plex_renamer/gui_qt/resources/theme.qss.tmpl` (one selector)
- Test: `tests/test_qt_queue_history.py` (extend)

**Interfaces:**
- Consumes: `_scale.icon("xl")`, `QApplication.style()` standard icons (same illustration language as `empty_state.py`'s drop zone: icon + heading + text-dim hint, centered).
- Produces: `_JobListTab._table_stack` (QStackedWidget hosting `_table` + `_table_empty`), `_TableEmptyState.set_texts(*, heading, hint)`, `_JobListTab._sync_empty_state()`, `_current_filter_label: str`.

- [ ] **Step 1: Write the failing tests** — append to `QtQueueHistoryTests`:

```python
    def test_empty_queue_table_shows_illustrated_empty_state(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            self.assertIs(
                queue_tab._table_stack.currentWidget(), queue_tab._table_empty
            )
            self.assertEqual(queue_tab._table_empty._heading.text(), "Queue is empty")
            self.assertIs(
                history_tab._table_stack.currentWidget(), history_tab._table_empty
            )
            self.assertEqual(history_tab._table_empty._heading.text(), "No history yet")
            queue_tab.close()
            history_tab.close()
            controller.close()

    def test_jobs_flip_the_stack_to_the_table_and_filters_show_no_match(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            store.add_job(RenameJob(
                library_root="C:/library", source_folder="Show",
                media_name="Example Show",
            ))
            controller = QueueController(store)
            tab = QueueTab(controller)
            self.assertIs(tab._table_stack.currentWidget(), tab._table)
            tab._filter_control.currentTextChanged.emit("Running")
            self._app.processEvents()
            self.assertIs(tab._table_stack.currentWidget(), tab._table_empty)
            self.assertEqual(tab._table_empty._heading.text(), "No matching jobs")
            self.assertIn("Running", tab._table_empty._hint.text())
            tab.close()
            controller.close()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py -q` → FAIL (`_table_stack` missing).

- [ ] **Step 3: QSS** — after the Task-5 revert-banner rules add:

```css
QFrame[cssClass="table-empty-state"] {
    background: transparent;
    border: none;
}
```

- [ ] **Step 4: Implement** in `_job_list_tab.py`:
  - Add `QApplication`, `QStackedWidget` to the QtWidgets import list (`QStyle` is already imported; `_scale` arrives in Task 2's import edit — if executing this task standalone, ensure `from .. import _scale, theme`).
  - Add the widget class above `_JobListTab`:

```python
class _TableEmptyState(QFrame):
    """Centered icon + heading + hint shown instead of an empty job table
    (spec §11: illustration treatment consistent with the workspace empty
    state's drop-zone language)."""

    def __init__(self, *, heading: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "table-empty-state")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(_scale.px(10))

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style = QApplication.style()
        if style is not None:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            icon_label.setPixmap(icon.pixmap(_scale.icon("xl")))
        layout.addWidget(icon_label)

        self._heading = QLabel(heading)
        self._heading.setProperty("cssClass", "heading")
        self._heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._heading)

        self._hint = QLabel(hint)
        self._hint.setProperty("cssClass", "text-dim")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

    def set_texts(self, *, heading: str, hint: str) -> None:
        self._heading.setText(heading)
        self._hint.setText(hint)
```

  - In `_JobListTab.__init__` (after the hover-delegate setup), build the stack and remember the tab's baseline strings:

```python
        if history:
            self._empty_heading = "No history yet"
            self._empty_hint = "Completed, failed, and reverted jobs will appear here."
        else:
            self._empty_heading = "Queue is empty"
            self._empty_hint = "Approve items in the TV or Movies tab, then queue them here."
        self._current_filter_label = "All"
        self._table_empty = _TableEmptyState(
            heading=self._empty_heading, hint=self._empty_hint
        )
        self._table_stack = QStackedWidget()
        self._table_stack.addWidget(self._table)
        self._table_stack.addWidget(self._table_empty)
```

  - `_finish_list_pane`: `self._list_layout.addWidget(self._table, stretch=1)` → `self._list_layout.addWidget(self._table_stack, stretch=1)`.
  - `_apply_filter` records the label and syncs — its body becomes:

```python
    def _apply_filter(self, label: str) -> None:
        self._current_filter_label = label
        self._proxy.set_allowed_statuses(self._filters.get(label))
        self._retain_visible_checked_jobs()
        self.refresh()
```

    (the sync happens inside the subclass `refresh()` — no second call here).
  - Add the sync method to `_JobListTab`:

```python
    def _sync_empty_state(self) -> None:
        if self._proxy.rowCount() > 0:
            self._table_stack.setCurrentWidget(self._table)
            return
        if self._model.rowCount() > 0:
            self._table_empty.set_texts(
                heading="No matching jobs",
                hint=f"No jobs match the {self._current_filter_label} filter.",
            )
        else:
            self._table_empty.set_texts(
                heading=self._empty_heading, hint=self._empty_hint
            )
        self._table_stack.setCurrentWidget(self._table_empty)
```

  - `queue_tab.py` `refresh()`: add `self._sync_empty_state()` immediately after `self._model.set_jobs(jobs)`. Same in `history_tab.py` `refresh()`.

- [ ] **Step 5: Run the covering file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_history.py tests\test_qt_main_window.py -q` → PASS (main-window tests construct both tabs through the shell — the stack must not disturb `select_job`/refresh flows).

- [ ] **Step 6: Full suites** — green, zero skips.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_job_list_tab.py plex_renamer/gui_qt/widgets/queue_tab.py plex_renamer/gui_qt/widgets/history_tab.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_qt_queue_history.py
git commit -m "feat(gui): queue/history empty tables get illustrated empty states"
```

---

### Task 7: Verification + bookkeeping (controller)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass, zero new skips; skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: Visual sanity** — throwaway offscreen grab script (scratchpad; `QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`, theme QSS applied). Grabs: (a) QueueTab with a mixed-status job set (pending/running/completed/failed) — painted pills per tone, merged Files column text, 36px rows, accent title on the current row, danger-outline Remove; (b) JobDetailPanel with a paired TV job — video row with nested SUB-badged companion child + residual group absent; (c) HistoryTab with the revert banner armed — warning wash + border, Confirm Revert danger; (d) both tabs empty — illustrated empty states, then a filter-no-match state. Assert parentage while grabbing (no stray visible top-levels — Plan 3's lesson). Keep script in scratchpad only.

- [ ] **Step 3: Update roadmap + handoff, commit** — roadmap row 7 → Landed (commit range); handoff status/current + "next step: write Plan 8 (settings restyle + mkvmerge seams, spec §12-§13)" + session log entry; carry forward the still-deferred items (Plan 6 minors M1-M6 not taken this plan; Plan 5 leftovers; this plan's recorded deviations 1-5, esp. the heuristic pairing).

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 7 landed; next up plan 8 (settings + mkvmerge seams)"
```

---

## Self-review notes (kept for the record)

- **Spec §11 coverage:** delegate restyle → pills/accent-title/row-height in Task 2 with stripe/selection/hover/alternation recorded as Plan-1-landed (deviation 1, alternation pinned by test); toolbar scheme → Task 2 (deviations 2-3 record the segmented-control and primary-button no-ops); Files column → Task 1 (exact `3 files (2 comp.)` format, singular handled, suffix drops at zero); companion grouping in the detail tree → Tasks 3-4 (pure pairing layer + rendering split so the heuristic is fast-tested without Qt); revert banner → Task 5; empty states → Task 6 (queue/history/filter-no-match variants, workspace illustration language).
- **Spec §13 seam:** the per-file grouping (video parent + typed companion children) is exactly the structure named in §13 as "the same structure a merge job will need"; `type_badge` is the badge vocabulary seam.
- **§16 discipline:** no job-store/controller edits anywhere; pairing is view-side and heuristic (deviation 4) because `RenameOp` persists no linkage; residual group guarantees nothing is hidden when the heuristic misses.
- **Plan-1 guard interactions:** the two `rgba(...)` additions use the documented hand-derived triples (warning 210,153,34; text_dim 155,155,155) — the no-hex guard only scans hex literals, and the tmpl header comment is updated by neither (values already listed). `_TRANSITION_COLORS` moves from raw `QColor(r,g,b,a)` literals to token-derived tints (Task 1) — closes a token-discipline gap the hex guard never saw.
- **Type-consistency pass:** `files_cell_text` defined Task 1, asserted Tasks 1; `_JOB_STATUS_TONE`/`_paint_status_pill` defined Task 2, tested Task 2; `JobPreviewRow.badge/children` + `pair_companions_with_videos` + `type_badge` defined Task 3, consumed Task 4 (`_add_preview_row(row=...)`, `_badge_label`); banner helpers' new signatures match both call sites and the layout test (Task 5); `_table_stack`/`_table_empty`/`_sync_empty_state`/`_current_filter_label` defined and tested Task 6; column constants Status=1/Name=2 consistent across Tasks 1-2.
- **Known test-plumbing risks:** Task 1 Step 5's stale-column grep is load-bearing (sort tests or badge counters may index old columns); Task 5 Step 1 adapts a named existing test by re-anchoring its visibility asserts — the implementer reads the real assertion lines rather than trusting a reproduction here; Task 4's tree test navigates by header text ("Season") to stay independent of the folder-group presence.
- **Empty-state stack risk:** `select_job` and the context-menu/current-row paths read `self._table` directly — the stack only re-parents the table, so those paths are untouched; the main-window covering run in Task 6 Step 5 guards the shell integration.
