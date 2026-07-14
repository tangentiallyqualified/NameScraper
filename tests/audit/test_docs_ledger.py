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


def test_dirty_and_committed_sources_produce_identical_ledger_status(
        synthetic_repo: Path, repo_git):
    reviewed = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nDIRTY = 1\n", encoding="utf-8")
    scripts = synthetic_repo / "scripts"
    scripts.mkdir(exist_ok=True)
    staged = scripts / "staged.py"
    staged.write_text("STAGED = 1\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "scripts/staged.py")
    untracked = synthetic_repo / "tests" / "test_untracked.py"
    untracked.write_text("UNTRACKED = 1\n", encoding="utf-8")
    entries = [{
        "path": "docs/guide.md",
        "reviewed_commit": reviewed,
        "sources": ["plex_renamer", "scripts", "tests"],
    }]

    before = _docs_ledger.staleness(synthetic_repo, entries)
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "commit ledger sources")
    after = _docs_ledger.staleness(synthetic_repo, entries)

    assert before == after
    assert before[0]["changed_sources"] == [
        "plex_renamer/alpha.py",
        "scripts/staged.py",
        "tests/test_untracked.py",
    ]


def test_run_writes_doc_status_with_purge_worksheet(synthetic_repo: Path, repo_git):
    head = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    _enroll(synthetic_repo, head)
    _inventory.run(synthetic_repo, None)
    assert _docs_ledger.run(synthetic_repo, None) == 0
    status = (synthetic_repo / "docs" / "audit" / "doc-status.md").read_text(encoding="utf-8")
    assert "docs/guide.md" in status
    assert "plex_renamer/gone.py" in status  # broken ref surfaced for purge review
    digest = _inventory._artifacts.input_digest(synthetic_repo)
    assert f"Generated from audit input {digest[:12]}" in status
    assert "Generated at commit" not in status


def test_missing_ledger_is_empty(synthetic_repo: Path):
    assert _docs_ledger.load_ledger(synthetic_repo) == []
