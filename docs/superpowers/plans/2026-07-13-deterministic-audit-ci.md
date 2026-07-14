# Deterministic Audit and CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make audit generation byte-deterministic, non-mutating to verify, neutrally named, and runnable on pull requests or manual CI dispatch without an LLM.

**Architecture:** A stable SHA-256 digest of sorted audit-input paths and bytes replaces commit/time provenance in committed artifacts. The existing staged analyzer remains intact; a snapshot/restore verification wrapper runs it and compares generated output, while renderers write a neutral `code-index` view.

**Tech Stack:** Python 3.11+, pytest, PowerShell wrappers, GitHub Actions YAML, existing Ruff/Vulture/Radon audit stages.

## Global Constraints

- Identical audit inputs must produce byte-identical committed files.
- Generated outputs must contain no wall-clock timestamp and no current-HEAD provenance.
- Generated files are excluded from `input_digest`.
- `audit --verify` must restore every pre-run generated file byte-for-byte, including on pipeline failure.
- `.audit/` remains an ignored stage cache and may change during verification.
- No LLM, network call, or generated prose is required.
- CI must not push commits or require write credentials.
- Existing fast-test behavior remains unchanged in this plan.

---

### Task 1: Add stable audit-input fingerprints

**Files:**
- Modify: `scripts/audit/_artifacts.py`
- Modify: `scripts/audit/__main__.py`
- Modify: `tests/audit/test_artifacts.py`
- Modify: `tests/audit/test_main.py`

**Interfaces:**
- Produces: `input_files(repo_root: Path) -> list[Path]`
- Produces: `input_digest(repo_root: Path) -> str`
- Produces: `AUDIT_INPUT_PATTERNS: tuple[str, ...]`
- `check_lines()` consumes the baseline `input_digest` instead of commit distance.

- [ ] **Step 1: Write failing digest tests**

Add tests proving sorted-path stability, byte-change sensitivity, generated-output exclusion, and path-name sensitivity:

```python
def test_input_digest_is_stable_and_excludes_generated_docs(tmp_path):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)
    (repo / "docs/audit/maps/overview.md").write_text("generated change", encoding="utf-8")
    assert _artifacts.input_digest(repo) == first


def test_input_digest_changes_when_source_or_policy_changes(tmp_path):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)
    (repo / "plex_renamer/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert _artifacts.input_digest(repo) != first
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_artifacts.py tests\audit\test_main.py -q`

Expected: failures report missing `input_digest` and commit-based staleness behavior.

- [ ] **Step 3: Implement deterministic input discovery and hashing**

Use a single tuple covering Python source, audit/test harness inputs,
`pyproject.toml`, and `docs/audit/doc-ledger.toml`. Walk paths with `Path.rglob`,
exclude `.git`, `.venv`, `.worktrees`, `.audit`, caches, and all generated
`docs/audit` paths except the ledger. Hash each POSIX relative path, a NUL byte,
its bytes, and another NUL byte in sorted order:

```python
def input_digest(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in input_files(repo_root):
        rel = path.relative_to(repo_root).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
```

Update `check_lines()` to return current/stale status by comparing this value to
`baseline.json["input_digest"]`. A legacy baseline without the field is stale
with the instruction to regenerate.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_artifacts.py tests\audit\test_main.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/audit/_artifacts.py scripts/audit/__main__.py tests/audit/test_artifacts.py tests/audit/test_main.py
git commit -m "feat(audit): fingerprint deterministic inputs"
```

---

### Task 2: Remove self-referential provenance and make history idempotent

**Files:**
- Modify: `scripts/audit/_artifacts.py`
- Modify: `scripts/audit/_coverage.py`
- Modify: `scripts/audit/_metrics.py`
- Modify: `scripts/audit/_diff.py`
- Modify: `scripts/audit/_docs_ledger.py`
- Modify: `scripts/audit/_render_human.py`
- Modify: `scripts/audit/_render_llm.py`
- Modify: `tests/audit/test_diff.py`
- Modify: `tests/audit/test_coverage.py`
- Modify: `tests/audit/test_render_human.py`
- Modify: `tests/audit/test_render_llm.py`
- Modify: `tests/audit/test_docs_ledger.py`
- Modify: `scripts/test_fast_runner.py`

**Interfaces:**
- Every stage artifact may retain transient `commit`/`generated_at` fields in ignored `.audit/`, but committed outputs consume `input_digest` only.
- `metrics["input_digest"]` is the canonical render provenance.
- `baseline.json` contains `input_digest`, `previous_baseline`, and current metrics; it omits `generated_at`, `commit`, and commit-age fields.
- Coverage metadata records `input_digest`; committed coverage status is digest matched/mismatched, never commit aged.

- [ ] **Step 1: Write failing deterministic-output tests**

Add assertions that rendered headers contain `Generated from audit input <12 hex>`;
baseline snapshots omit `generated_at`, `commit`, and `age_commits`; two
`_diff.run()` calls for the same digest produce identical `baseline.json` and
`CHANGES.md`; a new digest rotates the old current snapshot into
`previous_baseline` exactly once; coverage freshness compares digests; and
doc-ledger footers contain the digest rather than a commit.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_diff.py tests\audit\test_coverage.py tests\audit\test_render_human.py tests\audit\test_render_llm.py tests\audit\test_docs_ledger.py -q`

