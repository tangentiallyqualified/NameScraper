from __future__ import annotations

from pathlib import Path

import pytest

from audit import _artifacts


def _audit_repo(tmp_path: Path) -> Path:
    files = {
        "plex_renamer/example.py": "VALUE = 1\n",
        "scripts/audit/_stage.py": "STAGE = 1\n",
        "scripts/audit/allowlist.toml": "ignore = []\n",
        "scripts/audit/contracts.toml": "forbid = []\n",
        "scripts/audit/policy.toml": "[quality]\nthreshold = 1\n",
        "scripts/audit/quality-baseline.json": '{"schema_version": 2}\n',
        "scripts/audit.cmd": "@echo off\n",
        "scripts/audit.ps1": "Write-Output audit\n",
        "scripts/test_fast_runner.py": "RUNNER = 1\n",
        "scripts/test-fast.cmd": "@echo off\n",
        "scripts/test-fast.ps1": "Write-Output test\n",
        "tests/audit/test_stage.py": "def test_stage(): pass\n",
        "pyproject.toml": "[tool.audit]\n",
        "docs/audit/doc-ledger.toml": "documents = []\n",
        "docs/audit/maps/overview.md": "generated overview\n",
        "docs/guide.md": "ordinary documentation\n",
        "README.md": "root documentation\n",
        "scripts/audit/constraints.txt": "ruff==0.15.21\n",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_input_files_are_sorted_and_exclude_generated_or_cached_paths(tmp_path: Path):
    repo = _audit_repo(tmp_path)
    excluded = {
        ".git/hidden.py",
        ".venv/hidden.py",
        ".worktrees/hidden.py",
        ".audit/hidden.py",
        ".pytest_cache/hidden.py",
        "plex_renamer/__pycache__/hidden.py",
        "docs/audit/generated.py",
    }
    for relative_path in excluded:
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("HIDDEN = 1\n", encoding="utf-8")

    relative_paths = [path.relative_to(repo).as_posix() for path in _artifacts.input_files(repo)]

    assert relative_paths == sorted(relative_paths)
    assert not excluded.intersection(relative_paths)
    assert {
        "plex_renamer/example.py",
        "scripts/audit/_stage.py",
        "scripts/audit/allowlist.toml",
        "scripts/audit/contracts.toml",
        "scripts/audit.cmd",
        "scripts/audit.ps1",
        "scripts/test_fast_runner.py",
        "scripts/test-fast.cmd",
        "scripts/test-fast.ps1",
        "tests/audit/test_stage.py",
        "pyproject.toml",
        "docs/audit/doc-ledger.toml",
        "docs/guide.md",
        "README.md",
        "scripts/audit/constraints.txt",
    }.issubset(relative_paths)


def test_input_digest_is_stable_and_excludes_generated_docs(tmp_path: Path):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)
    (repo / "docs/audit/maps/overview.md").write_text("generated change", encoding="utf-8")
    assert _artifacts.input_digest(repo) == first


def test_input_digest_excludes_quality_baseline_ratchet_state(tmp_path: Path):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)

    (repo / "scripts/audit/quality-baseline.json").write_text(
        '{"schema_version": 2, "coverage": {"changed": true}}\n',
        encoding="utf-8",
    )

    assert _artifacts.input_digest(repo) == first
    assert "scripts/audit/quality-baseline.json" not in {
        path.relative_to(repo).as_posix() for path in _artifacts.input_files(repo)
    }


@pytest.mark.parametrize(
    "relative_path",
    [
        "plex_renamer/example.py",
        "scripts/audit/_stage.py",
        "scripts/audit/allowlist.toml",
        "scripts/audit/policy.toml",
        "scripts/audit.cmd",
        "scripts/test-fast.ps1",
        "tests/audit/test_stage.py",
        "pyproject.toml",
        "docs/audit/doc-ledger.toml",
        "docs/guide.md",
        "README.md",
        "scripts/audit/constraints.txt",
    ],
)
def test_input_digest_changes_when_source_or_policy_changes(tmp_path: Path, relative_path: str):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)
    (repo / relative_path).write_text("changed bytes\n", encoding="utf-8")
    assert _artifacts.input_digest(repo) != first


def test_input_digest_changes_when_ordinary_documentation_changes(tmp_path: Path):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)

    (repo / "docs/guide.md").write_text("changed documentation\n", encoding="utf-8")

    assert _artifacts.input_digest(repo) != first


