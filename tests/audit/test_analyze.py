from __future__ import annotations

import json
import subprocess
from pathlib import Path

from audit import _analyze, _artifacts, _graph, _inventory


def _analysis_for(repo: Path) -> dict:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    return _analyze.run_analysis(repo, inv, graph)


def test_ruff_finds_unused_import(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    hits = [
        f
        for f in a["findings"]
        if f["source"] == "ruff" and f["rule"] == "F401" and f["path"] == "plex_renamer/alpha.py"
    ]
    assert hits and hits[0]["category"] == "unused-import"


def test_ruff_decodes_json_as_strict_utf8(synthetic_repo: Path, monkeypatch) -> None:
    message = "Comment contains ambiguous \N{MULTIPLICATION SIGN} (MULTIPLICATION SIGN)."
    payload = [
        {
            "code": "RUF003",
            "filename": str(synthetic_repo / "plex_renamer" / "alpha.py"),
            "location": {"row": 1, "column": 1},
            "end_location": {"row": 1, "column": 2},
            "message": message,
        }
    ]
    captured: dict = {}

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(_analyze.subprocess, "run", fake_run)

    findings = _analyze._run_ruff(synthetic_repo)

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "strict"
    assert findings[0]["message"] == message


def test_vulture_dead_function_medium_confidence(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    dead = [
        f for f in a["findings"] if f["category"] == "dead-code" and f["symbol"] == "dead_function"
    ]
    assert dead
    assert dead[0]["confidence"] == 60
    assert dead[0]["assessment"] == "medium-confidence"
    assert dead[0]["production_references"] == []
    assert dead[0]["test_references"] == []


def test_dead_code_confidence_uses_reference_and_numeric_evidence():
    graph = {
        "modules": {
            "plex_renamer.alpha": {
                "path": "plex_renamer/alpha.py",
                "entrypoint": False,
                "symbols": [
                    {"name": "high", "imported_by": []},
                    {"name": "medium", "imported_by": []},
                    {"name": "low", "imported_by": []},
                    {"name": "production", "imported_by": ["z.consumer", "a.consumer"]},
                    {"name": "tested", "imported_by": []},
                ],
            },
            "plex_renamer.__main__": {
                "path": "plex_renamer/__main__.py",
                "entrypoint": True,
                "symbols": [{"name": "main", "imported_by": []}],
            },
        }
    }
    inventory = {
        "test_files": [
            {
                "path": "tests/test_z.py",
                "imports_symbols": ["plex_renamer.alpha.tested"],
            },
            {
                "path": "tests/test_a.py",
                "imports_symbols": ["plex_renamer.alpha.tested"],
            },
        ]
    }
    findings = [
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "high",
            "confidence": 80,
        },
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "medium",
            "confidence": 60,
        },
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "low",
            "confidence": 59,
        },
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "production",
            "confidence": 100,
        },
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "tested",
            "confidence": 100,
        },
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "unknown",
            "confidence": 100,
        },
        {
            "category": "dead-code",
            "path": "plex_renamer/__main__.py",
            "symbol": "main",
            "confidence": 100,
        },
    ]

    _analyze._assess_dead_code(findings, graph, inventory)
    by_symbol = {finding["symbol"]: finding for finding in findings}

    assert by_symbol["high"]["assessment"] == "high-confidence"
    assert by_symbol["medium"]["assessment"] == "medium-confidence"
    assert by_symbol["low"]["assessment"] == "low-confidence"
    assert by_symbol["production"]["assessment"] == "referenced"
    assert by_symbol["production"]["production_references"] == ["a.consumer", "z.consumer"]
    assert by_symbol["tested"]["assessment"] == "test-referenced"
    assert by_symbol["tested"]["test_references"] == ["tests/test_a.py", "tests/test_z.py"]
    assert by_symbol["unknown"]["assessment"] == "dynamic-or-unresolved"
    assert by_symbol["main"]["assessment"] == "entrypoint"