Expected: current commit/timestamp assertions fail the new expectations.

- [ ] **Step 3: Thread `input_digest` through metrics and renderers**

Set it when metrics are built:

```python
return {
    "input_digest": _artifacts.input_digest(repo_root),
    "modules": modules,
    "headline": headline,
    "coverage": coverage_info,
    "dead_code": dead_code_info,
}
```

Render the first twelve characters in generated headers and footers. Remove
calls to `datetime.now()` from committed-output paths. Have the fast-test runner
write the current `input_digest` beside coverage data. `_coverage.py` marks
legacy commit-only metadata unusable and determines freshness solely by exact
digest equality; renderers show `matched` or `mismatched`, never commit age.

- [ ] **Step 4: Make `CHANGES.md` history digest-keyed and idempotent**

Keep current metrics at the baseline top level and store one
`previous_baseline`. If the existing input digest differs, rotate the former
top-level snapshot into `previous_baseline`; if it matches, preserve the
existing previous snapshot. Render `CHANGES.md` from current metrics versus
`previous_baseline`, with full digests in HTML comments and twelve-character
digests in headings. Do not preserve a second rolling Markdown history.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_diff.py tests\audit\test_coverage.py tests\audit\test_render_human.py tests\audit\test_render_llm.py tests\audit\test_docs_ledger.py -q`

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/audit tests/audit
git commit -m "feat(audit): make generated provenance deterministic"
```

---

### Task 3: Add non-mutating full verification

**Files:**
- Create: `scripts/audit/_verify.py`
- Modify: `scripts/audit/__main__.py`
- Create: `tests/audit/test_verify.py`
- Modify: `tests/audit/test_main.py`

**Interfaces:**
- Produces: `_verify.snapshot_generated(repo_root: Path) -> dict[str, bytes]`
- Produces: `_verify.restore_generated(repo_root: Path, snapshot: dict[str, bytes]) -> None`
- Produces: `_verify.verify(repo_root: Path, run_pipeline: Callable[[], int]) -> tuple[int, list[str]]`
- CLI: `python -m audit --verify` and `scripts\audit.cmd --verify`.

- [ ] **Step 1: Write failing restoration and drift tests**

