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
    assert set(a["tool_status"]) == {"ruff", "vulture", "radon"}
    assert all(v["ok"] for v in a["tool_status"].values())
