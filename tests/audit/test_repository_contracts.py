"""Repository-specific architectural contract regressions."""

import json
from pathlib import Path

from audit import _analyze, _graph, _inventory

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_structured_audit_files_are_pinned_to_lf() -> None:
    attributes = {
        line.strip()
        for line in (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    }
    assert "*.json text eol=lf" in attributes
    assert "*.sarif text eol=lf" in attributes


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


def test_repository_has_no_new_enlarged_or_forbidden_dependency_cycles() -> None:
    inventory = _inventory.build_inventory(REPO_ROOT)
    graph = _graph.build_graph(REPO_ROOT, inventory)
    audit_dir = REPO_ROOT / "scripts" / "audit"
    contracts = (audit_dir / "contracts.toml").read_text(encoding="utf-8")
    baseline = (audit_dir / "cycle-baseline.json").read_text(encoding="utf-8")

    findings = _analyze._check_contracts(graph, contracts, baseline)

    blocking_rules = {"new-cycle", "enlarged-cycle", "forbidden-import"}
    assert [f for f in findings if f["rule"] in blocking_rules] == [], json.dumps(
        findings,
        indent=2,
    )