Cover unchanged output, modified output, newly generated files, deleted expected
files, and a pipeline exception. In every case assert the original tree bytes
are restored after `verify()` returns or raises.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_verify.py tests\audit\test_main.py -q`

Expected: import or missing-CLI failures for `_verify`/`--verify`.

- [ ] **Step 3: Implement snapshot, compare, and restoration**

Only snapshot files under committed generated roots (`docs/audit`, excluding
policy inputs). Compare path sets and bytes after the pipeline. In `finally`,
delete generated files absent from the snapshot, recreate original files, and
remove newly empty directories. Return sorted relative paths.

- [ ] **Step 4: Wire the CLI**

`--verify` is mutually exclusive with `--fast`, `--check`, and a single stage.
It runs the normal full pipeline through `_verify.verify`, prints either
`audit generated output is current` or a sorted `generated drift:` list, and
returns 1 for drift or the pipeline's nonzero result for execution failure.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_verify.py tests\audit\test_main.py -q`

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/audit/_verify.py scripts/audit/__main__.py tests/audit/test_verify.py tests/audit/test_main.py
git commit -m "feat(audit): verify generated output without mutation"
```

---

### Task 4: Rename the generated LLM index to a neutral code index

**Files:**
- Rename: `scripts/audit/_render_llm.py` to `scripts/audit/_render_code_index.py`
- Rename: `tests/audit/test_render_llm.py` to `tests/audit/test_render_code_index.py`
- Modify: `scripts/audit/__main__.py`
- Modify: `tests/audit/test_render_extensions.py`
- Modify: `CLAUDE.md`
- Modify: `docs/audit/maps/overview.md` only through audit regeneration
- Remove generated: `docs/audit/llm/*.md`
- Create generated: `docs/audit/code-index/*.md`

**Interfaces:**
- Generated root: `docs/audit/code-index/`.
- Renderer module: `audit._render_code_index`.
- Descriptions remain module/public-symbol docstrings or `(no docstring)`.

- [ ] **Step 1: Rename the test module and write failing path assertions**

Assert renderer output keys begin with `docs/audit/code-index/`, the index says
`Code Index`, and no output key contains `/llm/`.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_render_code_index.py tests\audit\test_render_extensions.py -q`

Expected: old `llm` paths/titles fail.

- [ ] **Step 3: Rename the renderer and update imports, paths, titles, and pointers**

Keep the rendering algorithm unchanged. Do not introduce summary generation;
continue reading `mod["doc"]` and symbol docstrings only.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_render_code_index.py tests\audit\test_render_extensions.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/audit tests/audit CLAUDE.md
git commit -m "refactor(audit): rename LLM index as code index"
```

---

### Task 5: Add pull-request verification and manual update workflows

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/audit-update.yml`
- Create: `tests/audit/test_workflows.py`

**Interfaces:**
- PR job command: `scripts/audit.cmd --verify` on Windows.
- Manual job command: `scripts/audit.cmd` followed by creation/upload of a
  patch plus `docs/audit` artifacts.
- Workflow never commits or pushes.

- [ ] **Step 1: Write failing workflow contract tests**

Read workflow files as text and assert `pull_request`, `workflow_dispatch`,
`scripts/audit.cmd --verify`, full audit update, `git diff --binary`, and
`actions/upload-artifact` are present; assert `git push` is absent.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_workflows.py -q`

Expected: missing manual workflow and verification job failures.

- [ ] **Step 3: Add the CI jobs**

Use `windows-latest`, Python 3.12, `pip install -e ".[dev]"`, and the exact
PowerShell audit commands. Upload `audit-generated.patch`, `docs/audit/**`, and
`.audit/*.json` with `if: always()` for manual runs. Keep permissions at
`contents: read`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_workflows.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows tests/audit/test_workflows.py
git commit -m "ci(audit): verify generated docs on pull requests"
```

---

### Task 6: Regenerate and verify the complete branch

**Files:**
- Modify: generated files under `docs/audit/`
- Modify: `docs/audit/baseline.json`
- Modify: `docs/audit/CHANGES.md`

**Interfaces:**
- The committed generated tree is the output accepted by `audit --verify`.

- [ ] **Step 1: Run audit tests**

Run: `.venv\Scripts\python.exe -m pytest tests\audit -q`

Expected: all audit tests pass.

- [ ] **Step 2: Generate the deterministic output**

Run: `scripts\audit.cmd`

Expected: exit 0 and generated output under `docs/audit/code-index` with no
`docs/audit/llm` files.

- [ ] **Step 3: Prove a second run is non-mutating**

Run: `scripts\audit.cmd --verify`

Expected: exit 0 and `audit generated output is current`.

- [ ] **Step 4: Run repository verification**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check plex_renamer tests scripts
.venv\Scripts\python.exe -m pytest -q
git status --short
```

Expected: Ruff exits 0; `2026` or more tests pass with no failures; status lists
only intended plan-1 files.

- [ ] **Step 5: Commit generated artifacts**

```powershell
git add docs/audit
git commit -m "chore(audit): regenerate deterministic artifacts"
```
