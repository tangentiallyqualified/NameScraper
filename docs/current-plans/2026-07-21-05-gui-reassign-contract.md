# GUI Reassign Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore an end-to-end behavioral contract for episode-row reassignment in the current Qt workspace.

**Architecture:** Drive the live expansion-card button, substitute a deterministic assignment dialog, and assert state mutation, projection refresh, visible row data, and emitted status. Add a negative control that disconnects dispatch so the test proves it is not merely inspecting the dialog or service directly. Do not refactor the coordinator ahead of V5.

**Tech Stack:** Python 3.14, PySide6, unittest/pytest, existing Qt smoke harness.

## Global Constraints

- Implement `GUI-001` only; keep `ARCH-003` deferred for V5.
- Test through the live `MediaWorkspace` signal path and visible table model.
- Do not add production hooks solely for the test.
- Preserve current copy, layout, and action placement.
- Run through `scripts/test-smoke.cmd` at compartment closeout.

---

### Task 1: Assert reassign dispatch, state mutation, and visible reprojection

**Files:**
- Modify: `tests/test_qt_media_workspace_review_actions.py:186-231`
- Read: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py:346-421`

**Interfaces:**
- Consumes: expansion-card `QPushButton` with `actionId == "reassign"`
- Consumes: `EpisodeAssignDialog.pick_episodes(...) -> list[tuple[int, int]] | None`
- Observes: `PreviewItem.season`, `PreviewItem.episodes`, model row data, and `status_message`.

- [ ] **Step 1: Replace the TODO-only assertion with a failing live action test**

```python
messages: list[tuple[str, int]] = []
workspace.status_message.connect(lambda text, timeout: messages.append((text, timeout)))
button = _card_action_button(card, "reassign")
self.assertIsNotNone(button)

with patch.object(
    EpisodeAssignDialog,
    "pick_episodes",
    return_value=[(1, 2)],
) as pick:
    button.click()
    self._app.processEvents()

pick.assert_called_once()
self.assertEqual(review_item.season, 1)
self.assertEqual(review_item.episodes, [2])
self.assertIn(("Episode mapping updated.", 3000), messages)
```

After the click, locate the row again from `panel.model.row_for_preview_index(0)` and assert its row data shows episode 2 and no stale episode-1 target.

- [ ] **Step 2: Run the single test and confirm RED or current wiring**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace_review_actions.py::QtMediaWorkspaceReviewActionsTests::test_media_workspace_review_episode_fix_button_replaced_by_actions_menu -q`
Expected: the new discriminating assertions either PASS on current wiring or expose the missing dispatch/refresh path. If RED, proceed to Step 3; if already GREEN, skip production changes.

- [ ] **Step 3: Make the smallest wiring fix if the live button does not reach the coordinator**

The intended connection is:

```python
card.action_requested.connect(
    lambda action_id, state=state, row=row: self._action_coordinator.handle_episode_row_action(
        state, row, action_id
    )
)
```

Place the connection in the existing card construction/refresh path, not in the test. Reuse the existing coordinator instance.

- [ ] **Step 4: Run the review-action module**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace_review_actions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_qt_media_workspace_review_actions.py plex_renamer/gui_qt/widgets/_media_workspace_refresh.py
git commit -m "test: restore live episode reassign contract"
```

Stage only the production path actually changed; omit it when the current wiring already passes.

### Task 2: Add a negative control for dispatch and refresh

**Files:**
- Modify: `tests/test_qt_media_workspace_review_actions.py`

- [ ] **Step 1: Prove the assertion fails when the service dispatch is disconnected**

Add a test that patches `EpisodeMappingService.assign_file` to a no-op, clicks the same live button, and asserts the preview remains on episode 1 and no success status is emitted. Then add a positive spy assertion to the main test:

```python
with patch.object(
    EpisodeMappingService,
    "assign_file",
    autospec=True,
    wraps=EpisodeMappingService.assign_file,
) as assign:
    button.click()
    self._app.processEvents()
assign.assert_called_once()
```

If `wraps` conflicts with the descriptor, use a local recording wrapper that calls the saved unbound method; do not replace the assertion with a private coordinator call.

- [ ] **Step 2: Run both tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace_review_actions.py -q`
Expected: PASS; the negative control demonstrates state/visible assertions depend on actual dispatch.

- [ ] **Step 3: Run Qt workspace regressions and smoke**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py tests\test_qt_media_workspace_review_actions.py tests\test_episode_mapping_projection.py -q`
Expected: PASS.

Run: `scripts\test-smoke.cmd`
Expected: all smoke tests pass.

- [ ] **Step 4: Run formatting and type checks**

Run: `.venv\Scripts\ruff.exe format tests\test_qt_media_workspace_review_actions.py && .venv\Scripts\ruff.exe check tests\test_qt_media_workspace_review_actions.py && .venv\Scripts\pyright.exe tests\test_qt_media_workspace_review_actions.py`
Expected: no new findings; existing findings are addressed by the adjacent typing plan rather than suppressed.

- [ ] **Step 5: Close `GUI-001` and commit**

Remove `GUI-001` from `docs/deferred-work.md` and its P1 summary. Keep `ARCH-003` active with its V5/defer rationale.

```powershell
git add tests/test_qt_media_workspace_review_actions.py docs/deferred-work.md
git commit -m "docs: close episode reassign coverage debt"
```
