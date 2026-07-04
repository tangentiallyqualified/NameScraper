# GUI V4 Plan 4: Bulk Assign Mode + Unassign-All Danger Treatment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unmap-then-modal-grind with an in-panel Bulk Assign mode (two-pane files→slots surface with assign-in-order, auto-map-remaining, and drag one-off pairs, applied as ONE batched service call), and make Unassign All visibly destructive (danger-outline, physical separation, exact-count confirm, bulk-assign offer) — spec §6, §15.7.

**Architecture:** A new `BulkAssignPanel` (two `QListView`s over two small `QAbstractListModel`s + a staging dict) swaps in for the episode table inside `MediaWorkPanel` via a `QStackedLayout`. Staging is purely local; **nothing touches the controller until Apply**, which fires one new additive `EpisodeMappingService.apply_assignments` call (loop `table.assign(..., displace=True)` + ONE `reproject`). Unassign All moves to an additive `EpisodeMappingService.unassign_all` (same single-reproject shape as the existing `approve_all`) behind a confirm dialog that offers Bulk Assign. Entry points: toolbar overflow "Bulk Assign…", the post-Unassign-All offer, and a Problems-filter empty-state hint row. Movie mode hides all of it.

**Tech Stack:** PySide6 (QStackedLayout, QListView/QAbstractListModel, drag-and-drop MIME, QMessageBox), theme tokens + `_scale`, existing `EpisodeMappingService` / `EpisodeAssignmentTable`, pytest + Qt smoke harness.

## Global Constraints

- Run Python/pytest through the venv: `.venv\Scripts\python.exe -m pytest ...` (Windows).
- `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` must pass at the end of every task; new Qt test files get added to BOTH runner lists: the Qt list in `scripts/test_smoke_runner.py` and the ignore list in `scripts/test_fast_runner.py` (same pattern as `tests/test_work_panel.py`).
- No hardcoded `P:\` paths in tests. No hex literals outside `theme.py` (guard enforced). No "Plex" strings in gui_qt (AST guard). All sizes via `_scale`. QSS colors only via `${tokens}` (rgba washes with numeric rgb components match existing file style).
- Engine and controllers unchanged. `EpisodeMappingService` gains EXACTLY TWO additive methods this plan specifies (`apply_assignments`, `unassign_all`) — both compose existing `EpisodeAssignmentTable` mutations + one `reproject`; no engine edits, no changes to existing service methods.
- Episode row action ids remain frozen (`approve`, `reassign`, `assign_to_more`, `unassign`, `keep_this`, `assign_file`); Bulk Assign does not add row action ids.
- **Nothing touches the controller until Apply** (spec §6): staging lives in `BulkAssignPanel`; Cancel discards; Apply = one `apply_assignments` call, one refresh, one toast.
- Bulk Assign MVP scope is spec §15.7 verbatim: check-files + assign-in-order + auto-map-remaining + drag single pairs; NO undo stack inside the mode (Apply/Cancel is the boundary).
- Movie mode: Bulk Assign not applicable — overflow entry hidden, hint row TV-only (spec §6).
- Guide building stays synchronous; BusyOverlay is Plan 5. The strip-rebuild perf item (Plan 3 deferred M2) stays deferred — do not touch `refresh_header`.
- Commit after every task with the messages given (trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`).

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `plex_renamer/app/services/episode_mapping_service.py` | modify | additive `apply_assignments(state, pairs)` + `unassign_all(state)` |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py` | create | `BulkFilesModel`, `BulkSlotsModel`, `BulkFilesView`, `BulkSlotsView`, `BulkAssignPanel` (staging, assign-in-order, auto-map, drag) |
| `plex_renamer/gui_qt/widgets/_work_panel.py` | modify | stacked table/bulk hosting, `enter/exit_bulk_assign`, toolbar overflow + danger-outline Unassign All |
| `plex_renamer/gui_qt/resources/theme.qss.tmpl` | modify | `danger-outline` button class + bulk-panel list styling |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py` + `_episode_table_delegate.py` | modify | `bulk-hint` empty-state row (Problems filter) + click signal |
| `media_workspace.py`, `_media_workspace_ui.py`, `_media_workspace_actions.py` | modify | entry/apply/cancel wiring, unassign-all confirm + offer, `toast_requested` |
| `plex_renamer/gui_qt/_main_window_tabs.py` | modify | connect `toast_requested` → `ToastManager.show_toast` |
| `plex_renamer/gui_qt/widgets/episode_assign_dialog.py` | modify | full-filename display (spec §6 first paragraph) |
| `tests/test_episode_mapping_projection.py` | modify | service batch-mutation tests |
| `tests/test_bulk_assign_panel.py` | create | panel/model/staging/drag tests (+ runner lists) |
| `tests/test_work_panel.py`, `tests/test_episode_table_model.py`, `tests/test_episode_table_delegate.py`, `tests/test_qt_media_workspace.py` | modify | hosting, hint row, workspace flows, dialog |

---

### Task 1: `EpisodeMappingService.apply_assignments` + `unassign_all`

**Files:**
- Modify: `plex_renamer/app/services/episode_mapping_service.py` (insert after `approve_all`, before `resolve_conflict`)
- Test: `tests/test_episode_mapping_projection.py` (append a new test class)

**Interfaces:**
- Consumes: `EpisodeAssignmentTable.assign(file_id, season, episodes, *, origin, displace)` (validates contiguity + slot existence, raises `ValueError`), `table.unassign(file_id)`, `table.assignments()`, `self.reproject(state)`, `ORIGIN_MANUAL`.
- Produces (Tasks 2/4 rely on these exact signatures):

```python
def apply_assignments(self, state: ScanState, pairs: list[tuple[int, int, int]]) -> tuple[int, int]:
    """Apply (file_id, season, episode) pairs in one batch: each valid pair
    becomes a single-episode manual assignment (displace=True); invalid pairs
    are skipped. ONE reproject at the end. Returns (applied, skipped)."""

def unassign_all(self, state: ScanState) -> int:
    """Unassign every assigned file (manual-unassign reason), ONE reproject.
    Returns the number of files unassigned (0 = no-op, no reproject)."""
```

- [ ] **Step 1: Write the failing tests** — append to `tests/test_episode_mapping_projection.py`:

