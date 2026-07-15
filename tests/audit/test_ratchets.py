from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from audit import _ratchets
from audit._ratchets import evaluate_ratchets

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _coverage_evidence() -> dict:
    return {
        "input_digest": "a" * 64,
        "suite": "fast",
        "full_suite": True,
        "scope_id": "b" * 64,
        "files": {"plex_renamer/a.py": {"executable_lines": []}},
        "package_floors": {"plex_renamer": {"covered": 1, "statements": 1, "percent": 100.0}},
    }


def _ruff_item(
    filename: Path,
    *,
    row: int,
    rule: str = "F841",
    name: str = "unused-variable",
    message: str = "Local variable `value` is assigned to but never used",
) -> dict:
    return {
        "code": rule,
        "filename": str(filename),
        "location": {"row": row, "column": 5},
        "end_location": {"row": row, "column": 10},
        "message": message,
        "name": name,
    }


def test_unchanged_legacy_debt_passes_and_thresholds_are_explicit_policy() -> None:
    current = {
        "findings": [_finding(symbol="legacy_import")],
        "modules": {
            "plex_renamer/legacy.py": {"max_complexity": 12, "loc": 550},
        },
    }
    baseline = {
        "schema_version": 2,
        "findings": [_finding(symbol="legacy_import")],
        "ceilings": {
            "plex_renamer/legacy.py": {"max_complexity": 12, "loc": 550},
        },
        "typing": {"legacy_python_files": []},
    }

    assert evaluate_ratchets(current, baseline) == []

    with (REPO_ROOT / "scripts" / "audit" / "policy.toml").open("rb") as handle:
        policy = tomllib.load(handle)
    assert policy["quality"] == {
        "max_cyclomatic_complexity": 10,
        "max_python_file_loc": 500,
        "changed_line_min_percent": 80.0,
    }


def test_numeric_paths_are_normalized_before_comparison() -> None:
    current = {
        "findings": [],
        "modules": {
            r"plex_renamer\legacy.py": {"max_complexity": 12, "loc": 550},
        },
    }
    baseline = {
        "schema_version": 1,
        "findings": [],
        "ceilings": {
            "plex_renamer/legacy.py": {"max_complexity": 12, "loc": 550},
        },
    }

    assert evaluate_ratchets(current, baseline) == []


def test_new_lint_finding_is_new_debt() -> None:
    legacy = _finding(symbol="legacy_import")
    added = _finding(rule="B007", path="plex_renamer/new_work.py", symbol="item")
    current = {"findings": [legacy, added], "modules": {}}
    baseline = {"schema_version": 1, "findings": [legacy], "ceilings": {}}

    assert evaluate_ratchets(current, baseline) == [
        {
            "analyzer": "ruff",
            "baseline": None,
            "current": None,
            "kind": "new-debt",
            "message": "new ruff/B007 finding",
            "metric": None,
            "path": "plex_renamer/new_work.py",
            "rule": "B007",
            "symbol": "item",
        }
    ]


def test_duplicate_ruff_diagnostics_preserve_multiplicity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "plex_renamer" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "def work():\n    value = 1\n    value = 2\n",
        encoding="utf-8",
    )
    items = [
        _ruff_item(source, row=2),
        _ruff_item(source, row=3),
    ]
    monkeypatch.setattr(
        _ratchets.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 1, stdout=json.dumps(items), stderr=""
        ),
    )

    findings = _ratchets._run_policy_ruff(tmp_path)
    symbols = [finding["symbol"] for finding in findings]

    assert len(set(symbols)) == 2
    assert all(
        isinstance(symbol, str) and symbol.startswith("plex_renamer.sample.work::unused-variable::")
        for symbol in symbols
    )
    assert symbols[0].endswith("#1")
    assert symbols[1].endswith("#2")

    baseline_one = _ratchets._bootstrap_quality_baseline_once(
        {"findings": findings[:1], "modules": {}}
    )
    added = evaluate_ratchets(
        {"findings": findings, "modules": {}},
        baseline_one,
    )
    assert [(finding["kind"], finding["symbol"]) for finding in added] == [("new-debt", symbols[1])]

    baseline_two = _ratchets._bootstrap_quality_baseline_once({"findings": findings, "modules": {}})
    removed = evaluate_ratchets(
        {"findings": findings[:1], "modules": {}},
        baseline_two,
    )
    assert [(finding["kind"], finding["symbol"]) for finding in removed] == [
        ("stale-baseline", symbols[1])
    ]


