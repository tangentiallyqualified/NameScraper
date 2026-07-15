# Audit Harness README Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give contributors a concise README workflow for running the deterministic audit harness and quality ratchets used by CI.

**Architecture:** Keep the contributor entry point in `README.md`, immediately after Testing, and leave detailed generated audit material under `docs/audit/`. Correct the audit CLI help string so the command-line contract and README agree, with focused tests locking both documentation surfaces to the implemented behavior.

**Tech Stack:** Markdown, Python 3.11+, argparse, pytest, PowerShell/CMD wrappers, Ruff, Pyright, Coverage.py, Radon, Vulture.

## Global Constraints

- Keep the README section concise; do not turn it into a complete stage-by-stage CLI reference.
- Use Windows-primary commands rooted at `scripts\test-fast.cmd` and `scripts\audit.cmd`.
- Preserve the distinction between `test-fast.cmd -Coverage` and `audit.cmd --with-coverage`.
- `--quality-check` requires current, full, unfiltered, digest-matched coverage evidence.
- New or enlarged debt fails `--quality-check`; stale debt-baseline entries are reported but do not fail it.
- Stale, duplicate, expired, or otherwise invalid manual decisions remain fail-closed during audit generation.
- Do not change audit behavior, quality thresholds, analyzer constraints, baseline contents or schemas, generated artifact formats, or CI ordering.
- Contributors inspect and commit generated output changes; they do not hand-edit generated sections.

## File map

- `scripts/audit/__main__.py`: owns argparse help text for audit modes.
- `tests/audit/test_cli.py`: locks CLI help to the implemented stale-baseline exit contract.
- `README.md`: owns the concise contributor workflow and correct development-tool installation guidance.
- `tests/audit/test_workflows.py`: locks README commands, ordering, and key safety guidance to CI and wrapper contracts.

---

### Task 1: Correct the quality-check CLI contract text

**Files:**
- Modify: `scripts/audit/__main__.py:166-170`
- Test: `tests/audit/test_cli.py:300-306`

**Interfaces:**
- Consumes: `cli.main(["--help"])`, which exits through argparse with status `0` and writes help to stdout.
- Produces: help text stating that new/enlarged debt fails while stale baseline entries are reported.

- [ ] **Step 1: Write the failing CLI help test**

Add this test beside `test_coverage_max_age_help_marks_option_as_legacy`:

```python
def test_quality_check_help_reports_stale_baseline_without_calling_it_debt(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out.lower()
    assert "fail on new/enlarged quality debt" in output
    assert "report stale baseline entries" in output
    assert "debt or stale baseline entries" not in output
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m pytest tests/audit/test_cli.py::test_quality_check_help_reports_stale_baseline_without_calling_it_debt -q
```

Expected: `1 failed`; the old help contains `debt or stale baseline entries` and does not contain `report stale baseline entries`.

- [ ] **Step 3: Correct only the argparse help string**

Replace the `--quality-check` argument with:

```python
parser.add_argument(
    "--quality-check",
    action="store_true",
    help="Fail on new/enlarged quality debt; report stale baseline entries.",
)
```

Do not change `run_quality_check`, its exit code, or baseline evaluation.

- [ ] **Step 4: Run focused CLI tests and confirm GREEN**

Run:

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m pytest tests/audit/test_cli.py::test_quality_check_help_reports_stale_baseline_without_calling_it_debt tests/audit/test_cli.py::test_quality_check_returns_zero_for_stale_baseline_only -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run Ruff on the touched Python files**

Run:

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m ruff check scripts/audit/__main__.py tests/audit/test_cli.py
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m ruff format --check scripts/audit/__main__.py tests/audit/test_cli.py
```

Expected: both commands exit `0`; Ruff reports no lint or format change required.

- [ ] **Step 6: Commit the CLI documentation correction**

```powershell
git add -- scripts/audit/__main__.py tests/audit/test_cli.py
git commit -m "docs(audit): clarify stale baseline help"
```

Expected: one commit containing only the help string and focused contract test.

---

### Task 2: Add the concise README audit workflow

**Files:**
- Modify: `README.md:171-193`
- Test: `tests/audit/test_workflows.py:5-8,186-199`

**Interfaces:**
- Consumes: the existing CI sequence `scripts/test-fast.cmd -Coverage`, `scripts/audit.cmd --quality-check`, and `scripts/audit.cmd --verify`.
- Produces: a contributor section named `## Audit harness and quality ratchets` located after Testing and before Architecture.

- [ ] **Step 1: Write the failing README contract test**

Add a README constant beside the existing path constants:

```python
README = REPO_ROOT / "README.md"
```

Append this test after `test_audit_analyzer_constraints_are_exact`:

