from __future__ import annotations

from pathlib import Path

from audit import _artifacts, _graph, _inventory


def _graph_for(repo: Path) -> dict:
    return _graph.build_graph(repo, _inventory.build_inventory(repo))


def test_import_edges_and_fan(synthetic_repo: Path):
    g = _graph_for(synthetic_repo)
    beta = g["modules"]["plex_renamer.beta"]
    assert beta["imports"] == ["plex_renamer.alpha"]
    assert g["modules"]["plex_renamer.alpha"]["fan_in"] == 1
    assert beta["fan_out"] == 1


def test_symbols_with_signature_and_imported_by(synthetic_repo: Path):
    g = _graph_for(synthetic_repo)
    alpha_syms = {s["name"]: s for s in g["modules"]["plex_renamer.alpha"]["symbols"]}
    used = alpha_syms["used_function"]
    assert used["signature"] == "used_function(value) -> int"
    assert used["doc"] == "Double a value."
    assert used["public"] is True
    assert used["imported_by"] == ["plex_renamer.beta"]
    assert alpha_syms["dead_function"]["imported_by"] == []


def test_relative_import_resolution(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "gamma.py").write_text(
        '"""Gamma."""\nfrom .alpha import used_function\n\n\ndef go():\n    return used_function(1)\n',
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.gamma"]["imports"] == ["plex_renamer.alpha"]


def test_cycle_detection(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "c1.py").write_text(
        '"""C1."""\nfrom plex_renamer import c2\n', encoding="utf-8")
    (synthetic_repo / "plex_renamer" / "c2.py").write_text(
        '"""C2."""\nfrom plex_renamer import c1\n', encoding="utf-8")
    g = _graph_for(synthetic_repo)
    assert any(set(c) == {"plex_renamer.c1", "plex_renamer.c2"} for c in g["cycles"])


def test_run_requires_inventory(synthetic_repo: Path):
    import pytest
    with pytest.raises(_artifacts.MissingArtifactError):
        _graph.run(synthetic_repo, None)


def test_run_writes_artifact(synthetic_repo: Path):
    _inventory.run(synthetic_repo, None)
    assert _graph.run(synthetic_repo, None) == 0
    data = _artifacts.read_artifact(synthetic_repo, "graph")
    assert "plex_renamer.alpha" in data["modules"]


def test_external_imports_captured(synthetic_repo: Path):
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.alpha"]["external_imports"] == ["json"]
    assert g["modules"]["plex_renamer.beta"]["external_imports"] == []


def test_external_imports_top_level_only(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "net.py").write_text(
        '"""Net."""\nimport urllib.request\nfrom collections import OrderedDict\n',
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.net"]["external_imports"] == ["collections", "urllib"]


def test_entrypoint_modules_flagged(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "__main__.py").write_text(
        '"""Entry."""\n\n\ndef main() -> None:\n    """Run."""\n    print("hi")\n',
        encoding="utf-8",
    )
    (synthetic_repo / "pyproject.toml").write_text(
        '[project]\nname = "mini"\nversion = "0"\n\n[project.scripts]\nmini = "plex_renamer.beta:run"\n',
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.__main__"]["entrypoint"] is True
    assert g["modules"]["plex_renamer.beta"]["entrypoint"] is True
    assert g["modules"]["plex_renamer.alpha"]["entrypoint"] is False


def test_no_pyproject_still_detects_dunder_main(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "__main__.py").write_text(
        '"""Entry."""\n', encoding="utf-8")
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.__main__"]["entrypoint"] is True
    assert g["modules"]["plex_renamer.beta"]["entrypoint"] is False


def test_malformed_pyproject_schema_does_not_abort(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "__main__.py").write_text(
        '"""Entry."""\n', encoding="utf-8")
    (synthetic_repo / "pyproject.toml").write_text(
        'project = "not a table"\n', encoding="utf-8")
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.__main__"]["entrypoint"] is True
    assert g["modules"]["plex_renamer.beta"]["entrypoint"] is False
