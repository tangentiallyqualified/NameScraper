from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
UPDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "audit-update.yml"
AUDIT_CONSTRAINTS = REPO_ROOT / "scripts" / "audit" / "constraints.txt"


def _job(workflow: str, name: str) -> str:
    marker = f"  {name}:\n"
    start = workflow.index(marker)
    remainder = workflow[start + len(marker) :]
    end = next(
        (
            offset
            for offset, line in _line_offsets(remainder)
            if line.startswith("  ") and not line.startswith("    ") and line.strip()
        ),
        len(remainder),
    )
    return remainder[:end]


def _step(job: str, marker: str) -> str:
    start = job.index(marker)
    line_start = job.rfind("\n", 0, start) + 1
    indent = len(job[line_start:start])
    remainder = job[start:]
    end = next(
        (
            offset
            for offset, line in _line_offsets(remainder)
            if offset > 0 and line.startswith(" " * indent + "- ")
        ),
        len(remainder),
    )
    return remainder[:end]


def _line_offsets(text: str):
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, line
        offset += len(line)


def test_pull_requests_verify_generated_audit_docs() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-verify")
    checkout = _step(job, "- uses: actions/checkout@v4")
    setup_python = _step(job, "- uses: actions/setup-python@v5")

    assert "pull_request:" in workflow
    assert "runs-on: windows-latest" in job
    assert "permissions:\n      contents: read" in job
    assert "fetch-depth: 0" in checkout
    assert 'python-version: "3.12"' in setup_python


def test_pull_request_audit_job_creates_and_provisions_venv() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-verify")
    create_marker = "- name: Create audit virtual environment"

    assert create_marker in job
    create_venv = _step(job, create_marker)
    install = _step(job, "- name: Install dependencies")

    assert "run: python -m venv .venv" in create_venv
    assert r".venv\Scripts\python.exe -m pip install --upgrade pip" in install
    assert r'.venv\Scripts\python.exe -m pip install -e ".[dev]"' in install
    assert r"-c scripts\audit\constraints.txt" in install
    assert (
        job.index("uses: actions/setup-python@v5")
        < job.index("python -m venv .venv")
        < job.index(r".venv\Scripts\python.exe -m pip install --upgrade pip")
        < job.index("scripts/audit.cmd")
    )


def test_pull_request_audit_job_runs_coverage_verification() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-verify")
    verify = _step(job, "- name: Verify generated audit docs")

    assert "run: scripts/audit.cmd --verify --with-coverage\n" in verify


def test_manual_audit_update_uploads_generated_outputs() -> None:
    workflow = UPDATE_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-update")
    checkout = _step(job, "- uses: actions/checkout@v4")
    setup_python = _step(job, "- uses: actions/setup-python@v5")
    stage = _step(job, "- name: Stage generated audit docs")
    patch = _step(job, "- name: Create binary patch")
    upload = _step(job, "- name: Upload generated audit artifacts")

    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in job
    assert "permissions:\n      contents: read" in job
    assert "fetch-depth: 0" in checkout
    assert 'python-version: "3.12"' in setup_python
    assert "if: always()" in stage
    assert "run: git add -A -- docs/audit" in stage
    assert "if: always()" in patch
    assert (
        "run: git diff --cached --binary --output=audit-generated.patch HEAD -- docs/audit" in patch
    )
    assert job.index("git add -A -- docs/audit") < job.index("git diff --cached --binary")
    assert "if: always()" in upload
    assert "actions/upload-artifact" in upload
    assert "audit-generated.patch" in upload
    assert "docs/audit/**" in upload
    assert ".audit/*.json" in upload
    assert "include-hidden-files: true" in upload


def test_manual_audit_job_creates_and_provisions_venv() -> None:
    workflow = UPDATE_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-update")
    create_marker = "- name: Create audit virtual environment"

    assert create_marker in job
    create_venv = _step(job, create_marker)
    install = _step(job, "- name: Install dependencies")

    assert "run: python -m venv .venv" in create_venv
    assert r".venv\Scripts\python.exe -m pip install --upgrade pip" in install
    assert r'.venv\Scripts\python.exe -m pip install -e ".[dev]"' in install
    assert r"-c scripts\audit\constraints.txt" in install
    assert (
        job.index("uses: actions/setup-python@v5")
        < job.index("python -m venv .venv")
        < job.index(r".venv\Scripts\python.exe -m pip install --upgrade pip")
        < job.index("scripts/audit.cmd")
    )


def test_manual_audit_job_runs_with_coverage_before_staging() -> None:
    workflow = UPDATE_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-update")
    generate = _step(job, "- name: Generate audit docs")

    assert "run: scripts/audit.cmd --with-coverage\n" in generate
    assert job.index("scripts/audit.cmd --with-coverage") < job.index("git add -A -- docs/audit")


def test_audit_workflows_never_commit_or_push() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8") for path in (CI_WORKFLOW, UPDATE_WORKFLOW) if path.exists()
    )

    assert "git commit" not in workflows
    assert "git push" not in workflows


def test_audit_analyzer_constraints_are_exact() -> None:
    constraints = {
        line.strip()
        for line in AUDIT_CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert constraints == {
        "coverage==7.15.0",
        "pyright==1.1.411",
        "radon==6.0.1",
        "ruff==0.15.21",
        "vulture==2.16",
    }