```python
from plex_renamer.engine.episode_assignments import (
    REASON_MANUAL_UNASSIGN,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _table_state(*, slots: int = 4, files: tuple[str, ...] = ("a.mkv", "b.mkv", "c.mkv")):
    """ScanState backed by a real assignment table; all files start unassigned."""
    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    file_ids: list[int] = []
    for name in files:
        entry = table.add_file(Path(f"C:/lib/Show/{name}"))
        table.mark_unassigned(entry.file_id, "no episode parsed")
        file_ids.append(entry.file_id)
    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"})
    state.scanned = True
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state, file_ids


class BulkMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = EpisodeMappingService()

    def test_apply_assignments_batches_with_single_reproject(self):
        state, file_ids = _table_state()
        calls: list[int] = []
        original = EpisodeMappingService.reproject

        def counting(service_self, target):
            calls.append(1)
            return original(service_self, target)

        EpisodeMappingService.reproject = counting
        try:
            applied, skipped = self.service.apply_assignments(
                state, [(file_ids[0], 1, 2), (file_ids[1], 1, 3)],
            )
        finally:
            EpisodeMappingService.reproject = original
        self.assertEqual((applied, skipped), (2, 0))
        self.assertEqual(len(calls), 1)
        table = state.assignments
        self.assertEqual(table.assignment_for(file_ids[0]).episodes, (2,))
        self.assertEqual(table.assignment_for(file_ids[1]).episodes, (3,))

    def test_apply_assignments_skips_invalid_pairs(self):
        state, file_ids = _table_state()
        applied, skipped = self.service.apply_assignments(
            state, [(file_ids[0], 1, 1), (file_ids[1], 1, 99)],  # E99 has no slot
        )
        self.assertEqual((applied, skipped), (1, 1))
        self.assertIsNotNone(state.assignments.assignment_for(file_ids[0]))
        self.assertIsNone(state.assignments.assignment_for(file_ids[1]))

    def test_apply_assignments_empty_is_noop(self):
        state, _file_ids = _table_state()
        before = list(state.preview_items)
        self.assertEqual(self.service.apply_assignments(state, []), (0, 0))
        self.assertEqual(state.preview_items, before)  # no reproject ran

    def test_unassign_all_clears_every_assignment_once(self):
        state, file_ids = _table_state()
        self.service.apply_assignments(state, [(file_ids[0], 1, 1), (file_ids[1], 1, 2)])
        count = self.service.unassign_all(state)
        self.assertEqual(count, 2)
        table = state.assignments
        self.assertEqual(table.assignments(), [])
        self.assertEqual(table.unassigned_reasons[file_ids[0]], REASON_MANUAL_UNASSIGN)
        self.assertEqual(self.service.unassign_all(state), 0)  # idempotent no-op
```

- [ ] **Step 2: Run to verify FAIL** — `.venv\Scripts\python.exe -m pytest tests\test_episode_mapping_projection.py -q` → `AttributeError: ... has no attribute 'apply_assignments'`.

- [ ] **Step 3: Implement** — in `episode_mapping_service.py`, insert after `approve_all` (line ~129):

```python
    def apply_assignments(
        self, state: ScanState, pairs: list[tuple[int, int, int]],
    ) -> tuple[int, int]:
        """Apply (file_id, season, episode) pairs as one batch (Bulk Assign).

        Each valid pair becomes a single-episode manual assignment
        (displace=True, same semantics as assign_file); invalid pairs are
        skipped, not fatal. Exactly one reproject when anything applied.
        """
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        applied = 0
        skipped = 0
        for file_id, season, episode in pairs:
            try:
                table.assign(
                    file_id, season, [episode],
                    origin=ORIGIN_MANUAL, displace=True,
                )
            except ValueError:
                skipped += 1
                continue
            applied += 1
        if applied:
            self.reproject(state)
        return applied, skipped

    def unassign_all(self, state: ScanState) -> int:
        """Unassign every assigned file with one reproject (bulk Unassign All)."""
        table = self._require_table(state)
        file_ids = [assignment.file_id for assignment in table.assignments()]
        for file_id in file_ids:
            table.unassign(file_id)
        if file_ids:
            self.reproject(state)
        return len(file_ids)
```

- [ ] **Step 4: Run to verify PASS** — the new class passes; whole file stays green.

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/app/services/episode_mapping_service.py tests/test_episode_mapping_projection.py
git commit -m "feat(services): batched apply_assignments + unassign_all with single reproject"
```

---

### Task 2: `BulkAssignPanel` (files pane / slots pane / staging / drag)

**Files:**
- Create: `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py`
- Test: `tests/test_bulk_assign_panel.py` (add to `scripts/test_smoke_runner.py` list + `scripts/test_fast_runner.py` ignore list)

**Interfaces:**
- Consumes: `EpisodeMappingService.episode_slot_choices(state) -> list[EpisodeSlotChoice]` (fields `season/episode/title/claimed_by`, `label` property `"S01E03 - Title"`), `EpisodeMappingService.unassigned_file_previews(state) -> list[PreviewItem]` (`.file_id`, `.original`), theme (`qcolor`), `_scale`.
- Produces (Tasks 3–4 rely on these exact names):

```python
FILE_ID_ROLE = Qt.ItemDataRole.UserRole + 1   # int (files model)
SLOT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1  # tuple[int, int] | None (slots model)
_MIME_FILE_ID = "application/x-namescraper-file-id"

class BulkFilesModel(QAbstractListModel):
    def __init__(self, parent=None): ...
    def set_files(self, previews: list) -> None      # sorted by original.name.casefold()
    def set_search(self, text: str) -> None          # casefold substring on filename
    def set_staged(self, staged: dict[int, tuple[int, int]]) -> None
    def checked_file_ids(self) -> list[int]          # display order
    def file_id_at(self, row: int) -> int | None
    # roles: Display "name" or "name  →  S01E05" when staged; CheckState
    # (unstaged rows only); ToolTip full path (+ " — SxxEyy" when staged);
    # Foreground: staged rows theme.qcolor("accent")
    # flags: enabled | selectable | user-checkable (unstaged) | drag-enabled

class BulkSlotsModel(QAbstractListModel):
    def __init__(self, parent=None): ...
    def set_slots(self, choices: list, staged_names: dict[tuple[int, int], str]) -> None
    def slot_key_at(self, row: int) -> tuple[int, int] | None   # None on headers
    def is_claimed(self, key: tuple[int, int]) -> bool
    def row_for_key(self, key: tuple[int, int]) -> int          # -1 when absent
    # rows: "Season NN (count)" / "Specials (count)" headers (enabled-only) +
    # slot rows "S01E03 - Title — claimant.mkv" | "…  →  staged.mkv" | "…  — missing"
    # Foreground: claimed text_dim, staged accent, missing warning

