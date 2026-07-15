"""Repository-specific architectural contract regressions."""

import json
from pathlib import Path

from audit import _analyze, _graph, _inventory, _render_human

REPO_ROOT = Path(__file__).resolve().parents[2]

_SETTINGS_MODULE_PREFIX = "plex_renamer.gui_qt.widgets."
_SETTINGS_AUTOMUX_PAGE = f"{_SETTINGS_MODULE_PREFIX}_settings_automux_page"
_SETTINGS_METADATA_PAGE = f"{_SETTINGS_MODULE_PREFIX}_settings_metadata_page"
_SETTINGS_PAGE_COMPONENTS = f"{_SETTINGS_MODULE_PREFIX}_settings_page"
_SETTINGS_SECTIONS = f"{_SETTINGS_MODULE_PREFIX}_settings_tab_sections"

_LEGACY_SETTINGS_PAGE_CYCLE = {
    "modules": [
        _SETTINGS_AUTOMUX_PAGE,
        _SETTINGS_METADATA_PAGE,
        _SETTINGS_SECTIONS,
    ],
    "edges": [
        [_SETTINGS_AUTOMUX_PAGE, _SETTINGS_SECTIONS],
        [_SETTINGS_METADATA_PAGE, _SETTINGS_SECTIONS],
        [_SETTINGS_SECTIONS, _SETTINGS_AUTOMUX_PAGE],
        [_SETTINGS_SECTIONS, _SETTINGS_METADATA_PAGE],
    ],
}


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


def test_engine_cycle_edge_classifications_cover_the_live_scc_exactly() -> None:
    inventory = _inventory.build_inventory(REPO_ROOT)
    graph = _graph.build_graph(REPO_ROOT, inventory)

    classifications = _render_human.load_cycle_edge_classifications(REPO_ROOT, graph)
    engine_edges = [list(edge) for edge in _render_human._engine_cycle_edges(graph)]

    assert [
        [record["source"], record["target"]]
        for record in classifications
    ] == engine_edges


def test_settings_page_composer_has_one_way_dependencies() -> None:
    inventory = _inventory.build_inventory(REPO_ROOT)
    graph = _graph.build_graph(REPO_ROOT, inventory)

    assert _LEGACY_SETTINGS_PAGE_CYCLE not in graph["cycles"]

    settings_modules = {
        _SETTINGS_AUTOMUX_PAGE,
        _SETTINGS_METADATA_PAGE,
        _SETTINGS_PAGE_COMPONENTS,
        _SETTINGS_SECTIONS,
    }
    settings_edges = sorted(
        [module, imported]
        for module in settings_modules
        for imported in graph["modules"][module]["imports"]
        if imported in settings_modules
    )
    assert settings_edges == [
        [_SETTINGS_AUTOMUX_PAGE, _SETTINGS_PAGE_COMPONENTS],
        [_SETTINGS_METADATA_PAGE, _SETTINGS_PAGE_COMPONENTS],
        [_SETTINGS_SECTIONS, _SETTINGS_AUTOMUX_PAGE],
        [_SETTINGS_SECTIONS, _SETTINGS_METADATA_PAGE],
        [_SETTINGS_SECTIONS, _SETTINGS_PAGE_COMPONENTS],
    ]
