# pyright: strict, reportPrivateUsage=false

"""CLI tests for the opt-in --accept-enlarged quality-baseline refresh flag."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from scripts.audit import __main__ as cli, _coverage, _ratchets

_main = cast(
    Callable[[list[str]], int],
    cli.main,  # pyright: ignore[reportUnknownMemberType]
)
_build_quality_baseline = cast(
    Callable[[dict[str, object], float], dict[str, object]],
    _coverage.build_quality_baseline,  # pyright: ignore[reportUnknownMemberType]
)


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

    result = _main(["--update-quality-baseline", "--accept-enlarged", "--repo-root", str(tmp_path)])

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


def test_accept_enlarged_requires_update_quality_baseline(tmp_path: Path) -> None:
    """Verify --accept-enlarged alone is rejected (requires --update-quality-baseline)."""
    with pytest.raises(SystemExit) as exc_info:
        _main(["--accept-enlarged", "--repo-root", str(tmp_path)])

    assert exc_info.value.code == 2
