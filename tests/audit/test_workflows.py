from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
UPDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "audit-update.yml"


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
    install = _step(job, "- name: Install dependencies")

    assert "pull_request:" in workflow
    assert "runs-on: windows-latest" in job
    assert "permissions:\n      contents: read" in job
    assert "fetch-depth: 0" in checkout
    assert 'python-version: "3.12"' in setup_python
    assert 'pip install -e ".[dev]"' in install
    assert "run: scripts/audit.cmd --verify" in job


def test_manual_audit_update_uploads_generated_outputs() -> None:
    workflow = UPDATE_WORKFLOW.read_text(encoding="utf-8")
    job = _job(workflow, "audit-update")
    checkout = _step(job, "- uses: actions/checkout@v4")
    setup_python = _step(job, "- uses: actions/setup-python@v5")
    install = _step(job, "- name: Install dependencies")
    stage = _step(job, "- name: Stage generated audit docs")
    patch = _step(job, "- name: Create binary patch")
    upload = _step(job, "- name: Upload generated audit artifacts")

    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in job
    assert "permissions:\n      contents: read" in job
    assert "fetch-depth: 0" in checkout
    assert 'python-version: "3.12"' in setup_python
    assert 'pip install -e ".[dev]"' in install
    assert "run: scripts/audit.cmd\n" in job
    assert "if: always()" in stage
    assert "run: git add -A -- docs/audit" in stage
    assert "if: always()" in patch
    assert (
        "run: git diff --cached --binary --output=audit-generated.patch HEAD -- docs/audit"
        in patch
    )
    assert job.index("git add -A -- docs/audit") < job.index("git diff --cached --binary")
    assert "if: always()" in upload
    assert "actions/upload-artifact" in upload
    assert "audit-generated.patch" in upload
    assert "docs/audit/**" in upload
    assert ".audit/*.json" in upload


def test_audit_workflows_never_commit_or_push() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CI_WORKFLOW, UPDATE_WORKFLOW)
        if path.exists()
    )

    assert "git commit" not in workflows
    assert "git push" not in workflows
