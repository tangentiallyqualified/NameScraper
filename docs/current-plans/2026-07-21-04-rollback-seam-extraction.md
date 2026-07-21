# Rollback Seam Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `revert_job` complexity by moving cohesive undo operations behind typed, behavior-preserving helpers.

**Architecture:** Create `_job_revert.py` with a `RevertContext` and small handlers for generated-file deletion, directory reversal, file reversal, and cleanup. Keep `job_executor.revert_job` as the public compatibility import and thin orchestration entry. Preserve exact operation order and error strings locked by the characterization plan.

**Tech Stack:** Python 3.14, dataclasses, pathlib/shutil, pytest.

## Global Constraints

- Execute only after `2026-07-21-03-rollback-characterization.md` is green.
- This plan is behavior-preserving; no new job kinds or undo schema fields.
- Preserve deletion -> directory rename -> directory recreation -> file move -> cleanup order.
- Preserve `revert_job(job) -> tuple[bool, list[str]]` and existing import paths.
- Do not weaken filesystem boundary checks.

---

### Task 1: Extract context and path validation

**Files:**
- Create: `plex_renamer/_job_revert.py`
- Modify: `plex_renamer/job_executor.py:439-515`
- Test: `tests/test_job_revert_characterization.py`

**Interfaces:**
- Produces: `@dataclass(slots=True) class RevertContext`
- Produces: `destination_path_errors(...) -> list[str]`

- [ ] **Step 1: Add a direct helper test for both boundary errors**

```python
def test_destination_path_errors_reports_both_boundaries(tmp_path: Path) -> None:
    errors = destination_path_errors(
        new_path=tmp_path / "outside-new",
        old_path=tmp_path / "outside-old",
        output_boundary=tmp_path / "out",
        source_boundary=tmp_path / "lib",
    )
    assert errors == [
        f"Revert source is outside the output root: {tmp_path / 'outside-new'}",
        f"Revert target is outside the source root: {tmp_path / 'outside-old'}",
    ]
```

- [ ] **Step 2: Run the helper test and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py -q`
Expected: import/collection FAIL because `_job_revert` does not exist.

- [ ] **Step 3: Create the typed context and move validation unchanged**

```python
@dataclass(slots=True)
class RevertContext:
    job: RenameJob
    undo: dict[str, Any]
    library_root: Path
    source_boundary: Path
    output_boundary: Path | None
    cleanup_boundary: Path
    errors: list[str] = field(default_factory=list)
    moved_from_paths: list[Path] = field(default_factory=list)
    dir_rename_map: dict[Path, Path] = field(default_factory=dict)
```

Move `_destination_revert_path_errors` as `destination_path_errors` without changing messages or exception handling.

- [ ] **Step 4: Run characterization and quality checks**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py tests\test_remux_revert.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/_job_revert.py plex_renamer/job_executor.py tests/test_job_revert_characterization.py
git commit -m "refactor: extract rollback context"
```

### Task 2: Extract generated-file and directory handlers

**Files:**
- Modify: `plex_renamer/_job_revert.py`
- Modify: `plex_renamer/job_executor.py:515-586`

**Interfaces:**
- Produces: `remove_generated_outputs(context) -> None`
- Produces: `restore_directories(context) -> None`

- [ ] **Step 1: Add direct order assertions around the two handlers**

Use the characterization event recorder to call both handlers and assert remux outputs and created files are deleted before reversed directory renames; the final tree and errors must match the public call.

- [ ] **Step 2: Move the loops into named helpers**

```python
def remove_generated_outputs(context: RevertContext) -> None:
    _remove_paths(
        context,
        context.undo.get("remux_outputs", []),
        outside_message="Remux output is outside the output root",
        failure_label="Could not remove remux output",
    )
    _remove_paths(
        context,
        context.undo.get("created_files", []),
        outside_message="Created file is outside the output root",
        failure_label="Could not remove metadata file",
    )
```

`restore_directories` must reverse `renamed_dirs`, populate `dir_rename_map`, then recreate `removed_dirs`, exactly matching current order.

- [ ] **Step 3: Run all rollback tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py tests\test_remux_revert.py tests\test_executor_metadata_integration.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add plex_renamer/_job_revert.py plex_renamer/job_executor.py
git commit -m "refactor: extract rollback output handlers"
```

### Task 3: Extract file restoration and cleanup

**Files:**
- Modify: `plex_renamer/_job_revert.py`
- Modify: `plex_renamer/job_executor.py:586-654`

**Interfaces:**
- Produces: `restore_files(context) -> None`
- Produces: `cleanup_reverted_tree(context) -> None`
- Produces: `_job_revert.revert_job(job) -> tuple[bool, list[str]]`

- [ ] **Step 1: Move path remapping into a pure helper with tests**

```python
def remap_after_directory_revert(path: Path, mapping: dict[Path, Path]) -> Path:
    for renamed_new, renamed_old in mapping.items():
        try:
            return renamed_old / path.relative_to(renamed_new)
        except ValueError:
            continue
    return path
```

Test unchanged paths and nested remapped paths directly.

- [ ] **Step 2: Move file reversal and both cleanup branches**

Keep `shutil.move` for cross-directory moves and `Path.rename` for same-directory moves. Keep destination-output cleanup bounded by `output_root`; keep legacy non-output cleanup bounded by `cleanup_boundary`.

- [ ] **Step 3: Replace the public implementation with a compatibility re-export**

```python
from ._job_revert import revert_job as revert_job
```

Remove the old helper/implementation block from `job_executor.py`; do not wrap or change its signature.

- [ ] **Step 4: Run regression and complexity checks**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py tests\test_remux_revert.py tests\test_executor_metadata_integration.py tests\test_queue_executor_progress.py -q`
Expected: PASS.

Run: `.venv\Scripts\ruff.exe format plex_renamer\_job_revert.py plex_renamer\job_executor.py tests\test_job_revert_characterization.py && .venv\Scripts\ruff.exe check plex_renamer\_job_revert.py plex_renamer\job_executor.py tests\test_job_revert_characterization.py && .venv\Scripts\pyright.exe plex_renamer\_job_revert.py plex_renamer\job_executor.py tests\test_job_revert_characterization.py`
Expected: all commands exit 0; `revert_job` is absent from the legacy complexity baseline or has materially lower complexity.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/_job_revert.py plex_renamer/job_executor.py tests/test_job_revert_characterization.py
git commit -m "refactor: isolate rollback operations"
```

### Task 4: Prune baselines and close `ARCH-002`

**Files:**
- Modify: `docs/deferred-work.md`
- Modify through approved prune-only command: `scripts/audit/quality-baseline.json`

- [ ] **Step 1: Run focused tests and confirm no enlarged debt**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py tests\test_remux_revert.py tests\test_executor_metadata_integration.py -q`
Expected: PASS.

- [ ] **Step 2: Remove `ARCH-002` and refresh only stale baseline entries**

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: exit 0 without `--accept-enlarged`; only stale/pruned entries change.

- [ ] **Step 3: Commit the closeout**

```powershell
git add docs/deferred-work.md scripts/audit/quality-baseline.json
git commit -m "chore: close rollback architecture debt"
```
