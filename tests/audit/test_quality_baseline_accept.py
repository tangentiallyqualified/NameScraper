# pyright: strict, reportPrivateUsage=false

"""CLI tests for the opt-in --accept-enlarged quality-baseline refresh flag."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from scripts.audit import __main__ as cli, _coverage, _quality_refresh, _ratchets

_main = cast(
    Callable[[list[str]], int],
    cli.main,  # pyright: ignore[reportUnknownMemberType]
)
_build_quality_baseline = cast(
    Callable[[dict[str, object], float], dict[str, object]],
    _coverage.build_quality_baseline,  # pyright: ignore[reportUnknownMemberType]
)

EXPECTED_LOC = "inventory|LOC|plex_renamer/legacy.py"
EXPECTED_COVERAGE = "coverage|package-floor|plex_renamer"


def _coverage_evidence(covered: int = 2) -> dict[str, object]:
    return {
        "input_digest": "a" * 64,
        "suite": "full-coverage",
        "full_suite": True,
        "scope_id": "b" * 64,
        "files": {"plex_renamer/a.py": {"executable_lines": []}},
        "package_floors": {
            "plex_renamer": {
                "covered": covered,
                "statements": 2,
                "percent": round(100.0 * covered / 2, 1),
            }
        },
    }


def _write_enlarged_debt_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, bytes]:
    """Seed enlarged LOC (505 -> 510) plus a coverage-floor decrease (100.0 -> 50.0)."""
    previous: dict[str, object] = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {"plex_renamer/legacy.py": {"loc": 505}},
        "complexity": {},
        "formatting": {},
        "typing": {"legacy_python_files": []},
        "coverage": _build_quality_baseline(_coverage_evidence(covered=2), 80.0),
    }
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(previous), encoding="utf-8")
    current: dict[str, object] = {
        "findings": [],
        "modules": {"plex_renamer/legacy.py": {"loc": 510}},
        "python_files": [],
    }
    decreased = _coverage_evidence(covered=1)

    def _fake_collect_current(_root: Path, _baseline: dict[str, object]) -> dict[str, object]:
        return current

    def _fake_collect_quality_coverage(_root: Path) -> dict[str, object]:
        return decreased

    monkeypatch.setattr(_ratchets, "collect_current", _fake_collect_current)
    monkeypatch.setattr(_coverage, "collect_quality_coverage", _fake_collect_quality_coverage)
    return path, path.read_bytes()


def test_update_with_accept_enlarged_accepts_and_prints_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _before = _write_enlarged_debt_fixture(tmp_path, monkeypatch)

    result = _main(
        [
            "--update-quality-baseline",
            "--accept-enlarged",
            "--expect-enlarged",
            EXPECTED_LOC,
            "--expect-enlarged",
            EXPECTED_COVERAGE,
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 0
    refreshed = json.loads(path.read_text(encoding="utf-8"))
    assert refreshed["ceilings"] == {"plex_renamer/legacy.py": {"loc": 510}}
    assert refreshed["coverage"]["package_floors"]["plex_renamer"]["covered"] == 1
    output = capsys.readouterr().out
    assert (
        "quality baseline: accepted enlarged-debt: plex_renamer/legacy.py: "
        "inventory/LOC (505 -> 510)" in output
    )
    assert (
        "quality baseline: accepted enlarged-debt: plex_renamer: "
        "coverage/package-floor (100.0 -> 50.0)" in output
    )
    assert "quality baseline: accepted 2 new/enlarged debt entries" in output
    assert "quality baseline: updated -" in output


@pytest.mark.parametrize(
    ("expected", "message"),
    [
        ([EXPECTED_LOC], "unexpected debt: coverage|package-floor|plex_renamer"),
        (
            [EXPECTED_LOC, EXPECTED_COVERAGE, "ruff|F401|plex_renamer/extra.py"],
            "expected debt not produced: ruff|F401|plex_renamer/extra.py",
        ),
        ([EXPECTED_LOC, EXPECTED_LOC, EXPECTED_COVERAGE], "duplicate expectation"),
        (["inventory|LOC"], "malformed expectation"),
        (["|LOC|plex_renamer/legacy.py"], "malformed expectation: |LOC|plex_renamer/legacy.py"),
        (
            ["inventory||plex_renamer/legacy.py"],
            "malformed expectation: inventory||plex_renamer/legacy.py",
        ),
        (["inventory|LOC|"], "malformed expectation: inventory|LOC|"),
    ],
)
def test_accept_enlarged_requires_exact_expectations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    expected: list[str],
    message: str,
) -> None:
    path, before = _write_enlarged_debt_fixture(tmp_path, monkeypatch)
    args = ["--update-quality-baseline", "--accept-enlarged", "--repo-root", str(tmp_path)]
    for entry in expected:
        args.extend(["--expect-enlarged", entry])

    assert _main(args) == 1
    assert path.read_bytes() == before
    assert message in capsys.readouterr().out


def test_malformed_expectation_precedes_duplicate_expectation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, before = _write_enlarged_debt_fixture(tmp_path, monkeypatch)

    result = _main(
        [
            "--update-quality-baseline",
            "--accept-enlarged",
            "--expect-enlarged",
            EXPECTED_LOC,
            "--expect-enlarged",
            EXPECTED_LOC,
            "--expect-enlarged",
            "inventory|LOC",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert path.read_bytes() == before
    assert capsys.readouterr().out.splitlines()[0] == (
        "quality baseline: refused - malformed expectation: inventory|LOC"
    )


def test_unexpected_actual_debt_precedes_missing_expected_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, before = _write_enlarged_debt_fixture(tmp_path, monkeypatch)

    result = _main(
        [
            "--update-quality-baseline",
            "--accept-enlarged",
            "--expect-enlarged",
            EXPECTED_LOC,
            "--expect-enlarged",
            "ruff|F401|plex_renamer/extra.py",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert path.read_bytes() == before
    assert capsys.readouterr().out.splitlines()[0] == (
        "quality baseline: refused - unexpected debt: coverage|package-floor|plex_renamer"
    )


def test_accept_enlarged_refuses_an_extra_actual_duplicate_identity() -> None:
    violations: list[dict[str, object]] = [
        {
            "analyzer": "inventory",
            "rule": "LOC",
            "path": "plex_renamer/legacy.py",
            "kind": "enlarged-debt",
        },
        {
            "analyzer": "inventory",
            "rule": "LOC",
            "path": "plex_renamer/legacy.py",
            "kind": "enlarged-debt",
        },
    ]

    with pytest.raises(_quality_refresh.QualityBaselineRefused, match="unexpected debt"):
        _quality_refresh.gate_refresh_debt(violations, True, [EXPECTED_LOC])


def test_update_refuses_duplicate_collected_identity_with_single_expectation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    previous: dict[str, object] = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "complexity": {},
        "formatting": {},
        "typing": {"legacy_python_files": []},
        "coverage": _build_quality_baseline(_coverage_evidence(), 80.0),
    }
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(previous), encoding="utf-8")
    before = path.read_bytes()
    current: dict[str, object] = {
        "findings": [
            {
                "analyzer": "ruff",
                "rule": "F401",
                "path": "plex_renamer/legacy.py",
                "symbol": "first",
            },
            {
                "analyzer": "ruff",
                "rule": "F401",
                "path": "plex_renamer/legacy.py",
                "symbol": "second",
            },
        ],
        "modules": {},
        "python_files": [],
    }

    def _fake_collect_current(_root: Path, _baseline: dict[str, object]) -> dict[str, object]:
        return current

    def _fake_collect_quality_coverage(_root: Path) -> dict[str, object]:
        return _coverage_evidence()

    monkeypatch.setattr(_ratchets, "collect_current", _fake_collect_current)
    monkeypatch.setattr(_coverage, "collect_quality_coverage", _fake_collect_quality_coverage)

    result = _main(
        [
            "--update-quality-baseline",
            "--accept-enlarged",
            "--expect-enlarged",
            "ruff|F401|plex_renamer/legacy.py",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert path.read_bytes() == before
    assert "unexpected debt: ruff|F401|plex_renamer/legacy.py" in capsys.readouterr().out


def test_update_without_flag_still_refuses_enlarged_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, before = _write_enlarged_debt_fixture(tmp_path, monkeypatch)

    result = _main(["--update-quality-baseline", "--repo-root", str(tmp_path)])

    assert result == 1
    assert path.read_bytes() == before
    output = capsys.readouterr().out
    assert "quality baseline: refused -" in output
    assert "accepted" not in output


@pytest.mark.parametrize(
    "prerequisites",
    [
        [],
        ["--update-quality-baseline"],
        ["--accept-enlarged"],
    ],
)
def test_expect_enlarged_requires_accept_and_update(
    prerequisites: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main([*prerequisites, "--expect-enlarged", "inventory|LOC|plex_renamer/a.py"])

    assert exc_info.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1] == (
        "audit: error: --expect-enlarged requires --update-quality-baseline and --accept-enlarged"
    )


def test_accept_enlarged_requires_update_quality_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify --accept-enlarged alone is rejected (requires --update-quality-baseline)."""
    with pytest.raises(SystemExit) as exc_info:
        _main(["--accept-enlarged", "--repo-root", str(tmp_path)])

    assert exc_info.value.code == 2
    assert "--accept-enlarged requires --update-quality-baseline" in capsys.readouterr().err
