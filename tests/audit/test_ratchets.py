from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from audit import __main__ as cli
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


def test_unchanged_legacy_debt_passes_and_thresholds_are_explicit_policy() -> None:
    current = {
        "findings": [_finding(symbol="legacy_import")],
        "modules": {
            "plex_renamer/legacy.py": {"max_complexity": 12, "loc": 550},
        },
    }
    baseline = {
        "schema_version": 1,
        "findings": [_finding(symbol="legacy_import")],
        "ceilings": {
            "plex_renamer/legacy.py": {"max_complexity": 12, "loc": 550},
        },
    }

    assert evaluate_ratchets(current, baseline) == []

    with (REPO_ROOT / "scripts" / "audit" / "policy.toml").open("rb") as handle:
        policy = tomllib.load(handle)
    assert policy["quality"] == {
        "max_cyclomatic_complexity": 10,
        "max_python_file_loc": 500,
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


def test_increased_cyclomatic_complexity_is_enlarged_debt() -> None:
    path = "plex_renamer/complex.py"
    current = {
        "findings": [],
        "modules": {path: {"max_complexity": 13, "loc": 100}},
    }
    baseline = {
        "schema_version": 1,
        "findings": [],
        "ceilings": {path: {"max_complexity": 12}},
    }

    assert evaluate_ratchets(current, baseline) == [
        {
            "analyzer": "radon",
            "baseline": 12,
            "current": 13,
            "kind": "enlarged-debt",
            "message": "max_complexity increased from 12 to 13",
            "metric": "max_complexity",
            "path": path,
            "rule": "CC",
            "symbol": None,
        }
    ]


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


def test_baseline_normalization_and_order_are_deterministic() -> None:
    assert hasattr(_ratchets, "build_baseline")
    build_baseline = _ratchets.build_baseline
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
    }

    expected = {
        "schema_version": 1,
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
            "plex_renamer/alpha.py": {"max_complexity": 11},
            "plex_renamer/zeta.py": {"loc": 700},
        },
    }

    assert build_baseline(current) == expected
    assert (
        build_baseline(
            {
                "findings": list(reversed(current["findings"])),
                "modules": dict(reversed(current["modules"].items())),
            }
        )
        == expected
    )


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
    inventory = {
        "python_files": [
            {"path": "z.py", "loc": 20},
            {"path": "a.py", "loc": 10},
        ],
    }
    analysis = {
        "findings": [
            {
                **_finding(analyzer="vulture", rule="unused-function", path="z.py"),
                "source": "vulture",
                "category": "dead-code",
                "allowlisted": False,
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
            **_finding(rule="B007", path="a.py"),
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

    assert _ratchets.collect_current(tmp_path) == {
        "findings": [
            {"analyzer": "ruff", "path": "a.py", "rule": "B007", "symbol": None},
            {
                "analyzer": "vulture",
                "path": "z.py",
                "rule": "unused-function",
                "symbol": None,
            },
        ],
        "modules": {
            "a.py": {"max_complexity": 2, "loc": 10},
            "z.py": {"max_complexity": 3, "loc": 20},
        },
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
