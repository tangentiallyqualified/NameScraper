from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from audit import _artifacts, _coverage


def _make_coverage_data(repo: Path, repo_git) -> None:
    """Execute alpha.used_function under coverage inside the synthetic repo."""
    script = repo / "_cov_driver.py"
    script.write_text("from plex_renamer.alpha import used_function\nused_function(3)\n",
                      encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--data-file={repo / '.coverage'}",
         "--source=plex_renamer", str(script)],
        cwd=repo, check=True, capture_output=True,
    )
    commit = repo_git(repo, "rev-parse", "--short", "HEAD")
    (repo / ".coverage.meta.json").write_text(
        json.dumps({"commit": commit, "collected_at": "2026-07-12T00:00:00+00:00"}),
        encoding="utf-8",
    )


def test_import_reads_per_module_percent(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["available"] is True
    assert cov["source"] == "imported"
    alpha = cov["modules"]["plex_renamer/alpha.py"]
    assert alpha["statements"] > 0
    assert 0 < alpha["percent"] < 100  # dead_function body is uncovered


def test_age_and_staleness(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    (synthetic_repo / "README.md").write_text("# v2\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "second")
    cov = _coverage.collect_coverage(synthetic_repo, max_age_commits=0)
    assert cov["age_commits"] == 1
    assert cov["stale"] is True
    fresh_enough = _coverage.collect_coverage(synthetic_repo, max_age_commits=15)
    assert fresh_enough["stale"] is False


def test_missing_data_degrades(synthetic_repo: Path):
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["available"] is False
    assert cov["reason"]


def test_run_degrades_without_data(synthetic_repo: Path, capsys):
    assert _coverage.run(synthetic_repo, None) == 2
    data = _artifacts.read_artifact(synthetic_repo, "coverage")
    assert data["available"] is False
    assert data["reason"]


def test_run_ok_with_data(synthetic_repo: Path, repo_git, capsys):
    _make_coverage_data(synthetic_repo, repo_git)
    assert _coverage.run(synthetic_repo, None) == 0
    data = _artifacts.read_artifact(synthetic_repo, "coverage")
    assert data["available"] is True
    assert data["modules"]


def test_max_age_zero_respected(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    (synthetic_repo / "README.md").write_text("# v2\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "second")
    opts = argparse.Namespace(with_coverage=False, coverage_max_age=0)
    assert _coverage.run(synthetic_repo, opts) == 0
    data = _artifacts.read_artifact(synthetic_repo, "coverage")
    assert data["age_commits"] == 1
    assert data["stale"] is True  # explicit 0 must not silently become 15


def test_corrupt_meta_sidecar_marks_stale(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    (synthetic_repo / ".coverage.meta.json").write_text("{not json", encoding="utf-8")
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["available"] is True
    assert cov["collected_at_commit"] is None
    assert cov["stale"] is True


def test_partial_sidecar_flags_partial_and_stale(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    meta = json.loads((synthetic_repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    meta["partial"] = True
    (synthetic_repo / ".coverage.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["available"] is True
    assert cov["partial"] is True
    assert cov["stale"] is True


def test_legacy_sidecar_without_partial_key_defaults_false(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["partial"] is False
    assert cov["stale"] is False


def test_run_with_partial_data_still_exits_zero_and_notes_partial(synthetic_repo: Path, repo_git, capsys):
    _make_coverage_data(synthetic_repo, repo_git)
    meta = json.loads((synthetic_repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    meta["partial"] = True
    (synthetic_repo / ".coverage.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert _coverage.run(synthetic_repo, None) == 0
    data = _artifacts.read_artifact(synthetic_repo, "coverage")
    assert data["partial"] is True
    out = capsys.readouterr().out
    assert "partial run" in out
