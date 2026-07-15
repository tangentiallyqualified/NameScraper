from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from audit import _artifacts, _coverage

from scripts import test_fast_runner


def _make_coverage_data(repo: Path, repo_git, *, include_source: bool = True) -> None:
    """Execute alpha.used_function under coverage inside the synthetic repo."""
    script = repo / "_cov_driver.py"
    script.write_text(
        "from plex_renamer.alpha import used_function\nused_function(3)\n", encoding="utf-8"
    )
    source = ["--source=plex_renamer"] if include_source else []
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--data-file={repo / '.coverage'}",
            *source,
            str(script),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    qt_tests = test_fast_runner._discover_qt_tests(repo)
    scope = test_fast_runner._coverage_scope(repo, [], list(qt_tests))
    (repo / ".coverage.meta.json").write_text(
        json.dumps(
            {
                "input_digest": _artifacts.input_digest(repo),
                "collected_at": "2026-07-12T00:00:00+00:00",
                "full_suite": True,
                "suite": "fast",
                "scope_id": test_fast_runner._scope_id(scope),
                "scope": scope,
            }
        ),
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


def test_quality_coverage_accepts_digest_matched_full_suite_evidence(
    synthetic_repo: Path, repo_git
) -> None:
    _make_coverage_data(synthetic_repo, repo_git)
    evidence = _coverage.collect_quality_coverage(synthetic_repo)
    alpha = evidence["files"]["plex_renamer/alpha.py"]
    assert evidence["input_digest"] == _artifacts.input_digest(synthetic_repo)
    assert evidence["full_suite"] is True
    assert alpha["executable_lines"]
    assert all(set(line) == {"fingerprint", "covered"} for line in alpha["executable_lines"])
    package = evidence["package_floors"]["plex_renamer"]
    covered = sum(module["covered"] for module in evidence["modules"].values())
    statements = sum(module["statements"] for module in evidence["modules"].values())
    assert package == {
        "covered": covered,
        "statements": statements,
        "percent": pytest.approx(100.0 * covered / statements, abs=0.05),
    }


def _update_meta(repo: Path, **updates: object) -> None:
    path = repo / ".coverage.meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.update(updates)
    path.write_text(json.dumps(meta), encoding="utf-8")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda repo: (repo / ".coverage").unlink(), "missing coverage evidence"),
        (lambda repo: _update_meta(repo, failed=True), "failed coverage evidence"),
        (lambda repo: _update_meta(repo, partial=True), "partial coverage evidence"),
        (
            lambda repo: (repo / "README.md").write_text(
                "# changed after coverage\n", encoding="utf-8"
            ),
            "coverage evidence input digest mismatch",
        ),
        (
            lambda repo: _update_meta(repo, scope_id=None),
            "coverage-scope-incomplete",
        ),
    ],
)
def test_quality_coverage_rejects_unusable_evidence_distinctly(
    synthetic_repo: Path, repo_git, mutate, message: str
) -> None:
    _make_coverage_data(synthetic_repo, repo_git)
    mutate(synthetic_repo)
    with pytest.raises(_coverage.CoverageEvidenceError, match=message):
        _coverage.collect_quality_coverage(synthetic_repo)


def _line(fingerprint: str, covered: bool) -> dict[str, object]:
    return {"fingerprint": fingerprint, "covered": covered}


def test_changed_lines_are_path_local_and_detect_insertions_and_duplicates() -> None:
    baseline = {
        "executable_lines": {
            "plex_renamer/alpha.py": ["a#1", "b#1", "dup#1"],
        },
        "package_floors": {},
    }
    current = {
        "files": {
            "plex_renamer/alpha.py": {
                "executable_lines": [
                    _line("a#1", False),
                    _line("b#1", False),
                    _line("dup#1", False),
                    _line("dup#2", True),
                    _line("new#1", False),
                ]
            },
            "plex_renamer/beta.py": {
                "executable_lines": [
                    _line("a#1", True),
                ]
            },
        },
        "package_floors": {},
    }

    result = _coverage.evaluate_quality_coverage(current, baseline, 80.0)
    assert result["changed_lines"] == {
        "covered": 2,
        "statements": 3,
        "percent": 66.7,
    }


@pytest.mark.parametrize(
    ("covered", "statements", "violates"),
    [(4, 5, False), (79, 100, True), (799, 999, True)],
)
def test_changed_executable_lines_require_policy_threshold(
    covered: int, statements: int, violates: bool
) -> None:
    current = {
        "files": {
            "plex_renamer/new.py": {
                "executable_lines": [
                    _line(f"line-{number}", number < covered) for number in range(statements)
                ]
            },
        },
        "package_floors": {},
    }

    result = _coverage.evaluate_quality_coverage(
        current,
        {"executable_lines": {}, "package_floors": {}},
        80.0,
    )

    assert bool(result["violations"]) is violates
    if violates:
        assert result["violations"][0]["kind"] == "changed-line-coverage"