def test_assess_dead_code_inventory_remains_optional():
    findings = [
        {
            "category": "dead-code",
            "path": "plex_renamer/alpha.py",
            "symbol": "orphan",
            "confidence": 80,
        }
    ]
    graph = {
        "modules": {
            "plex_renamer.alpha": {
                "path": "plex_renamer/alpha.py",
                "entrypoint": False,
                "symbols": [{"name": "orphan", "imported_by": []}],
            }
        }
    }

    _analyze._assess_dead_code(findings, graph)

    assert findings[0]["assessment"] == "high-confidence"
    assert findings[0]["test_references"] == []


def test_used_function_not_high_confidence_dead(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    assert not [
        f
        for f in a["findings"]
        if f["category"] == "dead-code"
        and f["symbol"] == "used_function"
        and f["assessment"] == "high-confidence"
    ]


def test_radon_flags_complex_function(synthetic_repo: Path):
    branches = "\n".join(f"    if value == {i}:\n        return {i}" for i in range(12))
    (synthetic_repo / "plex_renamer" / "twisty.py").write_text(
        f'"""Twisty."""\n\n\ndef twisty(value):\n{branches}\n    return -1\n', encoding="utf-8"
    )
    a = _analysis_for(synthetic_repo)
    hits = [f for f in a["findings"] if f["category"] == "complexity" and f["symbol"] == "twisty"]
    assert hits
    assert a["per_file"]["plex_renamer/twisty.py"]["max_complexity"] > 10


def test_allowlist_marks_finding(synthetic_repo: Path):
    allow = 'ignore = [\n  { symbol = "dead_function", reason = "test allow" },\n]\n'
    a = _analysis_for(synthetic_repo)  # default allowlist: not allowlisted
    assert any(f["symbol"] == "dead_function" and not f["allowlisted"] for f in a["findings"])
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    a2 = _analyze.run_analysis(synthetic_repo, inv, graph, allowlist_text=allow)
    assert all(f["allowlisted"] for f in a2["findings"] if f["symbol"] == "dead_function")
    assert all(
        f["allowlist_reason"] == "test allow"
        for f in a2["findings"]
        if f["symbol"] == "dead_function"
    )
    assert all(
        f["allowlist_reason"] is None for f in a2["findings"] if f["symbol"] != "dead_function"
    )


def test_historical_allowlist_is_archive_only():
    allowlist_text = (Path(__file__).parents[2] / "scripts" / "audit" / "allowlist.toml").read_text(
        encoding="utf-8"
    )
    findings = [
        {
            "symbol": "REFRESHING_CACHE",
            "path": "plex_renamer/app/models/state_models.py",
        },
        {
            "symbol": "REFRESHING_CACHE",
            "path": "plex_renamer/elsewhere.py",
        },
    ]

    _analyze._apply_allowlist(findings, allowlist_text)

    assert [finding["allowlisted"] for finding in findings] == [False, False]
    assert all(finding["allowlist_reason"] is None for finding in findings)


def test_tool_status_reported(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    assert set(a["tool_status"]) == {"ruff", "vulture", "radon", "deps", "contracts"}
    assert all(v["ok"] for v in a["tool_status"].values())


PYPROJECT_FAKE = """\
[project]
name = "mini"
dependencies = [
    "requests>=2.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
"""


def _dep_rules(repo: Path) -> set[tuple[str, str]]:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    a = _analyze.run_analysis(repo, inv, graph, pyproject_text=PYPROJECT_FAKE)
    return {(f["rule"], f["symbol"]) for f in a["findings"] if f["category"] == "dependency"}


def test_unused_and_undeclared_dependencies(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "uses_tomlkit.py").write_text(
        '"""Uses an undeclared package."""\nimport tomlkit\n', encoding="utf-8"
    )
    rules = _dep_rules(synthetic_repo)
    assert ("unused-dependency", "requests") in rules
    assert ("undeclared-dependency", "tomlkit") in rules


def test_dev_dependency_in_prod(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "uses_pytest.py").write_text(
        '"""Imports a dev-only tool."""\nimport pytest\n', encoding="utf-8"
    )
    assert ("dev-dependency-in-prod", "pytest") in _dep_rules(synthetic_repo)


def test_stdlib_imports_not_flagged(synthetic_repo: Path):
    # alpha imports json (stdlib); it must not appear as undeclared
    assert not any(sym == "json" for _rule, sym in _dep_rules(synthetic_repo))


def test_missing_pyproject_is_ok(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    a = _analyze.run_analysis(synthetic_repo, inv, graph)  # no pyproject in synthetic repo
    assert a["tool_status"]["deps"]["ok"] is True
    assert not [f for f in a["findings"] if f["category"] == "dependency"]


def test_corrupt_pyproject_degrades_not_aborts(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    a = _analyze.run_analysis(synthetic_repo, inv, graph, pyproject_text="not = valid [ toml")
    assert a["tool_status"]["deps"]["ok"] is False
    assert a["tool_status"]["deps"]["reason"]
    assert not [f for f in a["findings"] if f["category"] == "dependency"]


CONTRACTS_FAKE = """\
[[forbid]]
from = "plex_renamer.beta"
to = "plex_renamer.alpha"
reason = "test rule"
"""


def test_contract_violation_reported(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    a = _analyze.run_analysis(synthetic_repo, inv, graph, contracts_text=CONTRACTS_FAKE)
    hits = [f for f in a["findings"] if f["category"] == "layer-violation"]
    assert len(hits) == 1
    assert hits[0]["path"] == "plex_renamer/beta.py"
    assert hits[0]["symbol"] == "plex_renamer.alpha"
    assert "test rule" in hits[0]["message"]
    assert a["tool_status"]["contracts"]["ok"] is True


def test_contract_not_violated_in_allowed_direction(synthetic_repo: Path):
    allowed = (
        '[[forbid]]\nfrom = "plex_renamer.alpha"\nto = "plex_renamer.beta"\nreason = "reverse"\n'
    )
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    a = _analyze.run_analysis(synthetic_repo, inv, graph, contracts_text=allowed)
    assert not [f for f in a["findings"] if f["category"] == "layer-violation"]


def test_corrupt_contracts_degrades_not_aborts(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    a = _analyze.run_analysis(synthetic_repo, inv, graph, contracts_text="not = valid [ toml")
    assert a["tool_status"]["contracts"]["ok"] is False
    assert a["tool_status"]["contracts"]["reason"]
    assert not [f for f in a["findings"] if f["category"] == "layer-violation"]


def test_dead_code_in_entrypoint_module_protected(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "__main__.py").write_text(
        '"""Entry."""\n\n\ndef orphan() -> None:\n    """Unused."""\n    print("x")\n',
        encoding="utf-8",
    )
    a = _analysis_for(synthetic_repo)
    hits = [f for f in a["findings"] if f["category"] == "dead-code" and f["symbol"] == "orphan"]
    assert hits and hits[0]["assessment"] == "entrypoint"


def test_ruff_exit1_empty_stdout_degrades(synthetic_repo: Path, monkeypatch):
    import subprocess as sp

    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)

    class _FakeResult:
        returncode = 1
        stdout = ""
        stderr = "ruff crashed before emitting JSON"

    monkeypatch.setattr(sp, "run", lambda *a, **k: _FakeResult())
    a = _analyze.run_analysis(synthetic_repo, inv, graph)
    assert a["tool_status"]["ruff"]["ok"] is False
    assert not [f for f in a["findings"] if f["source"] == "ruff"]


def test_run_returns_2_and_writes_artifact_when_tool_degrades(
    synthetic_repo: Path, monkeypatch, capsys
):
    _inventory.run(synthetic_repo, None)
    _graph.run(synthetic_repo, None)

    def _boom(repo_root):
        raise RuntimeError("ruff unavailable")

    monkeypatch.setattr(_analyze, "_run_ruff", _boom)
    assert _analyze.run(synthetic_repo, None) == 2
    data = _artifacts.read_artifact(synthetic_repo, "analysis")
    assert data["tool_status"]["ruff"]["ok"] is False
    assert "unavailable: ruff" in capsys.readouterr().out


def test_check_dependencies_empty_runtime():
    findings = _analyze._check_dependencies({"modules": {}}, '[project]\nname = "x"\n')
    assert findings == []
