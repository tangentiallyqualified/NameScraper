# Job Detail Test Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 81 Pyright findings in `test_qt_job_detail_panel.py` using typed preview data and concrete Qt widget narrowing.

**Architecture:** Keep structural data assertions on `JobPreviewGroup`/`JobPreviewRow` before rendering. For widget behavior, identify concrete tree items and preview widgets with runtime `isinstance` checks rather than treating `QWidget | None` as a private subclass. Expose no new GUI API solely for typing.

**Tech Stack:** Python 3.14, PySide6 tree widgets, dataclasses, Pyright, unittest.

## Global Constraints

- Do not redesign the panel ahead of V5.
- Prefer data-builder tests over private rendered-widget attribute access.
- No `cast(Any, widget)`, private-usage disables, or broad mocks.
- Preserve preview grouping, labels, tooltips, and expansion behavior.

---

### Task 1: Type structural preview-data assertions

**Files:**
- Modify: `tests/test_qt_job_detail_panel.py`
- Read: `plex_renamer/gui_qt/widgets/_job_detail_preview.py`

**Interfaces:**
- Consumes: `build_job_preview_entries(job) -> list[JobPreviewGroup | JobPreviewRow]`
- Uses: concrete `JobPreviewGroup.rows` and `JobPreviewRow.label` only after `isinstance`.

- [ ] **Step 1: Replace assumed union attributes with narrowing**

```python
entries = build_job_preview_entries(job)
group = entries[0]
self.assertIsInstance(group, JobPreviewGroup)
assert isinstance(group, JobPreviewGroup)
self.assertEqual(group.label, "Destination")
self.assertEqual([row.after for row in group.rows], [expected])
```

Apply the same pattern to every `rows`/`label` access; assert a `JobPreviewRow` where the builder returns a row.

- [ ] **Step 2: Run Pyright and data-builder tests**

Run: `.venv\Scripts\pyright.exe tests\test_qt_job_detail_panel.py`
Expected: all `JobPreviewRow`/`JobPreviewGroup` attribute findings are removed.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_job_detail_panel.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_qt_job_detail_panel.py
git commit -m "types: narrow job preview data unions"
```

### Task 2: Narrow tree items and rendered preview widgets

**Files:**
- Modify: `tests/test_qt_job_detail_panel.py`
- Read: `plex_renamer/gui_qt/widgets/job_detail_panel.py`

- [ ] **Step 1: Assert optional tree items before Qt calls**

```python
item = panel._preview_tree.topLevelItem(0)
self.assertIsNotNone(item)
assert item is not None
panel._on_preview_item_clicked(item, 0)
```

Use this pattern for all six `QTreeWidgetItem | None` argument errors and every optional child access.

- [ ] **Step 2: Assert the concrete preview widget before behavior checks**

```python
widget = panel._preview_tree.itemWidget(item, 0)
self.assertIsInstance(widget, _RenamePreviewWidget)
assert isinstance(widget, _RenamePreviewWidget)
self.assertEqual(widget._after.text(), expected_after)
```

If importing `_RenamePreviewWidget` causes a private-usage finding, add a public test-facing predicate/accessor on `JobDetailPanel` only if it is also useful to V5 migration; otherwise assert through public child `QLabel` text/object properties and data-builder tests.

- [ ] **Step 3: Run the module and Pyright to zero**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_job_detail_panel.py -q`
Expected: PASS.

Run: `.venv\Scripts\pyright.exe tests\test_qt_job_detail_panel.py`
Expected: 0 errors.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_qt_job_detail_panel.py plex_renamer/gui_qt/widgets/job_detail_panel.py
git commit -m "types: narrow job detail Qt widgets"
```

Stage the production file only if a durable public accessor was justified.

### Task 3: Regressions, smoke, and baseline pruning

**Files:**
- Modify prune-only: `scripts/audit/quality-baseline.json`

- [ ] **Step 1: Run related detail/history tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_job_detail_panel.py tests\test_qt_queue_history.py tests\test_job_preview_grouping.py -q`
Expected: PASS.

- [ ] **Step 2: Format, smoke, and prune**

Run: `.venv\Scripts\ruff.exe format tests\test_qt_job_detail_panel.py plex_renamer\gui_qt\widgets\job_detail_panel.py && .venv\Scripts\ruff.exe check tests\test_qt_job_detail_panel.py plex_renamer\gui_qt\widgets\job_detail_panel.py`
Expected: exit 0.

Run: `scripts\test-smoke.cmd`
Expected: PASS.

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: prune-only exit 0; 81 findings and the legacy entry are removed.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_qt_job_detail_panel.py scripts/audit/quality-baseline.json
git commit -m "types: enroll job detail tests at strict"
```