def test_ruff_identity_ignores_line_only_shifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "plex_renamer" / "sample.py"
    source.parent.mkdir()
    calls = 0

    def shifted(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        leading = "\n" * (calls - 1)
        source.write_text(f"{leading}def work():\n    value = 1\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps([_ruff_item(source, row=calls + 1)]),
            stderr="",
        )

    monkeypatch.setattr(_ratchets.subprocess, "run", shifted)

    before = _ratchets._run_policy_ruff(tmp_path)
    after = _ratchets._run_policy_ruff(tmp_path)

    assert before[0]["symbol"] is not None
    assert before[0]["symbol"] == after[0]["symbol"]
    assert (
        evaluate_ratchets(
            {"findings": after, "modules": {}},
            _ratchets._bootstrap_quality_baseline_once({"findings": before, "modules": {}}),
        )
        == []
    )


def test_new_oversized_file_is_new_debt() -> None:
    path = "plex_renamer/new_large_module.py"
    current = {
        "findings": [],
        "modules": {path: {"max_complexity": 3, "loc": 501}},
    }
    baseline = {"schema_version": 1, "findings": [], "ceilings": {}}

    assert evaluate_ratchets(current, baseline) == [
        {
            "analyzer": "inventory",
            "baseline": None,
            "current": 501,
            "kind": "new-debt",
            "message": "new loc debt at 501",
            "metric": "loc",
            "path": path,
            "rule": "LOC",
            "symbol": None,
        }
    ]


def test_resolved_finding_requires_baseline_cleanup() -> None:
    resolved = _finding(symbol="removed_import")
    current = {"findings": [], "modules": {}}
    baseline = {"schema_version": 1, "findings": [resolved], "ceilings": {}}

    assert evaluate_ratchets(current, baseline) == [
        {
            "analyzer": "ruff",
            "baseline": None,
            "current": None,
            "kind": "stale-baseline",
            "message": "baseline ruff/F401 finding is no longer present",
            "metric": None,
            "path": "plex_renamer/legacy.py",
            "rule": "F401",
            "symbol": "removed_import",
        }
    ]


def test_stale_numeric_ceiling_requires_baseline_cleanup() -> None:
    path = "plex_renamer/shrunk.py"
    current = {
        "findings": [],
        "modules": {path: {"max_complexity": 4, "loc": 500}},
    }
    baseline = {
        "schema_version": 1,
        "findings": [],
        "ceilings": {path: {"loc": 550}},
    }

    assert evaluate_ratchets(current, baseline) == [
        {
            "analyzer": "inventory",
            "baseline": 550,
            "current": 500,
            "kind": "stale-baseline",
            "message": "baseline loc ceiling 550 is stale; current is 500",
            "metric": "loc",
            "path": path,
            "rule": "LOC",
            "symbol": None,
        }
    ]


@pytest.mark.parametrize(
    ("metric", "threshold", "analyzer", "rule"),
    [
        ("loc", 500, "inventory", "LOC"),
    ],
)
def test_numeric_ceiling_at_active_threshold_is_stale(
    metric: str, threshold: int, analyzer: str, rule: str
) -> None:
    path = "plex_renamer/resolved.py"
    current = {"findings": [], "modules": {path: {metric: threshold}}}
    baseline = {
        "schema_version": 1,
        "findings": [],
        "ceilings": {path: {metric: threshold}},
    }

    assert evaluate_ratchets(current, baseline) == [
        {
            "analyzer": analyzer,
            "baseline": threshold,
            "current": threshold,
            "kind": "stale-baseline",
            "message": (f"baseline {metric} ceiling {threshold} is stale; current is {threshold}"),
            "metric": metric,
            "path": path,
            "rule": rule,
            "symbol": None,
        }
    ]


def test_baseline_normalization_and_order_are_deterministic() -> None:
    assert hasattr(_ratchets, "build_baseline")
    build_baseline = _ratchets._bootstrap_quality_baseline_once
    current = {
        "findings": [
            _finding(rule="F841", path=r"plex_renamer\zeta.py", symbol="value"),
            _finding(analyzer="contracts", rule="forbidden-import", path="a.py", symbol=None),
            _finding(analyzer="contracts", rule="forbidden-import", path="a.py", symbol=None),
        ],
        "modules": {
            "plex_renamer/zeta.py": {"max_complexity": 10, "loc": 700},
            "plex_renamer/alpha.py": {"max_complexity": 11, "loc": 500},
            "plex_renamer/small.py": {"max_complexity": 2, "loc": 20},
        },
        "complexity": {
            "plex_renamer/alpha.py": {"plex_renamer.alpha.work": 11},
        },
        "formatting": {},
    }

    expected = {
        "schema_version": 2,
        "findings": [
            {
                "analyzer": "contracts",
                "path": "a.py",
                "rule": "forbidden-import",
                "symbol": None,
            },
            {
                "analyzer": "ruff",
                "path": "plex_renamer/zeta.py",
                "rule": "F841",
                "symbol": "value",
            },
        ],
        "ceilings": {
            "plex_renamer/zeta.py": {"loc": 700},
        },
        "complexity": {
            "plex_renamer/alpha.py": {"plex_renamer.alpha.work": 11},
        },
        "formatting": {},
        "typing": {"legacy_python_files": []},
    }

    assert build_baseline(current) == expected
    assert (
        build_baseline(
            {
                "findings": list(reversed(current["findings"])),
                "modules": dict(reversed(current["modules"].items())),
                "complexity": dict(reversed(current["complexity"].items())),
                "formatting": {},
            }
        )
        == expected
    )


@pytest.mark.parametrize(
    "current",
    [
        {"findings": [_finding(rule="B007")], "modules": {}, "python_files": []},
        {
            "findings": [_finding(analyzer="pyright", rule="reportUnknownVariableType")],
            "modules": {},
            "python_files": [],
        },
        {
            "findings": [],
            "modules": {"new.py": {"loc": 20}},
            "complexity": {"new.py": {"new.work": 11}},
            "python_files": [],
        },
        {
            "findings": [],
            "modules": {"new.py": {"max_complexity": 1, "loc": 501}},
            "python_files": [],
        },
        {
            "findings": [],
            "modules": {},
            "formatting": {"new.py": "sha256:new"},
            "python_files": [],
        },
    ],
    ids=["lint", "typing", "complexity", "loc", "formatting"],
)
def test_baseline_update_refuses_new_static_debt_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    current: dict,
) -> None:
    coverage = _coverage_evidence()
    previous = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "complexity": {},
        "formatting": {},
        "typing": {"legacy_python_files": []},
        "coverage": _ratchets._coverage.build_quality_baseline(coverage, 80.0),
    }
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(previous), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(_ratchets, "collect_current", lambda _root, _baseline: current)
    monkeypatch.setattr(_ratchets._coverage, "collect_quality_coverage", lambda _root: coverage)

    assert _ratchets.run_quality_baseline_update(tmp_path) == 1
    assert path.read_bytes() == before
    assert "quality baseline: refused -" in capsys.readouterr().out