```python
def test_readme_documents_ci_equivalent_audit_workflow() -> None:
    readme = README.read_text(encoding="utf-8")
    heading = "## Audit harness and quality ratchets"
    start = readme.index(heading)
    end = readme.index("\n---\n", start)
    guide = readme[start:end]

    coverage = r".\scripts\test-fast.cmd -Coverage"
    quality = r".\scripts\audit.cmd --quality-check"
    verify = r".\scripts\audit.cmd --verify"
    assert readme.index("## Testing") < start < readme.index("## Architecture")
    assert guide.index(coverage) < guide.index(quality) < guide.index(verify)
    assert (
        r'.\.venv\Scripts\python.exe -m pip install -e ".[dev]" '
        r"-c .\scripts\audit\constraints.txt"
    ) in readme
    assert r".\scripts\audit.cmd --with-coverage" in guide
    assert r".\scripts\audit.cmd --update-quality-baseline" in guide
    assert "does not collect coverage" in guide
    assert "stale baseline entries" in guide
    assert "scripts/audit/decisions.toml" in guide
    assert "audit.sarif" in guide
```

- [ ] **Step 2: Run the README contract test and confirm RED**

Run:

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m pytest tests/audit/test_workflows.py::test_readme_documents_ci_equivalent_audit_workflow -q
```

Expected: `1 failed` with `ValueError: substring not found` for the missing heading.

- [ ] **Step 3: Correct development dependency guidance**

Replace:

````markdown
Dev dependencies (just pytest) install with the `dev` extra:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```
````

with:

````markdown
The `dev` extra installs pytest and the audit toolchain. Use the committed
constraints file so local analyzer versions match CI:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c .\scripts\audit\constraints.txt
```
````

- [ ] **Step 4: Add the approved README section**

Insert this content after the real-library harness paragraph and before the horizontal rule preceding Architecture:

````markdown
## Audit harness and quality ratchets

The audit harness generates the code maps and live findings under `docs/audit/`
and the root `audit.sarif`. Its quality gate prevents new or enlarged formatting,
lint, typing, complexity, file-size, and coverage debt while allowing the
committed legacy baseline to improve over time.

Run the same sequence used by CI before submitting a change:

```powershell
.\scripts\test-fast.cmd -Coverage
.\scripts\audit.cmd --quality-check
.\scripts\audit.cmd --verify
```

`--quality-check` does not collect coverage. If coverage is missing, partial,
filtered, failed, or no longer matches the repository input digest, rerun
`test-fast.cmd -Coverage`. New or enlarged debt fails the gate; stale baseline
entries are reported as improvements and do not fail it.

To regenerate committed audit artifacts with fresh coverage after an intentional
input change, run:

```powershell
.\scripts\audit.cmd --with-coverage
```

Inspect and commit the generated changes rather than hand-editing generated
sections. Exact analyzer/rule/path/symbol decisions belong in
`scripts/audit/decisions.toml`; stale, duplicate, expired, or invalid decisions
fail generation.

After removing legacy debt, safely prune the existing quality baseline with:

```powershell
.\scripts\test-fast.cmd -Coverage
.\scripts\audit.cmd --update-quality-baseline
```

The updater refuses new or enlarged debt and never enrolls newly discovered
Python files as legacy. Note the Windows wrapper syntax: `test-fast.cmd` uses
`-Coverage`, while `audit.cmd` uses options such as `--with-coverage`.
````

- [ ] **Step 5: Run the documentation and CLI contract tests**

Run:

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m pytest tests/audit/test_workflows.py tests/audit/test_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Verify the documented commands against the wrappers**

Run:

```powershell
.\scripts\audit.cmd --help
```

Expected: exit `0`; help lists `--quality-check`, `--verify`, `--with-coverage`, and `--update-quality-baseline`, and describes stale entries as reported rather than failing debt.

Run fresh coverage and the two non-mutating CI-equivalent gates:

```powershell
.\scripts\test-fast.cmd -Coverage
.\scripts\audit.cmd --quality-check
.\scripts\audit.cmd --verify
```

Expected:

- coverage completes without test failures;
- quality prints `baseline current; no new or enlarged debt` and exits `0`;
- verify prints `audit generated output is current` and exits `0`.

- [ ] **Step 7: Check formatting, generated drift, and scope**

Run:

```powershell
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m ruff check scripts/audit/__main__.py tests/audit/test_cli.py tests/audit/test_workflows.py
& 'C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts\python.exe' -m ruff format --check scripts/audit/__main__.py tests/audit/test_cli.py tests/audit/test_workflows.py
git diff --check
git status --short
```

Expected: Ruff and `git diff --check` exit `0`; status lists only `README.md`, `tests/audit/test_workflows.py`, and any still-uncommitted plan artifact. Generated audit files remain unchanged after `--verify`.

- [ ] **Step 8: Commit the README workflow**

```powershell
git add -- README.md tests/audit/test_workflows.py
git commit -m "docs: explain audit harness workflow"
```

Expected: one commit containing the README guide and its contract test.

- [ ] **Step 9: Confirm branch readiness**

Run:

```powershell
git status --short
git log -3 --oneline
```

Expected: clean worktree after the plan artifact is committed or intentionally excluded; the latest implementation commits are `docs: explain audit harness workflow` and `docs(audit): clarify stale baseline help`.