class BulkFilesView(QListView): ...   # drag source (DragOnly, model mimeData)
class BulkSlotsView(QListView):       # drop target
    pair_dropped = Signal(int, tuple)  # file_id, (season, episode)

class BulkAssignPanel(QFrame):
    apply_requested = Signal(list)     # list[tuple[int, int, int]] (file_id, season, episode)
    cancelled = Signal()
    def __init__(self, parent=None): ...
    def show_state(self, state, service) -> None     # (re)build both panes, clear staging
    def staged_pairs(self) -> list[tuple[int, int, int]]
    def assign_in_order(self) -> None                # checked files → slots from anchor
    def auto_map_remaining(self) -> None             # unstaged files → unclaimed+unstaged slots
    def reset_staging(self) -> None
    # named attrs for tests/wiring: _files_model, _slots_model, _files_view,
    # _slots_view, _search_box, _assign_button, _auto_map_button,
    # _reset_button, _apply_button, _cancel_button, _status_label,
    # _anchor_key (tuple | None), _staged (dict[int, tuple[int, int]])
```

**Behavior contract (lock these semantics):**
- **Staging** is `self._staged: dict[int, tuple[int, int]]` (file_id → slot key) plus the derived reverse map; a slot holds at most one staged file, a file at most one staged slot. Staging never calls the service.
- **Anchor**: clicking a slot row (not header) sets `_anchor_key` and shows it in `_status_label` (`"Start at S01E05"`); clicking a header does nothing.
- **`assign_in_order()`**: take `_files_model.checked_file_ids()` (display order). Walk slot keys in `(season, episode)` sorted order starting at `_anchor_key` (inclusive; when `_anchor_key is None`, start at the first slot), skipping keys that are claimed (`is_claimed`) or already staged. Pair files to keys one-to-one; stage each pair; uncheck the staged files. If files remain when slots run out, `_status_label` shows `"{n} file(s) left unstaged — no free slots"`. Refresh both models.
- **`auto_map_remaining()`**: all visible unstaged file ids (display order, regardless of check state) paired against ALL unclaimed+unstaged slot keys in sorted order from the beginning. Stage, refresh. (The staged rows ARE the preview — spec's "preview before apply" is satisfied by the visible `→` pairings; Apply commits, Reset/Cancel discards.)
- **Drag one-off**: files view drags `_MIME_FILE_ID` = `str(file_id)`; slots view accepts the drop on a slot row only if the key is neither claimed nor staged, then emits `pair_dropped`; the panel handler `_handle_drop(file_id, key)` re-stages the file (dropping its previous staged slot if any). Dropping on a claimed slot or header is ignored (no displace in bulk MVP — displacement stays a single-row `reassign` affair).
- **Shift-range check**: in `BulkFilesView.mousePressEvent`, a click on the check zone with Shift held applies the toggled value to every row between the last-toggled row and this one (`_last_check_row` tracked on the view). Without Shift, default QListView check toggling applies.
- **Apply**: `_apply_button.clicked` → `apply_requested.emit(self.staged_pairs())`; disabled while `_staged` is empty. **Cancel**: `cancelled.emit()` (owner exits the mode; panel state is rebuilt on next `show_state`).
- Layout: `QHBoxLayout` of two `QVBoxLayout` columns — left: caption `"Unassigned files ({n})"` + `_search_box` (`QLineEdit`, placeholder `"Filter files…"`, clear button) + `_files_view`; right: caption `"Episode slots"` + `_slots_view`. Below, one button row: `_assign_button` (`"Assign in order"`, cssClass `primary`), `_auto_map_button` (`"Auto-map remaining"`, secondary), `_reset_button` (`"Reset"`, secondary), stretch, `_status_label` (caption), `_apply_button` (`"Apply"`, primary, disabled until staged), `_cancel_button` (`"Cancel"`, secondary). All spacing via `_scale.px`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bulk_assign_panel.py
"""BulkAssignPanel staging: assign-in-order, auto-map, drag pairs, apply payload."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _bulk_state(slots: int = 5, names: tuple[str, ...] = ("b.mkv", "a.mkv", "c.mkv")):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL, EpisodeAssignmentTable, EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    for name in names:
        entry = table.add_file(Path(f"C:/lib/Show/{name}"))
        table.mark_unassigned(entry.file_id, "no episode parsed")
    claimed = table.add_file(Path("C:/lib/Show/claimed.mkv"))
    table.assign(claimed.file_id, 1, [2], origin=ORIGIN_MANUAL)   # E02 pre-claimed
    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"})
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


class BulkAssignPanelTests(QtSmokeBase):
    def _panel(self):
        from plex_renamer.gui_qt.widgets._bulk_assign_panel import BulkAssignPanel

        state, service = _bulk_state()
        panel = BulkAssignPanel()
        panel.resize(900, 600)
        panel.show_state(state, service)
        return panel

    def test_files_sorted_and_searchable(self):
        panel = self._panel()
        model = panel._files_model
        names = [model.index(r, 0).data() for r in range(model.rowCount())]
        self.assertEqual(names, ["a.mkv", "b.mkv", "c.mkv"])
        panel._search_box.setText("b.m")
        self.assertEqual(panel._files_model.rowCount(), 1)
        panel._search_box.setText("")
        self.assertEqual(panel._files_model.rowCount(), 3)

    def test_assign_in_order_skips_claimed_and_unchecks(self):
        from PySide6.QtCore import Qt

        panel = self._panel()
        model = panel._files_model
        for row in range(2):  # check a.mkv + b.mkv
            model.setData(model.index(row, 0), Qt.CheckState.Checked.value,
                          Qt.ItemDataRole.CheckStateRole)
        panel._anchor_key = (1, 1)
        panel.assign_in_order()
        pairs = {(season, episode) for _fid, season, episode in panel.staged_pairs()}
        self.assertEqual(pairs, {(1, 1), (1, 3)})   # E02 claimed → skipped
        self.assertEqual(model.checked_file_ids(), [])

    def test_auto_map_remaining_fills_unclaimed_in_order(self):
        panel = self._panel()
        panel.auto_map_remaining()
        episodes = sorted(episode for _fid, _s, episode in panel.staged_pairs())
        self.assertEqual(episodes, [1, 3, 4])       # 3 files onto E01/E03/E04 (E02 claimed)
        self.assertEqual(len(panel.staged_pairs()), 3)

    def test_drop_stages_single_pair_and_rejects_claimed(self):
        panel = self._panel()
        file_id = panel._files_model.file_id_at(0)
        panel._handle_drop(file_id, (1, 4))
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        panel._handle_drop(file_id, (1, 2))          # claimed → ignored
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        self.assertEqual(len(panel.staged_pairs()), 1)

    def test_apply_emits_payload_and_reset_clears(self):
        panel = self._panel()
        panel.auto_map_remaining()
        fired: list[list] = []
        panel.apply_requested.connect(fired.append)
        self.assertTrue(panel._apply_button.isEnabled())
        panel._apply_button.click()
        self.assertEqual(len(fired), 1)
        self.assertEqual(len(fired[0]), 3)
        panel.reset_staging()
        self.assertEqual(panel.staged_pairs(), [])
        self.assertFalse(panel._apply_button.isEnabled())

    def test_slot_rows_show_claim_and_staged_markers(self):
        panel = self._panel()
        model = panel._slots_model
        claimed_row = model.row_for_key((1, 2))
        self.assertIn("claimed.mkv", model.index(claimed_row, 0).data())
        panel._handle_drop(panel._files_model.file_id_at(0), (1, 1))
        staged_row = panel._slots_model.row_for_key((1, 1))
        self.assertIn("→", panel._slots_model.index(staged_row, 0).data())
```

