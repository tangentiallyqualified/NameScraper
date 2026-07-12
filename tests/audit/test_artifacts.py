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