def test_package_statement_floor_cannot_decrease() -> None:
    current = {
        "files": {},
        "package_floors": {
            "plex_renamer": {"covered": 89, "statements": 100, "percent": 89.0},
            "plex_renamer/new": {"covered": 1, "statements": 2, "percent": 50.0},
        },
    }
    baseline = {
        "executable_lines": {},
        "package_floors": {
            "plex_renamer": {"covered": 9, "statements": 10, "percent": 90.0},
        },
    }

    result = _coverage.evaluate_quality_coverage(current, baseline, 80.0)

    assert result["violations"] == [
        {
            "baseline": 90.0,
            "current": 89.0,
            "kind": "package-floor-decrease",
            "path": "plex_renamer",
        }
    ]


def test_import_propagates_known_coverage_scope(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    meta_path = synthetic_repo / ".coverage.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "scope_id": "scope-123",
            "scope": {"coverage_source": ["plex_renamer"], "pytest_args": []},
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    cov = _coverage.collect_coverage(synthetic_repo)

    assert cov["scope_id"] == "scope-123"
    assert cov["scope"] == {
        "coverage_source": ["plex_renamer"],
        "pytest_args": [],
    }


def test_coverage_freshness_uses_exact_input_digest(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["input_digest"] == _artifacts.input_digest(synthetic_repo)
    assert cov["stale"] is False

    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nNEW = 1\n", encoding="utf-8")
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["stale"] is True
    assert cov["input_digest"] != _artifacts.input_digest(synthetic_repo)


def test_legacy_commit_only_coverage_metadata_is_unusable(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    meta_path = synthetic_repo / ".coverage.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("input_digest")
    meta["commit"] = repo_git(synthetic_repo, "rev-parse", "--short", "HEAD")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    cov = _coverage.collect_coverage(synthetic_repo)

    assert cov["input_digest"] is None
    assert cov["stale"] is True


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


def test_corrupt_meta_sidecar_marks_stale(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    (synthetic_repo / ".coverage.meta.json").write_text("{not json", encoding="utf-8")
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["available"] is True
    assert cov["input_digest"] is None
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


def test_sidecar_without_partial_key_defaults_false(synthetic_repo: Path, repo_git):
    _make_coverage_data(synthetic_repo, repo_git)
    cov = _coverage.collect_coverage(synthetic_repo)
    assert cov["partial"] is False
    assert cov["stale"] is False


def test_run_with_partial_data_still_exits_zero_and_notes_partial(
    synthetic_repo: Path, repo_git, capsys
):
    _make_coverage_data(synthetic_repo, repo_git)
    meta = json.loads((synthetic_repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    meta["partial"] = True
    (synthetic_repo / ".coverage.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert _coverage.run(synthetic_repo, None) == 0
    data = _artifacts.read_artifact(synthetic_repo, "coverage")
    assert data["partial"] is True
    out = capsys.readouterr().out
    assert "partial run" in out


def test_write_coverage_sidecar_failed_run_writes_partial_and_failed(
    synthetic_repo: Path, repo_git
):
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
    assert meta["input_digest"] == _artifacts.input_digest(synthetic_repo)


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


def test_run_fresh_uses_expected_command_cwd_and_timeout(synthetic_repo: Path, monkeypatch):
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
    synthetic_repo: Path, repo_git, monkeypatch
):
    _make_coverage_data(synthetic_repo, repo_git)
    data_path = synthetic_repo / ".coverage"
    meta_path = synthetic_repo / ".coverage.meta.json"

    def _refresh(repo_root):
        data_path.write_bytes(data_path.read_bytes())
        meta_path.write_text(meta_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    monkeypatch.setattr(_coverage, "_run_fresh", _refresh)

    cov = _coverage.collect_coverage(synthetic_repo, fresh=True)

    assert cov["available"] is True
    assert cov["source"] == "fresh"
    assert cov["failed"] is False
    assert cov["partial"] is False
    assert cov["stale"] is False


def test_collect_fresh_success_without_new_data_is_unavailable(
    synthetic_repo: Path, repo_git, monkeypatch
):
    _make_coverage_data(synthetic_repo, repo_git)
    monkeypatch.setattr(_coverage, "_run_fresh", lambda repo_root: None)

    cov = _coverage.collect_coverage(synthetic_repo, fresh=True)

    assert cov["available"] is False
    assert cov["source"] == "fresh"
    assert cov["failed"] is True
    assert cov["stale"] is True
    assert "did not replace .coverage data" in cov["reason"]


def test_collect_fresh_failure_does_not_reuse_older_coverage(
    synthetic_repo: Path, repo_git, monkeypatch
):
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
def test_non_boolean_failed_treated_as_failed_and_stale(synthetic_repo: Path, repo_git, raw_failed):
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
