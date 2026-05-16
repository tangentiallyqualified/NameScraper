# Batch Action Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make batch-level actions match user intent: approve all TV review episodes and the show together, promote duplicates intentionally, and remove movie checkboxes that imply unsupported per-file selection.

**Architecture:** Keep all state transitions in controller/action helpers, then let roster grouping refresh from canonical state. Add explicit primary selection state so duplicate recomputation cannot undo a user’s Make Primary choice.

**Tech Stack:** Python, PySide6, existing `ScanState`, `BatchTVOrchestrator`, `CommandGatingService`, pytest.

---

## File Structure

- Modify `plex_renamer/engine/models.py`: add manual duplicate priority marker.
- Modify `plex_renamer/engine/_batch_tv_duplicates.py`: honor manual primary marker.
- Modify `plex_renamer/app/controllers/_match_state_helpers.py`: add primary promotion helper.
- Modify `plex_renamer/app/controllers/media_controller.py`: expose `make_primary()`.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_action_state.py`: add Make Primary button state.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py`: enable new primary actions before queue eligibility gates run.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`: implement Approve All and Make Primary actions.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`: remove middle-panel TV Approve All button after moving action to detail panel.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_roster.py`: hide movie row check controls and select-all footer for movies.
- Modify `tests/test_command_gating_service.py`, `tests/test_qt_media_workspace.py`, and `tests/test_scan_improvements.py`.

### Task 1: Approve All As A Show-Level Action

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_action_state.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`

- [ ] **Step 1: Write failing workflow test**

Add a test with a TV state that has `confidence=0.6`, `match_origin="auto"`, and two episode review preview items. Assert the detail-panel primary action text is `Approve All`, click it, then assert:

```python
self.assertEqual([item.status for item in state.preview_items], ["OK", "OK"])
self.assertEqual(state.match_origin, "manual")
self.assertFalse(state.needs_review)
self.assertEqual(self._roster_section_for_state(workspace, state), "MATCHED")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_tv_workspace_approve_all_approves_episodes_and_show_match -q
```

Expected: fails because Approve All is still in the preview header and does not approve the show match.

- [ ] **Step 3: Implement action-label state**

In `_media_workspace_action_state.py`, add:

```python
def can_inline_approve_all(state: ScanState) -> bool:
    return (
        state.show_id is not None
        and not state.queued
        and not state.scanning
        and state.duplicate_of is None
        and any(item.is_episode_review for item in state.preview_items)
    )
```

Return `Approve All` from `primary_action_label()` before `can_inline_approve()`.

Update the action-bar enablement path so the detail-panel primary button is enabled when `can_inline_approve_all(state)` is true. This must run before the normal queue-eligibility fallback, otherwise the button can display `Approve All` while remaining disabled.

- [ ] **Step 4: Implement approve-all transition**

In `activate_selected_primary_action()`, route `can_inline_approve_all(state)` to:

```python
workspace._approve_all_episode_mappings()
```

Change `approve_all_episode_mappings()` to also mark the show manual:

```python
state.match_origin = "manual"
workspace.refresh_from_controller()
```

- [ ] **Step 5: Remove preview-header approve-all button**

Delete `_approve_all_button` creation and visibility logic from `MediaWorkspacePreviewPanel`. Keep episode filters in the preview header.

- [ ] **Step 6: Run focused test**

Run the same pytest command. Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py plex_renamer/gui_qt/widgets/_media_workspace_action_state.py plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py
git commit -m "Make approve all approve the TV show"
```

### Task 2: Make Primary For Duplicate Shows

**Files:**
- Modify: `tests/test_scan_improvements.py`
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/engine/models.py`
- Modify: `plex_renamer/engine/_batch_tv_duplicates.py`
- Modify: `plex_renamer/app/controllers/_match_state_helpers.py`
- Modify: `plex_renamer/app/controllers/media_controller.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_action_state.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py`

- [ ] **Step 1: Write failing duplicate priority test**

Add a pure duplicate-label test with two states sharing a `show_id`. Set `duplicate_primary_rank=1` on the second state. Assert the second state is primary, the first is duplicate, the promoted state remains `checked=True`, and the demoted duplicate is `checked=False` after `apply_duplicate_labels(states)`.

- [ ] **Step 2: Add manual primary marker**

Add to `ScanState`:

```python
duplicate_primary_rank: int = 0
```

Update `duplicate_priority()` to sort `-state.duplicate_primary_rank` before confidence.

- [ ] **Step 3: Add controller helper**

Add:

```python
def promote_duplicate_primary(state: ScanState, states: list[ScanState]) -> None:
    if state.show_id is None:
        return
    for candidate in states:
        if candidate.show_id == state.show_id:
            candidate.duplicate_primary_rank = 0
    state.duplicate_primary_rank = 1
```

After calling it, re-run duplicate labeling through the batch orchestrator.

After duplicate labels are recomputed, explicitly restore the promoted state to `checked=True` and leave all other duplicate siblings unchecked. This prevents a promoted primary from visually staying disabled or unselected after the action.

- [ ] **Step 4: Add UI action**

Show primary action text `Make Primary` when:

```python
workspace._media_type == "tv"
and state.duplicate_of is not None
and state.show_id is not None
and not state.queued
and not state.scanning
```

Clicking it calls `media_ctrl.make_primary(state)`, refreshes, and restores selection.

Update `_media_workspace_action_bar.py` so `Make Primary` is enabled for duplicate TV states before queue gating is evaluated.

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest tests/test_scan_improvements.py::ScanImprovementTests::test_duplicate_resolution_honors_manual_primary tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_tv_duplicate_make_primary_promotes_selected_state -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/engine/models.py plex_renamer/engine/_batch_tv_duplicates.py plex_renamer/app/controllers/_match_state_helpers.py plex_renamer/app/controllers/media_controller.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py plex_renamer/gui_qt/widgets/_media_workspace_action_state.py plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py tests/test_scan_improvements.py tests/test_qt_media_workspace.py
git commit -m "Add make primary for duplicate TV shows"
```

### Task 3: Remove Movie Batch Checkboxes

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_roster.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py`

- [ ] **Step 1: Write failing movie checkbox test**

Add a movie workspace test that asserts:

```python
self.assertTrue(workspace._roster_master_check.isHidden())
self.assertTrue(workspace._preview_master_check.isHidden())
self.assertTrue(row_widget._check.isHidden())
self.assertTrue(row_widget._check_slot.isHidden())
self.assertTrue(preview_widget._check.isHidden())
self.assertFalse(workspace._roster_queue_btn.isVisible())
```

Also assert toggling any remaining master-check or keyboard selection path does not mutate movie `ScanState.checked`; movie batch selection should be driven by the active row/detail action, not hidden bulk selection state.

- [ ] **Step 2: Hide movie roster check controls**

In roster panel UI, hide the master check and selection summary when `media_type == "movie"`. Keep `Queue Checked` out of the visible layout for movie mode or rename it to the selected movie action through the detail panel only.

When constructing movie roster rows, collapse the `_check_slot` as well as hiding the switch so the old checkbox gutter does not leave dead space.

- [ ] **Step 3: Hide movie preview check controls**

Pass `checkable=False` for movie preview rows in `attach_preview_widget()`.

- [ ] **Step 4: Shift middle panel up**

When movie mode hides the preview master row, remove the header row spacing by hiding all header controls and not adding empty text.

- [ ] **Step 5: Run test**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_movie_workspace_hides_batch_checkboxes -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_roster.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py plex_renamer/gui_qt/widgets/_workspace_widgets.py plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py tests/test_qt_media_workspace.py
git commit -m "Remove movie batch checkboxes"
```