@pytest.mark.parametrize(
    "ignored_root",
    [".superpowers", ".agents", ".codex", ".claude", ".vscode"],
)
def test_input_digest_ignores_agent_and_scratch_documentation(tmp_path: Path, ignored_root: str):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)
    report = repo / ignored_root / "sdd" / "report.md"
    report.parent.mkdir(parents=True)
    report.write_text("ignored scratch report\n", encoding="utf-8")

    assert _artifacts.input_digest(repo) == first


def test_input_digest_changes_when_input_path_changes(tmp_path: Path):
    repo = _audit_repo(tmp_path)
    first = _artifacts.input_digest(repo)
    (repo / "plex_renamer/example.py").rename(repo / "plex_renamer/renamed.py")
    assert _artifacts.input_digest(repo) != first


def test_write_then_read_roundtrip(synthetic_repo: Path):
    _artifacts.write_artifact(synthetic_repo, "inventory", {"python_files": []})
    data = _artifacts.read_artifact(synthetic_repo, "inventory")
    assert data["python_files"] == []
    assert data["commit"]  # stamped from git
    assert data["generated_at"]


def test_missing_artifact_names_producer(synthetic_repo: Path):
    with pytest.raises(_artifacts.MissingArtifactError) as exc:
        _artifacts.read_artifact(synthetic_repo, "graph")
    assert "graph" in str(exc.value)
    assert "audit" in str(exc.value)


def test_commits_between(synthetic_repo: Path, repo_git):
    first = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    (synthetic_repo / "README.md").write_text("# Mini v2\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "second")
    assert _artifacts.commits_between(synthetic_repo, first) == 1
    assert _artifacts.current_commit(synthetic_repo) != first


def test_payload_cannot_override_stamps(synthetic_repo: Path):
    _artifacts.write_artifact(
        synthetic_repo, "inventory", {"commit": "spoofed", "generated_at": "1999"}
    )
    data = _artifacts.read_artifact(synthetic_repo, "inventory")
    assert data["commit"] != "spoofed"
    assert data["generated_at"] != "1999"


def test_git_helpers_return_none_on_subprocess_failure(synthetic_repo: Path, monkeypatch):
    import subprocess as sp

    def _boom(*args, **kwargs):
        raise sp.TimeoutExpired(cmd="git", timeout=15)

    monkeypatch.setattr(sp, "run", _boom)
    assert _artifacts.current_commit(synthetic_repo) is None
    assert _artifacts.commits_between(synthetic_repo, "abc1234") is None
    assert _artifacts.changed_files_since(synthetic_repo, "abc1234", "plex_renamer") is None


def test_package_of():
    assert _artifacts.package_of("plex_renamer/engine/_scanner.py") == "engine"
    assert _artifacts.package_of("plex_renamer/alpha.py") == "root"


def test_working_tree_files_include_staged_unstaged_and_untracked(synthetic_repo: Path, repo_git):
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nDIRTY = 1\n", encoding="utf-8")
    (synthetic_repo / "plex_renamer" / "new.py").write_text("NEW = 1\n", encoding="utf-8")
    (synthetic_repo / "scripts").mkdir(exist_ok=True)
    harness = synthetic_repo / "scripts" / "audit.py"
    harness.write_text("AUDIT = 1\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "scripts/audit.py")

    files = _artifacts.working_tree_files(synthetic_repo, "plex_renamer", "scripts")
    assert files == ["plex_renamer/alpha.py", "plex_renamer/new.py", "scripts/audit.py"]


def test_working_tree_files_respects_pathspecs(synthetic_repo: Path):
    (synthetic_repo / "README.md").write_text("# dirty\n", encoding="utf-8")
    assert _artifacts.working_tree_files(synthetic_repo, "plex_renamer") == []


def test_changed_files_are_stable_when_a_rename_loses_similarity(synthetic_repo: Path, repo_git):
    old = synthetic_repo / "tests" / "test_legacy_name.py"
    old.write_text("\n".join(f"LINE_{i} = {i}" for i in range(40)) + "\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "tests/test_legacy_name.py")
    repo_git(synthetic_repo, "commit", "-m", "add legacy test")
    reviewed = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    new = synthetic_repo / "tests" / "test_new_name.py"
    old.rename(new)
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "rename test")
    new.write_text("NEW_CONTENT = True\n", encoding="utf-8")

    before = _artifacts.changed_files_since(synthetic_repo, reviewed, "tests")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "replace renamed test")
    after = _artifacts.changed_files_since(synthetic_repo, reviewed, "tests")

    assert before == after == ["tests/test_legacy_name.py", "tests/test_new_name.py"]
