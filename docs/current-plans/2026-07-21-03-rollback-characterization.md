# Rollback Characterization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the externally visible `revert_job` recovery contract before structural extraction.

**Architecture:** Add a focused matrix test module around the public function, real temporary trees, and synthetic undo logs. Cover rename/remux/decorate operations, reverse ordering, boundary refusal, missing inputs, and partial failure. This plan changes production behavior only if a test exposes a safety violation; otherwise it is test-only.

**Tech Stack:** Python 3.14, pathlib/shutil, pytest fixtures and monkeypatch.

## Global Constraints

- Characterize `ARCH-002` before moving any production code.
- Never use real library paths; every filesystem case uses `tmp_path`.
- Boundary violations must be refused without touching the outside path.
- Preserve `revert_job(job) -> tuple[bool, list[str]]`.
- Any correctness fix discovered here receives its own RED/GREEN commit before extraction.

---

### Task 1: Cover entry guards and remux/decorate deletion order

**Files:**
- Create: `tests/test_job_revert_characterization.py`
- Read: `tests/test_remux_revert.py`
- Read: `tests/test_executor_metadata_integration.py`

**Interfaces:**
- Consumes: `revert_job(job: RenameJob) -> tuple[bool, list[str]]`
- Produces: `_job(tmp_path, *, undo, output=True, kind=JobKind.RENAME) -> RenameJob`

- [ ] **Step 0: Add the shared job builder**

```python
def _job(
    tmp_path: Path,
    *,
    undo: dict[str, object] | None,
    output: bool = True,
    kind: str = JobKind.RENAME,
) -> RenameJob:
    library_root = tmp_path / "library"
    library_root.mkdir(exist_ok=True)
    output_root = tmp_path / "output"
    if output:
        output_root.mkdir(exist_ok=True)
    return RenameJob(
        media_type="tv",
        tmdb_id=1,
        media_name="Show",
        library_root=str(library_root),
        output_root=str(output_root) if output else None,
        source_folder="Show",
        job_kind=kind,
        undo_data=undo,
    )
```

- [ ] **Step 1: Write the guard and deletion-order tests**

```python
def test_no_undo_data_is_rejected_without_touching_files(tmp_path: Path) -> None:
    marker = tmp_path / "out" / "marker.mkv"
    marker.parent.mkdir()
    marker.write_bytes(b"keep")
    ok, errors = revert_job(_job(tmp_path, undo=None))
    assert ok is False
    assert errors == ["No undo data stored for this job."]
    assert marker.read_bytes() == b"keep"


def test_created_sidecars_and_remux_outputs_are_removed_before_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    source = tmp_path / "library" / "Show" / "episode.mkv"
    destination = tmp_path / "output" / "Show" / "renamed.mkv"
    sidecar = destination.with_suffix(".nfo")
    remux = destination.with_name("remuxed.mkv")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"video")
    sidecar.write_text("metadata", encoding="utf-8")
    remux.write_bytes(b"remux")

    original_unlink = Path.unlink
    original_move = shutil.move

    def recording_unlink(path: Path, missing_ok: bool = False) -> None:
        if path.is_relative_to(tmp_path):
            events.append(f"unlink:{path.name}")
        original_unlink(path, missing_ok=missing_ok)

    def recording_move(src: str, dst: str, copy_function=shutil.copy2) -> str:
        src_path = Path(src)
        if src_path.is_relative_to(tmp_path):
            events.append(f"move:{src_path.name}")
        return original_move(src, dst, copy_function=copy_function)

    monkeypatch.setattr(Path, "unlink", recording_unlink)
    monkeypatch.setattr(shutil, "move", recording_move)
    undo = {
        "remux_outputs": [str(remux)],
        "created_files": [str(sidecar)],
        "renames": [{"new": str(destination), "old": str(source)}],
    }
    ok, errors = revert_job(_job(tmp_path, undo=undo, output=True))

    assert ok, errors
    assert events == ["unlink:remuxed.mkv", "unlink:renamed.nfo", "move:renamed.mkv"]
    assert source.read_bytes() == b"video"
    assert not sidecar.exists()
    assert not remux.exists()
```

