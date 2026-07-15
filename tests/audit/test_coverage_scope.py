# pyright: strict, reportPrivateUsage=false

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from scripts import test_fast_runner
from scripts.audit import _artifacts, _coverage, _ratchets

Evidence = dict[str, object]
_collect = cast(
    Callable[[Path], Evidence],
    _coverage.collect_quality_coverage,  # pyright: ignore[reportUnknownMemberType]
)
_evaluate = cast(
    Callable[[Evidence, Evidence, float], Evidence],
    _coverage.evaluate_quality_coverage,  # pyright: ignore[reportUnknownMemberType]
)
_build_baseline = cast(
    Callable[[Evidence, Evidence], Evidence],
    _ratchets.build_baseline,  # pyright: ignore[reportUnknownMemberType]
)


def test_reordered_unique_executable_statements_are_both_changed() -> None:
    baseline: Evidence = {
        "executable_lines": {"plex_renamer/alpha.py": ["a#1", "b#1"]},
        "package_floors": {},
    }
    current: Evidence = {
        "files": {
            "plex_renamer/alpha.py": {
                "executable_lines": [
                    {"fingerprint": "b#1", "covered": False},
                    {"fingerprint": "a#1", "covered": False},
                ]
            }
        },
        "package_floors": {},
    }

    result = _evaluate(current, baseline, 80.0)

    assert result["changed_lines"] == {"covered": 0, "statements": 2, "percent": 0.0}
    assert cast(list[Evidence], result["violations"])[0]["kind"] == "changed-line-coverage"


def _scope(repo: Path) -> Evidence:
    qt_tests = test_fast_runner._discover_qt_tests(repo)
    return cast(
        Evidence,
        test_fast_runner._coverage_scope(  # pyright: ignore[reportUnknownMemberType]
            repo, [], list(qt_tests)
        ),
    )


def _scope_id(scope: Evidence) -> str:
    return test_fast_runner._scope_id(scope)  # pyright: ignore[reportUnknownMemberType]


def _make_coverage(repo: Path, *, include_source: bool = True) -> None:
    driver = repo / "_cov_driver.py"
    driver.write_text(
        "from plex_renamer.alpha import used_function\nused_function(3)\n", encoding="utf-8"
    )
    command = [sys.executable, "-m", "coverage", "run", f"--data-file={repo / '.coverage'}"]
    if include_source:
        command.append("--source=plex_renamer")
    subprocess.run([*command, str(driver)], cwd=repo, check=True, capture_output=True)
    scope = _scope(repo)
    (repo / ".coverage.meta.json").write_text(
        json.dumps(
            {
                "input_digest": _artifacts.input_digest(repo),
                "collected_at": "2026-07-12T00:00:00+00:00",
                "full_suite": True,
                "suite": "fast",
                "scope_id": _scope_id(scope),
                "scope": scope,
            }
        ),
        encoding="utf-8",
    )


def _update_meta(repo: Path, **updates: object) -> None:
    path = repo / ".coverage.meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.update(updates)
    if "scope" in updates and isinstance(meta.get("scope"), dict):
        meta["scope_id"] = _scope_id(cast(Evidence, meta["scope"]))
    path.write_text(json.dumps(meta), encoding="utf-8")


@pytest.mark.parametrize(
    "updates",
    [
        {"scope": None},
        {"scope_id": "forged"},
        {"suite": "slow"},
        {"pytest_args": ["-k", "focused"]},
        {"coverage_source": ["plex_renamer/engine"]},
    ],
)
def test_quality_coverage_rejects_incomplete_or_forged_scope(
    synthetic_repo: Path, updates: dict[str, object]
) -> None:
    _make_coverage(synthetic_repo)
    if "pytest_args" in updates or "coverage_source" in updates:
        meta = json.loads((synthetic_repo / ".coverage.meta.json").read_text(encoding="utf-8"))
        scope = dict(meta["scope"])
        scope.update(updates)
        updates = {"scope": scope}
    _update_meta(synthetic_repo, **updates)

    with pytest.raises(RuntimeError, match="coverage-scope-incomplete"):
        _collect(synthetic_repo)


def test_quality_coverage_rejects_truncated_executable_module_evidence(
    synthetic_repo: Path,
) -> None:
    _make_coverage(synthetic_repo, include_source=False)

    with pytest.raises(RuntimeError, match=r"coverage-scope-incomplete.*plex_renamer/beta\.py"):
        _collect(synthetic_repo)


def test_quality_coverage_allows_omitted_source_with_no_executable_statements(
    synthetic_repo: Path,
) -> None:
    empty = synthetic_repo / "plex_renamer" / "empty.py"
    empty.write_text("# intentionally no executable statements\n", encoding="utf-8")
    _make_coverage(synthetic_repo)

    evidence = _collect(synthetic_repo)
    modules = cast(dict[str, Evidence], evidence["modules"])

    assert modules["plex_renamer/empty.py"] == {
        "covered": 0,
        "covered_lines": [],
        "executable_lines": [],
        "percent": 100.0,
        "statements": 0,
    }


def test_real_baseline_refresh_keeps_sidecar_current_and_byte_identical(
    synthetic_repo: Path,
) -> None:
    _make_coverage(synthetic_repo)
    coverage = _collect(synthetic_repo)
    current: Evidence = {
        "findings": [],
        "modules": {},
        "python_files": [],
        "coverage": coverage,
    }
    previous: Evidence = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "typing": {"legacy_python_files": []},
    }
    first = _build_baseline(current, previous)
    path = synthetic_repo / "scripts" / "audit" / "quality-baseline.json"
    path.write_text(json.dumps(first, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    first_bytes = path.read_bytes()
    current["coverage"] = _collect(synthetic_repo)
    second = _build_baseline(current, first)
    path.write_text(json.dumps(second, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    assert path.read_bytes() == first_bytes


def test_existing_source_package_cannot_lose_its_baseline_floor() -> None:
    current: Evidence = {
        "files": {},
        "package_floors": {},
        "source_packages": ["plex_renamer"],
    }
    baseline: Evidence = {
        "executable_lines": {},
        "package_floors": {"plex_renamer": {"covered": 9, "statements": 10, "percent": 90.0}},
    }

    assert _evaluate(current, baseline, 80.0)["violations"] == [
        {
            "baseline": 90.0,
            "current": None,
            "kind": "coverage-scope-incomplete",
            "path": "plex_renamer",
        }
    ]


def test_removed_source_package_may_drop_its_baseline_floor() -> None:
    current: Evidence = {"files": {}, "package_floors": {}, "source_packages": []}
    baseline: Evidence = {
        "executable_lines": {},
        "package_floors": {
            "plex_renamer/removed": {"covered": 1, "statements": 1, "percent": 100.0}
        },
    }

    assert _evaluate(current, baseline, 80.0)["violations"] == []
