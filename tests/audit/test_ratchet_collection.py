from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path

import pytest
from audit import __main__ as cli
from audit import _coverage, _ratchets


def _finding(
    analyzer: str = "ruff",
    rule: str = "F401",
    path: str = "plex_renamer/legacy.py",
    symbol: str | None = None,
) -> dict:
    return {
        "analyzer": analyzer,
        "rule": rule,
        "path": path,
        "symbol": symbol,
    }


def _write_quality_baseline(repo_root: Path, baseline: dict) -> None:
    path = repo_root / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"complexity": {}, "formatting": {}, **baseline}),
        encoding="utf-8",
    )


def _coverage_evidence(
    *,
    covered: int = 9,
    statements: int = 10,
    fingerprints: list[tuple[str, bool]] | None = None,
) -> dict:
    lines = fingerprints or [(f"line-{number}", number < covered) for number in range(statements)]
    return {
        "input_digest": "a" * 64,
        "suite": "full-coverage",
        "full_suite": True,
        "scope_id": "b" * 64,
        "files": {
            "plex_renamer/a.py": {
                "executable_lines": [
                    {"fingerprint": fingerprint, "covered": is_covered}
                    for fingerprint, is_covered in lines
                ],
            },
        },
        "package_floors": {
            "plex_renamer": {
                "covered": covered,
                "statements": statements,
                "percent": round(100.0 * covered / statements, 1),
            },
        },
    }


def test_changed_line_threshold_is_authoritative_policy() -> None:
    policy = (Path(_ratchets.__file__).parent / "policy.toml").read_text(encoding="utf-8")

    assert "changed_line_min_percent = 80.0" in policy
    assert _ratchets.CHANGED_LINE_MIN_PERCENT == 80.0


def test_coverage_baseline_schema_strips_line_results_and_records_provenance() -> None:
    current = {
        "input_digest": "a" * 64,
        "suite": "full-coverage",
        "full_suite": True,
        "scope_id": "b" * 64,
        "files": {
            "plex_renamer/a.py": {
                "executable_lines": [
                    {"fingerprint": "sha256:one#1", "covered": True},
                    {"fingerprint": "sha256:two#1", "covered": False},
                ]
            },
        },
        "package_floors": {
            "plex_renamer": {"covered": 1, "statements": 2, "percent": 50.0},
        },
    }

    baseline = _coverage.build_quality_baseline(current, 80.0)

    assert baseline == {
        "changed_line_min_percent": 80.0,
        "executable_lines": {
            "plex_renamer/a.py": ["sha256:one#1", "sha256:two#1"],
        },
        "full_suite": True,
        "package_floors": current["package_floors"],
        "scope_id": "b" * 64,
        "suite": "full-coverage",
    }


def test_quality_check_reports_changed_line_coverage_debt() -> None:
    previous_coverage = _coverage.build_quality_baseline(
        _coverage_evidence(fingerprints=[("old", True)]), 80.0
    )
    current_coverage = _coverage_evidence(
        covered=0,
        statements=1,
        fingerprints=[("new", False)],
    )

    violations = _ratchets.evaluate_ratchets(
        {"findings": [], "modules": {}, "coverage": current_coverage},
        {
            "schema_version": 2,
            "findings": [],
            "ceilings": {},
            "typing": {"legacy_python_files": []},
            "coverage": previous_coverage,
        },
    )

    assert {(item["analyzer"], item["rule"], item["kind"]) for item in violations} == {
        ("coverage", "changed-lines", "new-debt"),
        ("coverage", "package-floor", "enlarged-debt"),
    }


def test_quality_baseline_update_refuses_coverage_decrease_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    previous_coverage = _coverage.build_quality_baseline(
        _coverage_evidence(fingerprints=[("old", True)]), 80.0
    )
    previous = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "typing": {"legacy_python_files": []},
        "coverage": previous_coverage,
    }
    _write_quality_baseline(tmp_path, previous)
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    before = path.read_bytes()
    monkeypatch.setattr(
        _ratchets,
        "collect_current",
        lambda _repo_root, _baseline: {"findings": [], "modules": {}, "python_files": []},
    )
    monkeypatch.setattr(
        _ratchets._coverage,
        "collect_quality_coverage",
        lambda _repo_root: _coverage_evidence(
            covered=0,
            statements=1,
            fingerprints=[("new", False)],
        ),
    )
    assert cli.main(["--update-quality-baseline", "--repo-root", str(tmp_path)]) == 1
    assert path.read_bytes() == before
    output = capsys.readouterr().out
    assert "quality baseline: refused -" in output
    assert "coverage/changed-lines" in output


def test_baseline_builder_cannot_drop_existing_coverage_policy() -> None:
    previous = {
        "coverage": _coverage.build_quality_baseline(_coverage_evidence(), 80.0),
        "typing": {"legacy_python_files": []},
    }

    with pytest.raises(_ratchets.QualityEvidenceError, match="current coverage evidence missing"):
        _ratchets.build_baseline({"findings": [], "modules": {}, "python_files": []}, previous)