- [ ] **Step 2: Run to verify FAIL** — `ModuleNotFoundError: plex_renamer.gui_qt.widgets._bulk_assign_panel`.

- [ ] **Step 3: Implement `_bulk_assign_panel.py`** per the interface + behavior contract. Key mechanics: models rebuild via `beginResetModel`/`endResetModel` from `set_files`/`set_slots`; the panel refreshes after every staging change with `self._files_model.set_staged(dict(self._staged))` and `self._slots_model.set_slots(self._choices, {key: name for ...})` (cache `self._choices`/`self._previews` on `show_state`); `staged_pairs()` returns `[(fid, s, e) for fid, (s, e) in sorted(self._staged.items())]`; `_apply_button.setEnabled(bool(self._staged))` after each refresh. Files model `mimeData` packs `_MIME_FILE_ID`; `BulkSlotsView.dropEvent` resolves `indexAt(pos)` → `slot_key_at` → emits `pair_dropped` only for droppable keys, and `dragEnterEvent`/`dragMoveEvent` accept the custom MIME; the panel wires `self._slots_view.pair_dropped.connect(self._handle_drop)` and `self._slots_view.clicked.connect(self._on_slot_clicked)` (sets `_anchor_key` for slot rows). No `processEvents` anywhere.

- [ ] **Step 4: Run to verify PASS** — 6 passed.

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets/_bulk_assign_panel.py tests/test_bulk_assign_panel.py scripts
git commit -m "feat(gui): BulkAssignPanel - files/slots panes, staging, assign-in-order, auto-map, drag pairs"
```

---

### Task 3: Work panel hosting + toolbar (overflow entry, danger-outline Unassign All)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_work_panel.py`, `plex_renamer/gui_qt/resources/theme.qss.tmpl`
- Test: `tests/test_work_panel.py` (extend)

**Interfaces:**
- Consumes: Task 2 `BulkAssignPanel`.
- Produces (Task 4 relies on these):

```python
class MediaWorkPanel(QFrame):
    bulk_assign_requested = Signal()          # overflow menu action (and Task 5 hint forward)
    @property bulk_panel -> BulkAssignPanel
    @property overflow_button -> QToolButton  # "⋯", tv only
    def bulk_assign_active(self) -> bool
    def enter_bulk_assign(self) -> None       # stack → bulk page; filters/search disabled;
                                              # Approve All/Unassign All hidden while active
    def exit_bulk_assign(self) -> None        # stack → table page; update_toolbar(self._state)
```

- [ ] **Step 1: Write the failing tests** — append to `tests/test_work_panel.py` (reuse its existing `_guide_state`-based `_panel` helper):

```python
    def test_bulk_mode_swaps_stack_and_gates_toolbar(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        self.assertFalse(panel.bulk_assign_active())
        panel.enter_bulk_assign()
        self.assertTrue(panel.bulk_assign_active())
        self.assertIs(panel._table_stack.currentWidget(), panel.bulk_panel)
        self.assertFalse(panel.segmented_filter.isEnabled())
        self.assertFalse(panel.search_box.isEnabled())
        self.assertFalse(panel.approve_all_button.isVisible())
        self.assertFalse(panel.unassign_all_button.isVisible())
        panel.exit_bulk_assign()
        self.assertFalse(panel.bulk_assign_active())
        self.assertIs(panel._table_stack.currentWidget(), panel.table_view)
        self.assertTrue(panel.segmented_filter.isEnabled())
        panel.close()

    def test_overflow_menu_emits_bulk_assign_requested(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[bool] = []
        panel.bulk_assign_requested.connect(lambda: fired.append(True))
        actions = panel.overflow_button.menu().actions()
        self.assertEqual([a.text() for a in actions], ["Bulk Assign…"])
        actions[0].trigger()
        self.assertEqual(fired, [True])

    def test_unassign_all_is_danger_outline(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertEqual(panel.unassign_all_button.property("cssClass"), "danger-outline")

    def test_movie_mode_hides_overflow(self):
        from pathlib import Path
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        panel = MediaWorkPanel(media_type="movie")
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        self.assertFalse(panel.overflow_button.isVisible())
        panel.close()
```

- [ ] **Step 2: Run to verify FAIL** (no `_table_stack` / `overflow_button` / class mismatch).

- [ ] **Step 3: Implement.** In `_build_table`, host the stack (import `QStackedLayout`, `QToolButton`, `QMenu`; `BulkAssignPanel` from `._bulk_assign_panel`):

```python
    def _build_table(self, outer: QVBoxLayout) -> None:
        self._model = EpisodeTableModel(
            media_type=self._media_type,
            settings_service=self._settings,
            guide_provider=self._guide_provider,
        )
        self._table_view = EpisodeTableView()
        self._table_view.setModel(self._model)
        self._delegate = EpisodeTableDelegate(self._table_view, media_type=self._media_type)
        self._table_view.setItemDelegate(self._delegate)
        self._table_view.header_clicked.connect(self._on_header_clicked)
        self._bulk_panel = BulkAssignPanel()
        stack_host = QWidget()
        self._table_stack = QStackedLayout(stack_host)
        self._table_stack.addWidget(self._table_view)
        self._table_stack.addWidget(self._bulk_panel)
        outer.addWidget(stack_host, stretch=1)
```

