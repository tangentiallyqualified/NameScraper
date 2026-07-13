from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_fast_runner
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
    assert cov["partial"] is True
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


def test_write_coverage_sidecar_failed_run_writes_partial_and_failed(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    test_fast_runner._write_coverage_sidecar(synthetic_repo, 1, ["tests/test_x.py"])
    meta_path = synthetic_repo / ".coverage.meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["partial"] is True
    assert meta["failed"] is True
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["partial"] is True
    assert cov["failed"] is True
    assert cov["stale"] is True


def test_write_coverage_sidecar_successful_full_run_not_partial(synthetic_repo: Path):
    test_fast_runner._write_coverage_sidecar(synthetic_repo, 0, [])
    meta = json.loads((synthetic_repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    assert meta["partial"] is False
    assert meta["failed"] is False


def test_write_coverage_sidecar_successful_filtered_run_marks_partial(synthetic_repo: Path):
    test_fast_runner._write_coverage_sidecar(synthetic_repo, 0, ["tests/test_x.py"])
    meta = json.loads((synthetic_repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    assert meta["partial"] is True


def test_non_boolean_partial_treated_as_partial(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    meta_path = synthetic_repo / ".coverage.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["partial"] = "false"  # malformed: string, not JSON boolean
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["partial"] is True
    assert cov["stale"] is True


def test_unavailable_reason_print_is_ascii(synthetic_repo: Path, monkeypatch, capsys):
    (synthetic_repo / ".coverage").write_text("stub", encoding="utf-8")

    def _boom(repo_root, data_file):
        raise RuntimeError("café exploded")

    monkeypatch.setattr(_coverage, "_read_modules", _boom)
    assert _coverage.run(synthetic_repo, None) == 2
    assert "caf? exploded" in capsys.readouterr().out


def test_falsy_non_boolean_partial_treated_as_partial(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    meta_path = synthetic_repo / ".coverage.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["partial"] = 0  # malformed: number, not JSON boolean; bool(0) would hide it
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["partial"] is True
    assert cov["stale"] is True


def test_run_fresh_uses_expected_command_cwd_and_timeout(
        synthetic_repo: Path, monkeypatch):
    seen = {}

    def _run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(_coverage.subprocess, "run", _run)
    _coverage._run_fresh(synthetic_repo)

    assert seen["command"] == [
        sys.executable,
        str(synthetic_repo / "scripts" / "test_fast_runner.py"),
        "--coverage",
    ]
    assert seen["cwd"] == synthetic_repo
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["timeout"] == 1800


def test_run_fresh_reports_launch_error_ascii_safe(synthetic_repo: Path, monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError("caf\u00e9 executable unavailable")

    monkeypatch.setattr(_coverage.subprocess, "run", _raise)
    with pytest.raises(RuntimeError) as exc_info:
        _coverage._run_fresh(synthetic_repo)

    message = str(exc_info.value)
    assert message == "could not launch fresh coverage run: caf? executable unavailable"
    assert message.isascii()


def test_run_fresh_reports_timeout_with_bounded_stderr(synthetic_repo: Path, monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0], timeout=1800, stderr=("last caf\u00e9 line " * 100)
        )

    monkeypatch.setattr(_coverage.subprocess, "run", _raise)
    with pytest.raises(RuntimeError) as exc_info:
        _coverage._run_fresh(synthetic_repo)

    message = str(exc_info.value)
    assert "timed out after 1800 seconds" in message
    assert "last caf? line" in message
    assert message.isascii()
    assert len(message) < 500


def test_run_fresh_reports_nonzero_with_bounded_stderr(synthetic_repo: Path, monkeypatch):
    monkeypatch.setattr(
        _coverage.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=7, stderr=("pytest caf\u00e9 failure " * 100)
        ),
    )
    with pytest.raises(RuntimeError) as exc_info:
        _coverage._run_fresh(synthetic_repo)

    message = str(exc_info.value)
    assert "failed (exit 7): pytest caf? failure" in message
    assert message.isascii()
    assert len(message) < 500


def test_collect_fresh_success_marks_source_and_preserves_evidence(
        synthetic_repo: Path, repo_git, monkeypatch):
    _make_coverage_data(synthetic_repo, repo_git)
    data_path = synthetic_repo / ".coverage"
    meta_path = synthetic_repo / ".coverage.meta.json"

    def _refresh(repo_root):
        data_path.write_bytes(data_path.read_bytes())
        meta_path.write_text(
            meta_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )

    monkeypatch.setattr(_coverage, "_run_fresh", _refresh)

    cov = _coverage.collect_coverage(synthetic_repo, fresh=True)

    assert cov["available"] is True
    assert cov["source"] == "fresh"
    assert cov["failed"] is False
    assert cov["partial"] is False
    assert cov["stale"] is False


def test_collect_fresh_success_without_new_data_is_unavailable(
        synthetic_repo: Path, repo_git, monkeypatch):
    _make_coverage_data(synthetic_repo, repo_git)
    monkeypatch.setattr(_coverage, "_run_fresh", lambda repo_root: None)

    cov = _coverage.collect_coverage(synthetic_repo, fresh=True)

    assert cov["available"] is False
    assert cov["source"] == "fresh"
    assert cov["failed"] is True
    assert cov["stale"] is True
    assert "did not replace .coverage data" in cov["reason"]


def test_collect_fresh_failure_does_not_reuse_older_coverage(
        synthetic_repo: Path, repo_git, monkeypatch):
    _make_coverage_data(synthetic_repo, repo_git)

    def _fail(repo_root):
        raise RuntimeError("fresh coverage run failed (exit 3): caf\u00e9")

    monkeypatch.setattr(_coverage, "_run_fresh", _fail)
    cov = _coverage.collect_coverage(synthetic_repo, fresh=True)

    assert cov["available"] is False
    assert cov["source"] == "fresh"
    assert cov["modules"] == {}
    assert cov["failed"] is True
    assert cov["partial"] is True
    assert cov["stale"] is True
    assert "exit 3" in cov["reason"]
    assert cov["reason"].isascii()


@pytest.mark.parametrize("raw_failed", ["false", 0, None, [], {}])
def test_non_boolean_failed_treated_as_failed_and_stale(
        synthetic_repo: Path, repo_git, raw_failed):
    _make_coverage_data(synthetic_repo, repo_git)
    meta_path = synthetic_repo / ".coverage.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["failed"] = raw_failed
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    cov = _coverage.collect_coverage(synthetic_repo)

    assert cov["available"] is True
    assert cov["failed"] is True
    assert cov["stale"] is True


def test_legacy_sidecar_without_failed_key_defaults_false(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["failed"] is False


def test_failed_sidecar_is_stale_even_when_not_partial(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    meta_path = synthetic_repo / ".coverage.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({"partial": False, "failed": True})
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    cov = _coverage.collect_coverage(synthetic_repo)

    assert cov["partial"] is False
    assert cov["failed"] is True
    assert cov["stale"] is True