def test_baseline_update_allows_stale_only_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coverage = _coverage_evidence()
    previous = {
        "schema_version": 2,
        "findings": [_finding(path="resolved.py")],
        "ceilings": {},
        "complexity": {},
        "formatting": {},
        "typing": {"legacy_python_files": []},
        "coverage": _ratchets._coverage.build_quality_baseline(coverage, 80.0),
    }
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(previous), encoding="utf-8")
    current = {"findings": [], "modules": {}, "python_files": []}
    monkeypatch.setattr(_ratchets, "collect_current", lambda _root, _baseline: current)
    monkeypatch.setattr(_ratchets._coverage, "collect_quality_coverage", lambda _root: coverage)

    assert _ratchets.run_quality_baseline_update(tmp_path) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["findings"] == []


def test_baseline_update_refuses_missing_existing_package_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    coverage = _coverage_evidence()
    previous = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "complexity": {},
        "formatting": {},
        "typing": {"legacy_python_files": []},
        "coverage": _ratchets._coverage.build_quality_baseline(coverage, 80.0),
    }
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(previous), encoding="utf-8")
    before = path.read_bytes()
    coverage["package_floors"] = {}
    coverage["source_packages"] = ["plex_renamer"]
    current = {"findings": [], "modules": {}, "python_files": []}
    monkeypatch.setattr(_ratchets, "collect_current", lambda _root, _baseline: current)
    monkeypatch.setattr(_ratchets._coverage, "collect_quality_coverage", lambda _root: coverage)

    assert _ratchets.run_quality_baseline_update(tmp_path) == 1
    assert path.read_bytes() == before
    assert "coverage/scope-incomplete" in capsys.readouterr().out
