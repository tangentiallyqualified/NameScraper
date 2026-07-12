from __future__ import annotations

from pathlib import Path

from audit import _analyze, _graph, _inventory


def _analysis_for(repo: Path) -> dict:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    return _analyze.run_analysis(repo, inv, graph)


def test_ruff_finds_unused_import(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    hits = [f for f in a["findings"]
            if f["source"] == "ruff" and f["rule"] == "F401" and f["path"] == "plex_renamer/alpha.py"]
    assert hits and hits[0]["category"] == "unused-import"


def test_vulture_dead_function_high_confidence(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    dead = [f for f in a["findings"] if f["category"] == "dead-code" and f["symbol"] == "dead_function"]
    assert dead
    assert dead[0]["assessment"] == "high-confidence"  # zero graph fan-in


def test_used_function_not_high_confidence_dead(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    assert not [f for f in a["findings"]
                if f["category"] == "dead-code" and f["symbol"] == "used_function"
                and f["assessment"] == "high-confidence"]


def test_radon_flags_complex_function(synthetic_repo: Path):
    branches = "\n".join(f"    if value == {i}:\n        return {i}" for i in range(12))
    (synthetic_repo / "plex_renamer" / "twisty.py").write_text(
        f'"""Twisty."""\n\n\ndef twisty(value):\n{branches}\n    return -1\n', encoding="utf-8")
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


def test_tool_status_reported(synthetic_repo: Path):
    a = _analysis_for(synthetic_repo)
    assert set(a["tool_status"]) == {"ruff", "vulture", "radon", "deps"}
    assert all(v["ok"] for v in a["tool_status"].values())


PYPROJECT_FAKE = '''\
[project]
name = "mini"
dependencies = [
    "requests>=2.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
'''


def _dep_rules(repo: Path) -> set[tuple[str, str]]:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    a = _analyze.run_analysis(repo, inv, graph, pyproject_text=PYPROJECT_FAKE)
    return {(f["rule"], f["symbol"]) for f in a["findings"] if f["category"] == "dependency"}


def test_unused_and_undeclared_dependencies(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "uses_tomlkit.py").write_text(
        '"""Uses an undeclared package."""\nimport tomlkit\n', encoding="utf-8")
    rules = _dep_rules(synthetic_repo)
    assert ("unused-dependency", "requests") in rules
    assert ("undeclared-dependency", "tomlkit") in rules


def test_dev_dependency_in_prod(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "uses_pytest.py").write_text(
        '"""Imports a dev-only tool."""\nimport pytest\n', encoding="utf-8")
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
