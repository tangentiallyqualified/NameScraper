from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path

import pytest
from audit import __main__ as cli
from audit import _ratchets


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
    path.write_text(json.dumps(baseline), encoding="utf-8")


def test_quality_check_cli_passes_unchanged_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence = {
        "findings": [_finding(symbol="legacy")],
        "modules": {"legacy.py": {"max_complexity": 12, "loc": 510}},
    }
    _write_quality_baseline(tmp_path, _ratchets.build_baseline(evidence))
    monkeypatch.setattr(_ratchets, "collect_current", lambda _repo_root: evidence, raising=False)

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
    baseline = {"schema_version": 1, "findings": [stale], "ceilings": {}}
    _write_quality_baseline(tmp_path, baseline)
    monkeypatch.setattr(_ratchets, "collect_current", lambda _repo_root: current, raising=False)

    assert cli.main(["--quality-check", "--repo-root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "quality: new-debt: new.py: ruff/B007 [item]" in output
    assert "quality: stale-baseline: old.py: ruff/F401 [gone]" in output
    assert "quality: 1 new/enlarged debt; 1 stale baseline entry" in output


def test_current_collection_replaces_narrow_ruff_and_sorts_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "z.py").write_text("def unused():\n    pass\n", encoding="utf-8")
    inventory = {
        "python_files": [
            {"path": "z.py", "loc": 20},
            {"path": "a.py", "loc": 10},
        ],
    }
    analysis = {
        "findings": [
            {
                **_finding(
                    analyzer="vulture",
                    rule="unused-function",
                    path="z.py",
                    symbol="unused",
                ),
                "source": "vulture",
                "category": "dead-code",
                "allowlisted": False,
                "line": 1,
            },
            {
                **_finding(rule="F401", path="old-policy.py"),
                "source": "ruff",
                "category": "lint",
                "allowlisted": False,
            },
        ],
        "per_file": {
            "z.py": {"max_complexity": 3},
            "a.py": {"max_complexity": 2},
        },
        "tool_status": {
            analyzer: {"ok": True} for analyzer in ("ruff", "vulture", "radon", "deps", "contracts")
        },
    }
    expanded_ruff = [
        {
            **_finding(rule="B007", path="a.py", symbol="a::unused-loop-control-variable::#1"),
            "source": "ruff",
            "category": "lint",
            "allowlisted": False,
        }
    ]
    monkeypatch.setattr(_ratchets._inventory, "build_inventory", lambda _root: inventory)
    monkeypatch.setattr(_ratchets._graph, "build_graph", lambda _root, _inv: {})
    monkeypatch.setattr(
        _ratchets._analyze,
        "run_analysis",
        lambda _root, _inventory, _graph: analysis,
    )
    monkeypatch.setattr(_ratchets, "_run_policy_ruff", lambda _root: expanded_ruff)
    monkeypatch.setattr(
        _ratchets,
        "_repository_python_records",
        lambda _root: inventory["python_files"],
    )

    assert _ratchets.collect_current(tmp_path) == {
        "findings": [
            {
                "analyzer": "ruff",
                "path": "a.py",
                "rule": "B007",
                "symbol": "a::unused-loop-control-variable::#1",
            },
            {
                "analyzer": "vulture",
                "path": "z.py",
                "rule": "unused-function",
                "symbol": "z.unused#1",
            },
        ],
        "modules": {
            "a.py": {"max_complexity": 2, "loc": 10},
            "z.py": {"max_complexity": 3, "loc": 20},
        },
    }


def test_numeric_collection_ratchets_tests_and_scripts_with_safe_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    baseline = _ratchets.build_baseline(current)
    assert baseline["ceilings"] == {
        "scripts/legacy_complex.py": {"max_complexity": 11},
        "tests/test_legacy_large.py": {"loc": 501},
    }

    new_debt = _ratchets.evaluate_ratchets(
        current,
        {"schema_version": 1, "findings": [], "ceilings": {}},
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
    }
    assert {
        (finding["path"], finding["kind"])
        for finding in _ratchets.evaluate_ratchets(enlarged, baseline)
    } == {
        ("scripts/legacy_complex.py", "enlarged-debt"),
        ("tests/test_legacy_large.py", "enlarged-debt"),
    }


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


@pytest.mark.parametrize("other", ["--fast", "--check", "--verify", "--with-coverage", "inventory"])
def test_quality_check_is_mutually_exclusive_with_other_run_modes(
    other: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--quality-check", other])

    assert exc_info.value.code == 2
    assert "--quality-check cannot be combined" in capsys.readouterr().err
