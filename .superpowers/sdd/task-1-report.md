# Task 1 report — live episode reassign contract

## Result

Implemented GUI-001 as a characterization test only. Production wiring was
already present: the expansion card's `action_requested` signal dispatches to
`MediaWorkspaceActionCoordinator.handle_episode_row_action`. No production
files changed.

## Changes

- Replaced the TODO-only review-row test with a live `Reassign...` expansion
  card click.
- Used the established table-backed scanned-TV fixture pattern:
  `EpisodeAssignmentTable`, two slots, one auto-assigned scanned file, and
  `project_preview_items`.
- Patched `EpisodeAssignDialog.pick_episodes` to return exactly `[(1, 2)]`.
- Asserted dispatch, the reprojected preview's season/episode values, the
  `("Episode mapping updated.", 3000)` status message, and the refreshed
  model row's E02 target with no stale E01 target.

## TDD / investigation evidence

1. The first assertion-only version used the previous hand-built
   `PreviewItem` fixture. The required live test did not complete because the
   action coordinator caught `ValueError` at
   `_media_workspace_actions.py:512` and opened its warning modal. A
   faulthandler run consistently captured the stack:
   `button.click` -> expansion card `action_requested` -> state-coordinator
   lambda -> `handle_episode_row_action` -> warning path.
2. A nearby working live action test,
   `test_media_workspace_approve_all_review_episodes_is_inline_with_filters`,
   passed in 0.78s. This ruled out general Qt/button test infrastructure.
3. The initial fixture had neither an assignment table nor a scanned file ID;
   `EpisodeMappingService.episode_slot_choices` therefore raised before the
   dialog. A temporary warning-recorder diagnostic showed the intended dialog
   mock was called zero times, confirming that the test data—not card
   dispatch—was the missing behavior.
4. After switching to the existing table-backed fixture pattern, the dialog
   dispatch occurred. The next RED result showed that reprojecting replaces
   the `PreviewItem` list, so the pre-action object remained E01. The final
   test deliberately observes the reprojected item with the same `file_id`,
   then checks the visible model row. This is the actual state contract.
5. The final required test passed without production changes, confirming the
   existing live card signal wiring is correct.

## Commands and results

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m pytest 'tests\test_qt_media_workspace_review_actions.py::QtMediaWorkspaceReviewActionsTests::test_media_workspace_review_episode_fix_button_replaced_by_actions_menu' -q
```

Final result: `1 passed in 0.78s`.

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m pytest 'tests\test_qt_media_workspace_review_actions.py' -q
```

Result: `10 passed in 1.54s`.

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\ruff.exe' check 'tests\test_qt_media_workspace_review_actions.py'
git diff --check
```

Result: `All checks passed!`; diff check clean.

## Files changed

- `tests/test_qt_media_workspace_review_actions.py`
- `.superpowers/sdd/task-1-report.md`

## Self-review

- Uses the actual expansion-card button and public visible table model; no
  test-only production hook was added.
- Keeps copy, layout, and action placement unchanged.
- Keeps ARCH-003/refactoring out of scope.
- Stages only the task test and report; no production file is staged.

## Concerns

- None. The only investigation residue was orphaned diagnostic pytest
  processes; the four processes created by this task were verified by
  interpreter path/start time and terminated before completion.
