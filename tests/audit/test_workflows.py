from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
UPDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "audit-update.yml"


def test_pull_requests_verify_generated_audit_docs() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "windows-latest" in workflow
    assert "scripts/audit.cmd --verify" in workflow


def test_manual_audit_update_uploads_generated_outputs() -> None:
    workflow = UPDATE_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "scripts/audit.cmd" in workflow
    assert "git diff --binary" in workflow
    assert "actions/upload-artifact" in workflow
    assert "audit-generated.patch" in workflow
    assert "docs/audit/**" in workflow
    assert ".audit/*.json" in workflow
    assert "if: always()" in workflow


def test_audit_workflows_never_push() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CI_WORKFLOW, UPDATE_WORKFLOW)
        if path.exists()
    )

    assert "git push" not in workflows
