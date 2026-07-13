"""Repository-specific architectural contract regressions."""

from pathlib import Path

from audit import _analyze, _graph, _inventory


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_engine_does_not_import_application_layer():
    inventory = _inventory.build_inventory(REPO_ROOT)
    graph = _graph.build_graph(REPO_ROOT, inventory)
    contracts = (REPO_ROOT / "scripts" / "audit" / "contracts.toml").read_text(
        encoding="utf-8",
    )
    findings = _analyze._check_contracts(graph, contracts)
    engine_to_app = [
        finding
        for finding in findings
        if finding["category"] == "layer-violation"
        and finding["symbol"].startswith("plex_renamer.app")
    ]
    assert engine_to_app == []