In `_build_toolbar`, replace the two-button tail (keep signal wiring identical; Approve All stays primary-right, then a fixed gap, then the danger-outline Unassign All, then the overflow):

```python
        toolbar.addStretch()

        self._approve_all_button = QPushButton("Approve All")
        self._approve_all_button.setProperty("cssClass", "primary")
        self._approve_all_button.setProperty("sizeVariant", "compact")
        self._approve_all_button.hide()
        self._approve_all_button.clicked.connect(self.approve_all_clicked.emit)
        toolbar.addWidget(self._approve_all_button)

        toolbar.addSpacing(_scale.px(24))   # physical separation (spec §6)

        self._unassign_all_button = QPushButton("Unassign All")
        self._unassign_all_button.setProperty("cssClass", "danger-outline")
        self._unassign_all_button.setProperty("sizeVariant", "compact")
        self._unassign_all_button.hide()
        self._unassign_all_button.clicked.connect(self.unassign_all_clicked.emit)
        toolbar.addWidget(self._unassign_all_button)

        self._overflow_button = QToolButton()
        self._overflow_button.setText("⋯")
        self._overflow_button.setProperty("cssClass", "toolbar-overflow")
        self._overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        overflow_menu = QMenu(self._overflow_button)
        overflow_menu.addAction("Bulk Assign…", self.bulk_assign_requested.emit)
        self._overflow_button.setMenu(overflow_menu)
        if self._media_type == "movie":
            self._overflow_button.hide()
        toolbar.addWidget(self._overflow_button)
```

Mode methods + property (place with the other public API; `bulk_assign_active` reads the stack):

```python
    @property
    def bulk_panel(self) -> BulkAssignPanel:
        return self._bulk_panel

    @property
    def overflow_button(self) -> QToolButton:
        return self._overflow_button

    def bulk_assign_active(self) -> bool:
        return self._table_stack.currentWidget() is self._bulk_panel

    def enter_bulk_assign(self) -> None:
        self._table_stack.setCurrentWidget(self._bulk_panel)
        self._segmented_filter.setEnabled(False)
        self._search_box.setEnabled(False)
        self._approve_all_button.hide()
        self._unassign_all_button.hide()

    def exit_bulk_assign(self) -> None:
        self._table_stack.setCurrentWidget(self._table_view)
        self._segmented_filter.setEnabled(True)
        self._search_box.setEnabled(True)
        if self._state is not None:
            self.update_toolbar(self._state)
```

`update_toolbar` additionally hides the overflow while `bulk_assign_active()` is True and shows it back for tv otherwise — add as the first lines:

```python
        if self._media_type != "movie":
            self._overflow_button.setVisible(not self.bulk_assign_active())
```

`theme.qss.tmpl` — add after the `danger` block (colors: tokens + the existing error-wash rgb triplet style):

```css
/* Danger outline button (destructive-but-not-primary; spec §6 Unassign All) */
QPushButton[cssClass="danger-outline"] {
    background-color: transparent;
    color: ${error};
    border: 1px solid ${error};
}

QPushButton[cssClass="danger-outline"]:hover {
    background-color: rgba(229, 83, 75, 0.12);
}

QPushButton[cssClass="danger-outline"]:disabled {
    color: ${text_dim};
    border-color: ${border_light};
}

QPushButton[cssClass="danger-outline"][sizeVariant="compact"] {
    padding: 2px 6px;
    font-size: 11px;
}

QToolButton[cssClass="toolbar-overflow"] {
    background-color: transparent;
    color: ${text};
    border: 1px solid ${border_light};
    border-radius: ${radius_sm}px;
    padding: 1px 8px;
}

QToolButton[cssClass="toolbar-overflow"]::menu-indicator {
    image: none;
}

QToolButton[cssClass="toolbar-overflow"]:hover {
    background-color: ${card_hover};
}
```

- [ ] **Step 4: Run to verify PASS** — new tests + full `tests\test_work_panel.py` green.

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets/_work_panel.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_work_panel.py
git commit -m "feat(gui): work panel hosts bulk-assign stack; overflow entry; danger-outline Unassign All"
```

---

### Task 4: Workspace wiring — enter/apply/cancel, confirm-with-offer, one toast

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`, `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, `plex_renamer/gui_qt/_main_window_tabs.py`
- Test: `tests/test_qt_media_workspace.py` (extend)

**Interfaces:**
- Consumes: Tasks 1–3 (`apply_assignments`, `unassign_all`, `enter/exit_bulk_assign`, `bulk_panel`, `bulk_assign_requested`, `apply_requested`, `cancelled`); existing idioms `_refresh_episode_projection(workspace, state)`, `workspace.refresh_from_controller()`, `workspace.status_message`, injectable `warning_box` (pattern from `handle_episode_row_action`), `window._toast_manager.show_toast(title=, message=, tone=, duration_ms=)`.
- Produces:

```python
# media_workspace.py
toast_requested = Signal(str, str, str)        # title, message, tone
def _enter_bulk_assign(self) -> None            # → action coordinator enter_bulk_assign()
def _on_bulk_apply(self, pairs: list) -> None   # → action coordinator apply_bulk_assignments(pairs)
def _on_bulk_cancel(self) -> None               # → action coordinator cancel_bulk_assign()

