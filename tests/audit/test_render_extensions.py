from __future__ import annotations

from pathlib import Path

from audit import _analyze, _coverage, _graph, _inventory, _metrics, _render_human


def overview_for(repo: Path, **analysis_kwargs) -> str:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    analysis = _analyze.run_analysis(repo, inv, graph, **analysis_kwargs)
    cov = _coverage.collect_coverage(repo)
    metrics = _metrics.build_metrics(inv, graph, analysis, cov)
    return _render_human.render_overview(repo, graph, metrics, analysis)


def test_overview_lists_dependency_issues(synthetic_repo: Path):
    pyproject = '[project]\nname = "mini"\ndependencies = [\n    "requests>=2.28",\n]\n'
    text = overview_for(synthetic_repo, pyproject_text=pyproject)
    assert "## Dependency issues" in text
    assert "unused" in text and "requests" in text


def test_overview_dependency_section_clean_when_no_findings(synthetic_repo: Path):
    text = overview_for(synthetic_repo)  # no pyproject in synthetic repo
    assert "_None. Declared dependencies match imports._" in text


def test_overview_lists_layer_violations(synthetic_repo: Path):
    contracts = '[[forbid]]\nfrom = "plex_renamer.beta"\nto = "plex_renamer.alpha"\nreason = "layering"\n'
    text = overview_for(synthetic_repo, contracts_text=contracts)
    assert "## Layer contracts" in text
    assert "forbidden by contract" in text


def test_overview_effects_table(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "mut.py").write_text(
        '"""Mut."""\nimport shutil\n\n\ndef go(a, b):\n    """Move."""\n    shutil.move(a, b)\n',
        encoding="utf-8",
    )
    text = overview_for(synthetic_repo)
    assert "## External effects" in text
    assert "| `plex_renamer/mut.py` | file-move |" in text
