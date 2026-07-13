from __future__ import annotations

from pathlib import Path

import pytest

from audit import _artifacts


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
    _artifacts.write_artifact(synthetic_repo, "inventory",
                              {"commit": "spoofed", "generated_at": "1999"})
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
    (synthetic_repo / "scripts").mkdir()
    harness = synthetic_repo / "scripts" / "audit.py"
    harness.write_text("AUDIT = 1\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "scripts/audit.py")

    files = _artifacts.working_tree_files(synthetic_repo, "plex_renamer", "scripts")
    assert files == ["plex_renamer/alpha.py", "plex_renamer/new.py", "scripts/audit.py"]


def test_working_tree_files_respects_pathspecs(synthetic_repo: Path):
    (synthetic_repo / "README.md").write_text("# dirty\n", encoding="utf-8")
    assert _artifacts.working_tree_files(synthetic_repo, "plex_renamer") == []
