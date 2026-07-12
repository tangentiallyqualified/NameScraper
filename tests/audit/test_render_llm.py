from __future__ import annotations

from pathlib import Path

from audit import _graph, _inventory, _metrics, _render_llm


def _rendered(repo: Path) -> dict[str, str]:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    analysis = {"findings": [], "per_file": {}, "tool_status": {}}
    coverage = {"available": False, "modules": {}}
    metrics = _metrics.build_metrics(inv, graph, analysis, coverage)
    return _render_llm.render(repo, inv, graph, metrics)


def test_index_lists_every_module_once(synthetic_repo: Path):
    out = _rendered(synthetic_repo)
    index = out["docs/audit/llm/INDEX.md"]
    assert index.count("alpha.py") == 1
    assert "Alpha module: scoring helpers." in index
    assert "regenerate: scripts\\audit.cmd" in index


def test_package_file_has_symbols_and_users(synthetic_repo: Path):
    out = _rendered(synthetic_repo)
    root = out["docs/audit/llm/root.md"]
    assert "used_function(value) -> int" in root
    assert "used by: plex_renamer.beta" in root
    assert "tests/test_alpha.py" in root  # test mapping


def test_missing_docstring_marked(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "bare.py").write_text("X = 1\n", encoding="utf-8")
    out = _rendered(synthetic_repo)
    assert "(no docstring)" in out["docs/audit/llm/INDEX.md"]


def test_run_writes_files(synthetic_repo: Path):
    from audit import _artifacts
    for stage in (_inventory, _graph):
        stage.run(synthetic_repo, None)
    _artifacts.write_artifact(synthetic_repo, "analysis",
                              {"findings": [], "per_file": {}, "tool_status": {}})
    _artifacts.write_artifact(synthetic_repo, "coverage", {"available": False, "modules": {}})
    _metrics.run(synthetic_repo, None)
    assert _render_llm.run(synthetic_repo, None) == 0
    assert (synthetic_repo / "docs" / "audit" / "llm" / "INDEX.md").exists()