def test_quality_check_cli_passes_unchanged_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence = {
        "findings": [_finding(symbol="legacy")],
        "modules": {"legacy.py": {"max_complexity": 12, "loc": 510}},
        "coverage": _coverage_evidence(),
    }
    _write_quality_baseline(tmp_path, _ratchets._bootstrap_quality_baseline_once(evidence))
    monkeypatch.setattr(
        _ratchets,
        "collect_current",
        lambda _repo_root, _baseline: {
            key: value for key, value in evidence.items() if key != "coverage"
        },
        raising=False,
    )
    monkeypatch.setattr(
        _ratchets._coverage,
        "collect_quality_coverage",
        lambda _repo_root: evidence["coverage"],
    )
    assert cli.main(["--quality-check", "--repo-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "quality: baseline current; no new or enlarged debt\n"


def test_quality_check_cli_separates_debt_and_stale_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = _finding(path="old.py", symbol="gone")
    current = {
        "findings": [_finding(rule="B007", path="new.py", symbol="item")],
        "modules": {},
    }
    baseline = {
        "schema_version": 2,
        "findings": [stale],
        "ceilings": {},
        "typing": {"legacy_python_files": []},
        "coverage": _coverage.build_quality_baseline(_coverage_evidence(), 80.0),
    }
    _write_quality_baseline(tmp_path, baseline)
    monkeypatch.setattr(
        _ratchets,
        "collect_current",
        lambda _repo_root, _baseline: current,
        raising=False,
    )
    monkeypatch.setattr(
        _ratchets._coverage,
        "collect_quality_coverage",
        lambda _repo_root: _coverage_evidence(),
    )

    assert cli.main(["--quality-check", "--repo-root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "quality: new-debt: new.py: ruff/B007 [item]" in output
    assert "quality: stale-baseline: old.py: ruff/F401 [gone]" in output
    assert "quality: 1 new/enlarged debt; 1 stale baseline entry" in output


def test_numeric_collection_ratchets_tests_and_scripts_with_safe_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_git
) -> None:
    large_test = tmp_path / "tests" / "test_legacy_large.py"
    large_test.parent.mkdir()
    large_test.write_text("# legacy test debt\n" * 501, encoding="utf-8")

    complex_script = tmp_path / "scripts" / "legacy_complex.py"
    complex_script.parent.mkdir()
    branches = "\n".join(f"    if value == {number}:\n        value += 1" for number in range(10))
    complex_script.write_text(
        f"def legacy(value):\n{branches}\n    return value\n",
        encoding="utf-8",
    )

    excluded_names = (".venv", ".worktrees", ".audit", ".pytest_cache")
    fixture_parents = (tmp_path, tmp_path / "tests")
    for parent, excluded in itertools.product(fixture_parents, excluded_names):
        ignored = parent / excluded / "ignored.py"
        ignored.parent.mkdir()
        ignored.write_text("# ignored\n" * 600, encoding="utf-8")

    repo_git(tmp_path, "init")
    repo_git(tmp_path, "add", "-A")
    repo_git(tmp_path, "commit", "-m", "fixture")

    analysis = {
        "findings": [],
        "per_file": {},
        "tool_status": {
            analyzer: {"ok": True} for analyzer in ("ruff", "vulture", "radon", "deps", "contracts")
        },
    }
    monkeypatch.setattr(_ratchets._graph, "build_graph", lambda _root, _inv: {})
    monkeypatch.setattr(
        _ratchets._analyze,
        "run_analysis",
        lambda _root, _inventory, _graph: analysis,
    )
    monkeypatch.setattr(_ratchets, "_run_policy_ruff", lambda _root: [])
    monkeypatch.setattr(_ratchets, "_run_policy_format", lambda _root, _files: {})
    monkeypatch.setattr(
        _ratchets,
        "_run_policy_pyright",
        lambda _root, _python_files, _legacy_python_files: [],
    )

    current = _ratchets.collect_current(tmp_path)

    assert set(current["modules"]) == {
        "scripts/legacy_complex.py",
        "tests/test_legacy_large.py",
    }
    assert current["modules"]["tests/test_legacy_large.py"] == {
        "loc": 501,
        "max_complexity": 0,
    }
    assert current["modules"]["scripts/legacy_complex.py"] == {
        "loc": 22,
        "max_complexity": 11,
    }

    baseline = _ratchets._bootstrap_quality_baseline_once(current)
    assert baseline["ceilings"] == {
        "tests/test_legacy_large.py": {"loc": 501},
    }
    assert baseline["complexity"] == {
        "scripts/legacy_complex.py": {"scripts.legacy_complex.legacy": 11}
    }

    new_debt = _ratchets.evaluate_ratchets(
        current,
        {
            "schema_version": 2,
            "findings": [],
            "ceilings": {},
            "complexity": {},
            "formatting": {},
        },
    )
    assert {(finding["path"], finding["rule"]) for finding in new_debt} == {
        ("scripts/legacy_complex.py", "CC"),
        ("tests/test_legacy_large.py", "LOC"),
    }

    enlarged = {
        "findings": [],
        "modules": {
            "scripts/legacy_complex.py": {"loc": 22, "max_complexity": 12},
            "tests/test_legacy_large.py": {"loc": 502, "max_complexity": 0},
        },
        "python_files": [
            "scripts/legacy_complex.py",
            "tests/test_legacy_large.py",
        ],
        "complexity": {
            "scripts/legacy_complex.py": {"scripts.legacy_complex.legacy": 12},
            "tests/test_legacy_large.py": {},
        },
        "formatting": {},
    }
    assert {
        (finding["path"], finding["kind"])
        for finding in _ratchets.evaluate_ratchets(enlarged, baseline)
    } == {
        ("scripts/legacy_complex.py", "enlarged-debt"),
        ("tests/test_legacy_large.py", "enlarged-debt"),
    }


def test_repository_python_records_excludes_git_untracked_files(
    synthetic_repo: Path,
) -> None:
    untracked = synthetic_repo / "plex_renamer" / "untracked.py"
    untracked.write_text("VALUE = 1\n", encoding="utf-8")

    records = _ratchets._repository_python_records(synthetic_repo)
    paths = {record["path"] for record in records}

    assert "plex_renamer/alpha.py" in paths
    assert "plex_renamer/untracked.py" not in paths


def test_policy_ruff_scans_explicit_repository_python_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def completed(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    monkeypatch.setattr(_ratchets.subprocess, "run", completed)

    assert _ratchets._run_policy_ruff(tmp_path) == []
    assert commands == [
        [
            _ratchets.sys.executable,
            "-m",
            "ruff",
            "check",
            "--output-format=json",
            "--no-cache",
            "plex_renamer",
            "tests",
            "scripts",
        ]
    ]


@pytest.mark.parametrize(
    "other",
    [
        "--fast",
        "--check",
        "--verify",
        "--with-coverage",
        "inventory",
    ],
)
def test_quality_check_is_mutually_exclusive_with_other_run_modes(
    other: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--quality-check", other])

    assert exc_info.value.code == 2
    assert "--quality-check cannot be combined" in capsys.readouterr().err


def test_quality_baseline_update_preserves_new_clean_file_as_nonlegacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    previous = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "typing": {"legacy_python_files": ["plex_renamer/legacy.py"]},
    }
    current = {
        "findings": [],
        "modules": {},
        "python_files": ["plex_renamer/legacy.py", "plex_renamer/new_clean.py"],
    }
    _write_quality_baseline(tmp_path, previous)

    def collect(_repo_root: Path, baseline: dict) -> dict:
        assert baseline["typing"] == previous["typing"]
        return current

    monkeypatch.setattr(_ratchets, "collect_current", collect)
    monkeypatch.setattr(
        _ratchets._coverage,
        "collect_quality_coverage",
        lambda _repo_root: _coverage_evidence(),
    )

    args = ["--update-quality-baseline", "--repo-root", str(tmp_path)]
    assert cli.main(args) == 0
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    first = path.read_bytes()
    updated = json.loads(first)
    assert updated["typing"] == {"legacy_python_files": ["plex_renamer/legacy.py"]}
    assert "plex_renamer/new_clean.py" not in updated["typing"]["legacy_python_files"]
    assert updated["coverage"] == _coverage.build_quality_baseline(_coverage_evidence(), 80.0)
    assert capsys.readouterr().out == (
        "quality baseline: updated - 0 findings; 0 ceilings; 1 legacy Python file\n"
    )

    assert cli.main(args) == 0
    assert path.read_bytes() == first


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"schema_version": 1, "findings": [], "ceilings": {}},
        "{not-json",
        "valid JSON, but not a baseline object",
    ],
)
def test_quality_baseline_update_fails_closed_without_supported_previous_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: dict | str | None,
) -> None:
    if payload is not None:
        path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
        if isinstance(payload, str):
            path.parent.mkdir(parents=True)
            serialized = json.dumps(payload) if payload.startswith("valid") else payload
            path.write_text(serialized, encoding="utf-8")
        else:
            _write_quality_baseline(tmp_path, payload)
        before = path.read_bytes()
    monkeypatch.setattr(
        _ratchets,
        "collect_current",
        lambda _repo_root, _baseline: pytest.fail("collection must not run without a baseline"),
    )

    assert cli.main(["--update-quality-baseline", "--repo-root", str(tmp_path)]) == 1
    assert "quality baseline: failed -" in capsys.readouterr().out
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    if payload is None:
        assert not path.exists()
    else:
        assert path.read_bytes() == before


@pytest.mark.parametrize(
    "other",
    ["--fast", "--check", "--verify", "--with-coverage", "--quality-check", "inventory"],
)
def test_quality_baseline_update_is_mutually_exclusive_with_other_run_modes(
    other: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--update-quality-baseline", other])

    assert exc_info.value.code == 2
    assert "--update-quality-baseline cannot be combined" in capsys.readouterr().err
