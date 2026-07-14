from __future__ import annotations

from pathlib import Path

from audit import _toolchain
from audit import __main__ as cli


def _constraints(repo: Path, text: str) -> None:
    path = repo / "scripts" / "audit" / "constraints.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_validate_accepts_exact_installed_analyzer_versions(tmp_path: Path, monkeypatch):
    _constraints(
        tmp_path,
        "coverage==7.15.0\nradon==6.0.1\nruff==0.15.21\nvulture==2.16\n",
    )
    installed = {
        "coverage": "7.15.0",
        "radon": "6.0.1",
        "ruff": "0.15.21",
        "vulture": "2.16",
    }
    monkeypatch.setattr(_toolchain.metadata, "version", installed.__getitem__)

    assert _toolchain.validate(tmp_path) == []


def test_validate_reports_missing_pins_and_version_mismatches(tmp_path: Path, monkeypatch):
    _constraints(tmp_path, "coverage==7.15.0\nradon==6.0.1\nruff==0.15.21\n")
    installed = {"coverage": "7.14.0", "radon": "6.0.1", "ruff": "0.15.21"}
    monkeypatch.setattr(_toolchain.metadata, "version", installed.__getitem__)

    assert _toolchain.validate(tmp_path) == [
        "coverage version mismatch: installed 7.14.0, required 7.15.0",
        "missing exact analyzer constraint: vulture",
    ]


def test_local_generation_stops_before_stages_when_toolchain_is_incompatible(
    synthetic_repo: Path, monkeypatch, capsys
):
    ran = []
    monkeypatch.setattr(_toolchain, "validate", lambda _repo: ["ruff mismatch"])
    monkeypatch.setattr(cli, "STAGES", [("inventory", lambda _root, _options: ran.append(True) or 0)])

    assert cli.main(["--repo-root", str(synthetic_repo)]) == 1

    assert ran == []
    assert "audit toolchain incompatible: ruff mismatch" in capsys.readouterr().out