- [ ] **Step 2: Run the new module**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py -q`
Expected: PASS against current behavior; if order differs, stop and record the actual safety implication before changing production.

- [ ] **Step 3: Add irreversible and missing-output cases to the same matrix**

```python
@pytest.mark.parametrize("irreversible", [True, 1])
def test_irreversible_undo_never_mutates_tree(tmp_path: Path, irreversible: object) -> None:
    output = tmp_path / "out" / "result.mkv"
    output.parent.mkdir()
    output.write_bytes(b"muxed")
    ok, errors = revert_job(
        _job(tmp_path, undo={"irreversible": irreversible, "remux_outputs": [str(output)]})
    )
    assert not ok
    assert "cannot be reverted" in errors[0]
    assert output.exists()
```

- [ ] **Step 4: Run focused regression tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py tests\test_remux_revert.py tests\test_executor_metadata_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_job_revert_characterization.py
git commit -m "test: characterize rollback entry and deletion order"
```

### Task 2: Cover rename, directory restoration, and cleanup boundaries

**Files:**
- Modify: `tests/test_job_revert_characterization.py`

- [ ] **Step 1: Add a table of same-folder and cross-folder rename reversals**

```python
@pytest.mark.parametrize("cross_folder", [False, True])
def test_revert_moves_files_back_and_removes_only_empty_created_dirs(
    tmp_path: Path, cross_folder: bool
) -> None:
    source = tmp_path / "lib" / "Show" / "episode.mkv"
    destination_dir = tmp_path / "out" / "Show" if cross_folder else source.parent
    destination = destination_dir / "renamed.mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"video")
    keep = destination_dir / "keep.txt"
    keep.write_text("keep", encoding="utf-8")
    undo = {
        "renames": [{"new": str(destination), "old": str(source)}],
        "created_dirs": [str(destination_dir)],
        "removed_dirs": [],
        "renamed_dirs": [],
    }
    ok, errors = revert_job(_job(tmp_path, undo=undo, output=cross_folder))
    assert ok, errors
    assert source.read_bytes() == b"video"
    assert keep.exists()
    assert destination_dir.exists()
```

- [ ] **Step 2: Add reverse directory-rename and removed-directory recreation tests**

Build two nested `renamed_dirs` entries and assert reverse replay restores the original tree before file moves. Add one `removed_dirs` entry and assert it exists after revert.

- [ ] **Step 3: Run and confirm the characterization**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_job_revert_characterization.py
git commit -m "test: characterize rollback tree restoration"
```

### Task 3: Cover boundary attacks and partial failures

**Files:**
- Modify: `tests/test_job_revert_characterization.py`
- Modify only if RED exposes unsafe mutation: `plex_renamer/job_executor.py:487-654`

- [ ] **Step 1: Add outside-output and outside-source refusal tests**

```python
def test_revert_refuses_paths_outside_both_boundaries(tmp_path: Path) -> None:
    outside_output = tmp_path / "outside-output.mkv"
    outside_source = tmp_path / "outside-source.mkv"
    outside_output.write_bytes(b"keep")
    undo = {"renames": [{"new": str(outside_output), "old": str(outside_source)}]}
    ok, errors = revert_job(_job(tmp_path, undo=undo, output=True))
    assert not ok
    assert any("outside the output root" in error for error in errors)
    assert any("outside the source root" in error for error in errors)
    assert outside_output.read_bytes() == b"keep"
    assert not outside_source.exists()
```

- [ ] **Step 2: Add partial unlink/move failure tests**

Monkeypatch only the targeted `Path.unlink` or `shutil.move` call to raise `OSError("denied")`. Assert later independent undo entries still run, the returned error contains the failing basename, and `ok` is false.

- [ ] **Step 3: Run RED/GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py -q`
Expected: PASS. If any safety test fails, make the smallest fix in `job_executor.py`, rerun to GREEN, and commit that fix separately as `fix: preserve rollback boundaries`.

- [ ] **Step 4: Run all revert-related tests and quality tools**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_revert_characterization.py tests\test_remux_revert.py tests\test_executor_metadata_integration.py tests\test_scan_improvements.py -q`
Expected: PASS.

Run: `.venv\Scripts\ruff.exe format tests\test_job_revert_characterization.py plex_renamer\job_executor.py && .venv\Scripts\ruff.exe check tests\test_job_revert_characterization.py plex_renamer\job_executor.py && .venv\Scripts\pyright.exe tests\test_job_revert_characterization.py plex_renamer\job_executor.py`
Expected: all commands exit 0; the new test is strict-clean.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_job_revert_characterization.py
git commit -m "test: characterize rollback failures and boundaries"
```