# _media_workspace_actions.py (MediaWorkspaceActionCoordinator)
def enter_bulk_assign(self) -> None
def apply_bulk_assignments(self, pairs: list[tuple[int, int, int]]) -> None
def cancel_bulk_assign(self) -> None
def unassign_all_episode_mappings(self, *, warning_box: Any = QMessageBox) -> None  # rewritten
```

- [ ] **Step 1: Write the failing tests** — add a self-contained test class to `tests/test_qt_media_workspace.py`. The file's idiom (see `QtMediaWorkspaceTests.test_media_workspace_queue_buttons_use_distinct_labels`, line ~28) is inline fake controllers + a real `MediaWorkspace`; the module already imports `TemporaryDirectory`, `Path`, `ScanState`, `SettingsService`, `CommandGatingService`. Fixture:

```python
class BulkAssignWorkspaceTests(QtSmokeBase):
    def _tv_workspace_with_table_state(self, *, assign_first: bool = False):
        from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_MANUAL, EpisodeAssignmentTable, EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        table = EpisodeAssignmentTable()
        for episode in range(1, 5):
            table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
        file_ids: list[int] = []
        for name in ("a.mkv", "b.mkv", "c.mkv"):
            entry = table.add_file(Path(f"C:/library/tv/Show/{name}"))
            table.mark_unassigned(entry.file_id, "no episode parsed")
            file_ids.append(entry.file_id)
        if assign_first:
            table.assign(file_ids[0], 1, [1], origin=ORIGIN_MANUAL)
            table.assign(file_ids[1], 1, [2], origin=ORIGIN_MANUAL)
        state = ScanState(folder=Path("C:/library/tv/Show"),
                          media_info={"id": 101, "name": "Show", "year": "2024"})
        state.scanned = True
        state.confidence = 1.0
        state.assignments = table
        EpisodeMappingService().reproject(state)

        class _FakeQueueController:
            def add_tv_batch(self, states, root, output_root, gating):
                return None

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        settings = SettingsService(path=Path(tmp.name) / "settings.json")
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController(),
            queue_controller=_FakeQueueController(),
            settings_service=settings,
        )
        self.addCleanup(workspace.close)
        workspace.resize(1200, 700)
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()
        self.assertIs(workspace._selected_state(), state)
        return workspace
    def test_overflow_entry_enters_bulk_mode(self):
        workspace = self._tv_workspace_with_table_state()
        workspace._enter_bulk_assign()
        self.assertTrue(workspace._work_panel.bulk_assign_active())
        # files pane populated from the state's unassigned previews
        self.assertEqual(workspace._work_panel.bulk_panel._files_model.rowCount(), 3)

    def test_apply_lands_assignments_and_exits_with_one_toast(self):
        workspace = self._tv_workspace_with_table_state()
        state = workspace._selected_state()
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        panel.auto_map_remaining()
        toasts: list[tuple] = []
        workspace.toast_requested.connect(lambda *a: toasts.append(a))
        panel._apply_button.click()
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0][2], "success")
        self.assertIn("3", toasts[0][1])                    # "Assigned 3 file(s)."
        table = state.assignments
        self.assertEqual(len(table.assignments()), 3)

    def test_cancel_discards_and_restores_table(self):
        workspace = self._tv_workspace_with_table_state()
        state = workspace._selected_state()
        workspace._enter_bulk_assign()
        workspace._work_panel.bulk_panel.auto_map_remaining()
        workspace._work_panel.bulk_panel._cancel_button.click()
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(state.assignments.assignments(), [])   # nothing applied

    def test_unassign_all_confirms_with_exact_count_and_offers_bulk(self):
        from PySide6.QtWidgets import QMessageBox

        workspace = self._tv_workspace_with_table_state(assign_first=True)  # pre-assign 2 files
        state = workspace._selected_state()
        prompts: list[str] = []

        class _Box:
            StandardButton = QMessageBox.StandardButton

            @staticmethod
            def question(parent, title, text, buttons, default):
                prompts.append(text)
                return QMessageBox.StandardButton.Yes          # plain unassign

        workspace._action_coordinator.unassign_all_episode_mappings(warning_box=_Box)
        self.assertIn("2", prompts[0])                          # exact count in the prompt
        self.assertEqual(state.assignments.assignments(), [])
        self.assertFalse(workspace._work_panel.bulk_assign_active())

    def test_unassign_all_bulk_offer_enters_mode(self):
        from PySide6.QtWidgets import QMessageBox

        workspace = self._tv_workspace_with_table_state(assign_first=True)

        class _Box:
            StandardButton = QMessageBox.StandardButton

            @staticmethod
            def question(parent, title, text, buttons, default):
                return QMessageBox.StandardButton.YesToAll      # "Unassign & Bulk Assign…"

        workspace._action_coordinator.unassign_all_episode_mappings(warning_box=_Box)
        self.assertTrue(workspace._work_panel.bulk_assign_active())
```

- [ ] **Step 2: Run to verify FAIL.**

- [ ] **Step 3: Implement.**

`media_workspace.py` — add the signal next to `status_message` (line ~48) and the thin handlers next to the other episode handlers:

```python
    toast_requested = Signal(str, str, str)   # title, message, tone ("success"/"info"/"error")
```

```python
    def _enter_bulk_assign(self) -> None:
        self._action_coordinator.enter_bulk_assign()

    def _on_bulk_apply(self, pairs: list) -> None:
        self._action_coordinator.apply_bulk_assignments(pairs)

    def _on_bulk_cancel(self) -> None:
        self._action_coordinator.cancel_bulk_assign()
```

`_media_workspace_ui.py` — in `_build_work_panel`, after the existing `panel.*` connections:

```python
        panel.bulk_assign_requested.connect(workspace._enter_bulk_assign)
        panel.bulk_panel.apply_requested.connect(workspace._on_bulk_apply)
        panel.bulk_panel.cancelled.connect(workspace._on_bulk_cancel)
```

`_media_workspace_actions.py` — new methods on the coordinator (imports at top of file already include `EpisodeMappingService`, `QMessageBox`):

```python
    def enter_bulk_assign(self) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        if workspace._media_type == "movie" or state.assignments is None:
            return
        panel = workspace._work_panel
        panel.bulk_panel.show_state(state, EpisodeMappingService())
        panel.enter_bulk_assign()

    def apply_bulk_assignments(self, pairs: list[tuple[int, int, int]]) -> None:
        workspace = self._workspace
        state = workspace._selected_state()
        panel = workspace._work_panel
        panel.exit_bulk_assign()
        if state is None or not pairs:
            return
        applied, skipped = EpisodeMappingService().apply_assignments(state, pairs)
        if applied == 0:
            workspace.status_message.emit("No assignments were applied.", 4000)
            return
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        message = f"Assigned {applied} file(s)."
        if skipped:
            message += f" {skipped} skipped."
        workspace.toast_requested.emit("Bulk Assign", message, "success")

    def cancel_bulk_assign(self) -> None:
        workspace = self._workspace
        workspace._work_panel.exit_bulk_assign()
        workspace.status_message.emit("Bulk Assign cancelled - nothing was changed.", 3000)
