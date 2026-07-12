from __future__ import annotations

from pathlib import Path

from audit import _docs_ledger, _inventory


def _enroll(repo: Path, reviewed_commit: str) -> None:
    ledger_dir = repo / "docs" / "audit"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "doc-ledger.toml").write_text(
        'docs = [\n'
        f'  {{ path = "docs/guide.md", sources = ["plex_renamer/alpha.py"], reviewed_commit = "{reviewed_commit}" }},\n'
        ']\n',
        encoding="utf-8",
    )


def test_fresh_doc_not_stale(synthetic_repo: Path, repo_git):
    head = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    _enroll(synthetic_repo, head)
    report = _docs_ledger.staleness(synthetic_repo, _docs_ledger.load_ledger(synthetic_repo))
    assert report[0]["stale"] is False
    assert report[0]["changed_sources"] == []


def test_source_change_marks_stale(synthetic_repo: Path, repo_git):
    head = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    _enroll(synthetic_repo, head)
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nNEW = 1\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "touch alpha")
    report = _docs_ledger.staleness(synthetic_repo, _docs_ledger.load_ledger(synthetic_repo))
    assert report[0]["stale"] is True
    assert report[0]["changed_sources"] == ["plex_renamer/alpha.py"]


def test_run_writes_doc_status_with_purge_worksheet(synthetic_repo: Path, repo_git):
    head = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    _enroll(synthetic_repo, head)
    _inventory.run(synthetic_repo, None)
    assert _docs_ledger.run(synthetic_repo, None) == 0
    status = (synthetic_repo / "docs" / "audit" / "doc-status.md").read_text(encoding="utf-8")
    assert "docs/guide.md" in status
    assert "plex_renamer/gone.py" in status  # broken ref surfaced for purge review


def test_missing_ledger_is_empty(synthetic_repo: Path):
    assert _docs_ledger.load_ledger(synthetic_repo) == []