```

Rewrite `unassign_all_episode_mappings` (replacing the per-file loop) — the confirm uses `question()` with three standard buttons so the injectable box stays a plain `QMessageBox` shim: `Yes` = plain unassign, `YesToAll` = unassign + open Bulk Assign, `Cancel` = abort. Button labels are set via `button(...).setText(...)` on the real path; the injected test box only sees the return value:

```python
    def unassign_all_episode_mappings(self, *, warning_box: Any = QMessageBox) -> None:
        """Danger-treated Unassign All: exact-count confirm + bulk-assign offer."""
        workspace = self._workspace
        state = workspace._selected_state()
        if state is None or state.queued or state.scanning:
            return
        if state.assignments is None:
            return
        count = len(state.assignments.assignments())
        if count == 0:
            return
        if warning_box is QMessageBox:
            box = QMessageBox(workspace)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Unassign All")
            box.setText(
                f"Unassign all {count} assigned file(s) for {state.display_name}?\n"
                "Every episode mapping for this show will be cleared."
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.YesToAll
                | QMessageBox.StandardButton.Cancel
            )
            box.button(QMessageBox.StandardButton.Yes).setText("Unassign All")
            box.button(QMessageBox.StandardButton.YesToAll).setText("Unassign && Bulk Assign…")
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            answer = box.exec()
        else:
            answer = warning_box.question(
                workspace, "Unassign All",
                f"Unassign all {count} assigned file(s) for {state.display_name}?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.YesToAll
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
        if answer not in (
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.YesToAll,
        ):
            return
        unassigned = EpisodeMappingService().unassign_all(state)
        if unassigned == 0:
            return
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(f"Unassigned {unassigned} file(s).", 3000)
        if answer == QMessageBox.StandardButton.YesToAll:
            self.enter_bulk_assign()
```

(The old docstring's "lock-step with the per-row unassign path" rationale is superseded: `unassign_all` composes the same `table.unassign` mutation with one reproject — identical outcome, one projection pass instead of N. Note this in the commit body.)

`_main_window_tabs.py` — next to the two `status_message.connect` lines (~88-89):

```python
        for workspace in (window._tv_workspace, window._movie_workspace):
            workspace.toast_requested.connect(
                lambda title, message, tone, window=window: window._toast_manager.show_toast(
                    title=title, message=message, tone=tone, duration_ms=4000,
                )
            )
```

- [ ] **Step 4: Run to verify PASS** — the new class + the file's episode-mapping classes green.

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt tests/test_qt_media_workspace.py
git commit -m "feat(gui): bulk-assign workspace wiring - enter/apply/cancel, unassign-all confirm with offer, toast signal"
```

---

### Task 5: Problems-filter empty-state hint row

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_model.py`, `plex_renamer/gui_qt/widgets/_episode_table_delegate.py`, `plex_renamer/gui_qt/widgets/_work_panel.py`
- Test: `tests/test_episode_table_model.py`, `tests/test_episode_table_delegate.py` (extend)

**Interfaces:**
- Produces: row kind `"bulk-hint"` (model), `EpisodeTableView.bulk_hint_clicked = Signal()`, forwarded by `MediaWorkPanel` to its existing `bulk_assign_requested` signal.

**Contract:** under `filter_mode == "problems"`, TV mode only, when the guide has ≥1 unmapped primary file AND no episode row with status in `{"Review", "Conflict"}`, the model prepends ONE entry: kind `"bulk-hint"`, text `f"No problem episodes — {n} unmapped file(s). Open Bulk Assign to map them…"`, `EpisodeRowData(kind="bulk-hint", title=<same text>, status_tone="info")`, `section_key=None`, not selectable (`ItemIsEnabled` only, same flags branch as headers). Clicking it emits `bulk_hint_clicked` (view `clicked` routing, same pattern as `header_clicked`). The delegate paints it at `px(34)` like a section label but with `accent` text and a `selection_bg`-tinted fill so it reads as actionable.

- [ ] **Step 1: Write the failing tests**

`tests/test_episode_table_model.py` (append to the class; `_guide_state()`'s guide has one Review row — mutate it to Mapped for the hint case):

```python
    def test_problems_filter_bulk_hint_when_only_unmapped_remain(self):
        state, guide = _guide_state()
        guide.rows[1].status = "Mapped"          # no Review/Conflict left
        model = self._model(state, guide)
        model.set_filter_mode("problems")
        kinds = [model.row_kind_at(r) for r in range(model.rowCount())]
        self.assertEqual(kinds[0], "bulk-hint")
        self.assertEqual(kinds.count("bulk-hint"), 1)
        text = model.index(0, 0).data()
        self.assertIn("1 unmapped", text)

    def test_no_bulk_hint_when_review_rows_exist_or_other_filters(self):
        state, guide = _guide_state()
        model = self._model(state, guide)        # guide still has a Review row
        model.set_filter_mode("problems")
        kinds = [model.row_kind_at(r) for r in range(model.rowCount())]
        self.assertNotIn("bulk-hint", kinds)
        guide.rows[1].status = "Mapped"
        model.set_filter_mode("all")
        self.assertNotIn("bulk-hint",
                         [model.row_kind_at(r) for r in range(model.rowCount())])
```

`tests/test_episode_table_delegate.py` (append; reuse `_view` then re-point the model):

```python
    def test_bulk_hint_click_emits_signal(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        guide.rows[1].status = "Mapped"
        view, model, delegate = self._view(state, guide)
        model.set_filter_mode("problems")
        view.show()
        fired: list[bool] = []
        view.bulk_hint_clicked.connect(lambda: fired.append(True))
        rect = view.visualRect(model.index(0, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(fired, [True])
        view.close()
```

- [ ] **Step 2: Run to verify FAIL.**

- [ ] **Step 3: Implement.**

Model — in the TV composition path, immediately before yielding the unmapped section, insert (mirror the existing `_label_entry` helper; `media_type` guard is implicit — this branch is TV-only):

```python
        if (
            self._filter_mode == "problems"
            and guide.unmapped_primary_files
            and not any(row.status in ("Review", "Conflict") for row in guide.rows)
        ):
            n = len(guide.unmapped_primary_files)
            text = f"No problem episodes — {n} unmapped file(s). Open Bulk Assign to map them…"
            yield _Entry(
                kind="bulk-hint",
                section_key=None,
                text=text,
                preview_index=None,
                guide_row=None,
                row_data=EpisodeRowData(kind="bulk-hint", title=text, status_tone="info"),
            )
```

Model `flags()` — add `"bulk-hint"` to the enabled-only kinds set:

```python
        if entry.kind in {"section-header", "section-label", "folder", "bulk-hint"}:
            return Qt.ItemFlag.ItemIsEnabled
```

Delegate — `sizeHint`: return `px(34)` for `"bulk-hint"` (add it beside the single-line branch). `paint` dispatch: add before the header branch:

```python
        if kind == "bulk-hint":
            painter.save()
            fill = theme.qcolor("selection_bg")
            painter.fillRect(option.rect, fill)
            painter.setPen(theme.qcolor("accent"))
            text_rect = option.rect.adjusted(_scale.px(8), 0, -_scale.px(8), 0)
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             index.data() or "")
            painter.restore()
            return
```

View — signal + routing in `_on_clicked`:

```python
    bulk_hint_clicked = Signal()
```

```python
    def _on_clicked(self, index: QModelIndex) -> None:
        kind = index.data(ROW_KIND_ROLE)
        if kind == "section-header":
            section_key = index.data(SECTION_KEY_ROLE)
            if section_key:
                self.header_clicked.emit(section_key)
        elif kind == "bulk-hint":
            self.bulk_hint_clicked.emit()
```

`_work_panel.py` — one line in `_build_table` after the header connection:

```python
        self._table_view.bulk_hint_clicked.connect(self.bulk_assign_requested.emit)
```

- [ ] **Step 4: Run to verify PASS.**

- [ ] **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets tests
git commit -m "feat(gui): problems-filter empty-state hint row routes into Bulk Assign"
```

---

### Task 6: `EpisodeAssignDialog` full-filename display (spec §6 restyle slice)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/episode_assign_dialog.py`
- Test: `tests/test_qt_media_workspace.py` (the file already holds the dialog's tests — extend beside them)

**Contract:** the filename the user is verifying must never be truncated (spec §6: dialogs "gain full-filename display"). The header file label becomes full-text, word-wrapped, mouse-selectable; tree rows keep their elide (slot titles) but every leaf gets its full label as tooltip.

- [ ] **Step 1: Write the failing test**

```python
    def test_assign_dialog_shows_full_filename_unelided(self):
        from plex_renamer.app.models.state_models import EpisodeSlotChoice
        from plex_renamer.gui_qt.widgets.episode_assign_dialog import EpisodeAssignDialog

        long_name = "Show.Name.2020.S01E01.Absurdly.Long.Release.Tag.Chain.1080p.WEB-DL.DDP5.1.H.264-GROUP.mkv"
        dialog = EpisodeAssignDialog(
            slots=[EpisodeSlotChoice(season=1, episode=1, title="One")],
            file_label=long_name,
        )
        label = dialog._file_label
        self.assertEqual(label.text(), long_name)      # no "…" elision
        self.assertTrue(label.wordWrap())
        dialog.close()
```

- [ ] **Step 2: Run to verify FAIL** (`AttributeError: _file_label` / elided text mismatch).

- [ ] **Step 3: Implement** — replace `_file_name_label` and keep a named attribute:

```python
def _file_name_label(file_label: str, parent) -> QLabel:
    label = QLabel(file_label, parent)
    label.setProperty("cssClass", "caption")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
```

In `__init__`, assign it: `self._file_label = _file_name_label(file_label, self); layout.addWidget(self._file_label)` (replacing the unnamed local). Both trees already tooltip their leaves with the full label (`episode_assign_dialog.py:140` and `:291`) — no leaf changes needed; the elided header label (old `metrics.elidedText` at line ~64) was the only truncation site.

- [ ] **Step 4: PASS**, **Step 5: Suites + commit**

```bash
git add plex_renamer/gui_qt/widgets/episode_assign_dialog.py tests/test_qt_media_workspace.py
git commit -m "feat(gui): assign dialog shows full filenames - wrapped, selectable, tooltipped"
```

---

### Task 7: Verification + bookkeeping (controller)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass, zero new skips; skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: Visual sanity** — throwaway offscreen grab test (Plan 3 pattern; set `QT_QPA_FONTDIR=C:\Windows\Fonts` so text renders). Build a table-backed TV state (5 slots, one pre-claimed, three unassigned files), `MediaWorkPanel` at 1000×700, `enter_bulk_assign` + `bulk_panel.show_state`, stage via `auto_map_remaining`, grab: two panes with sorted files (staged rows accent + `→` markers), season-grouped slots showing claimed/staged/missing colors, button row with Apply enabled, danger-outline Unassign All + ⋯ overflow visible in the toolbar behind the stack (grab the table page too for the hint row: problems filter with only-unmapped state). Verify widget parentage pitfalls per Plan 3's lessons (any persistent-editor-style hosting must live inside the panel window). Delete the throwaway test after inspection.

- [ ] **Step 3: Update roadmap + handoff, commit** — roadmap row 4 → Landed (commit range); handoff status/current + "next step: write Plan 5 (async + perf, spec §7)" + session log entry.

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 4 landed; next up plan 5 (async + perf)"
```

---

## Self-review notes (kept for the record)

- **Spec §6 coverage:** three entry points (overflow Task 3, post-Unassign-All offer Task 4, Problems empty-state hint Task 5); two-pane surface inside the work panel (Task 2 + Task 3 stack); check-N-files + click-starting-slot + Assign-in-order with contiguity handled by walking free slots (engine's per-assignment contiguity untouched — each bulk pair is a single-episode run, so `table.assign` validation cannot reject on contiguity, only on unknown slots); Auto-map remaining with staging-as-preview; drag one-off pairs (claimed slots rejected — displacement stays a deliberate single-row act); nothing → controller until Apply = one `apply_assignments` + one refresh + one `toast_requested`; Cancel discards; movie hidden (Tasks 3/5 guards); Unassign All danger-outline + physical `px(24)` separation + exact-count confirm + offer (Tasks 3–4); single-row dialogs gain full-filename display (Task 6). §15.7 MVP boundary respected: no in-mode undo (Reset/Cancel only).
- **Deliberate scope choices:** `unassign_all` becomes one service call (same mutation, one reproject) — outcome-identical to the old N-loop and prerequisite for an honest exact-count confirm; toast delivery = new `toast_requested` signal → existing `ToastManager` (statusBar `status_message` stays for low-key messages; Plan 6 restyles toast visuals); shift-range check lives in the files view (Qt has no native range-check); staged preview = in-place `→` markers rather than a separate preview dialog (spec's "preview before apply" reading — the surface IS the preview); `QMessageBox.question`-shim contract keeps the injectable-box test pattern from `handle_episode_row_action`.
- **Type consistency check:** `apply_assignments(state, pairs) -> (applied, skipped)` used identically in Tasks 1/4; pair tuples `(file_id, season, episode)` everywhere (`staged_pairs`, `apply_requested`, service); `bulk_assign_requested`/`apply_requested`/`cancelled` names match Tasks 2/3/4/5 wiring; `bulk_panel`/`overflow_button`/`enter_bulk_assign`/`exit_bulk_assign`/`bulk_assign_active` match Tasks 3/4 usage; `EpisodeSlotChoice.label` drives slot display text (Task 2) consistent with `state_models.py`; runner-list edits named in Task 2 only (the single new Qt test file).
