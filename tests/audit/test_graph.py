from __future__ import annotations

import json
import textwrap
from pathlib import Path

from audit import _artifacts, _graph, _inventory

from scripts.audit import _analyze


def _graph_for(repo: Path) -> dict:
    return _graph.build_graph(repo, _inventory.build_inventory(repo))


def _write_module(repo: Path, name: str, *imports: str) -> None:
    body = [f'"""{name}."""', *(f"import {target}" for target in imports)]
    (repo / Path(*name.split("."))).with_suffix(".py").write_text(
        "\n".join(body) + "\n",
        encoding="utf-8",
    )


def _cycle_findings(graph: dict, baseline_cycles: list[dict]) -> list[dict]:
    baseline = json.dumps({"version": 1, "cycles": baseline_cycles})
    return [
        finding
        for finding in _analyze._check_contracts(graph, {}, baseline)
        if finding["rule"] in {"new-cycle", "enlarged-cycle"}
    ]


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
        '"""C1."""\nfrom plex_renamer import c2\n', encoding="utf-8"
    )
    (synthetic_repo / "plex_renamer" / "c2.py").write_text(
        '"""C2."""\nfrom plex_renamer import c1\n', encoding="utf-8"
    )
    g = _graph_for(synthetic_repo)
    assert g["cycles"] == [
        {
            "modules": ["plex_renamer.c1", "plex_renamer.c2"],
            "edges": [
                ["plex_renamer.c1", "plex_renamer.c2"],
                ["plex_renamer.c2", "plex_renamer.c1"],
            ],
        }
    ]


def test_cycle_ordering_is_stable_for_modules_edges_and_components(synthetic_repo: Path):
    _write_module(
        synthetic_repo,
        "plex_renamer.zed",
        "plex_renamer.middle",
        "plex_renamer.alpha_cycle",
    )
    _write_module(synthetic_repo, "plex_renamer.middle", "plex_renamer.zed")
    _write_module(synthetic_repo, "plex_renamer.alpha_cycle", "plex_renamer.zed")
    _write_module(synthetic_repo, "plex_renamer.yankee", "plex_renamer.xray")
    _write_module(synthetic_repo, "plex_renamer.xray", "plex_renamer.yankee")

    assert _graph_for(synthetic_repo)["cycles"] == [
        {
            "modules": [
                "plex_renamer.alpha_cycle",
                "plex_renamer.middle",
                "plex_renamer.zed",
            ],
            "edges": [
                ["plex_renamer.alpha_cycle", "plex_renamer.zed"],
                ["plex_renamer.middle", "plex_renamer.zed"],
                ["plex_renamer.zed", "plex_renamer.alpha_cycle"],
                ["plex_renamer.zed", "plex_renamer.middle"],
            ],
        },
        {
            "modules": ["plex_renamer.xray", "plex_renamer.yankee"],
            "edges": [
                ["plex_renamer.xray", "plex_renamer.yankee"],
                ["plex_renamer.yankee", "plex_renamer.xray"],
            ],
        },
    ]


def test_unchanged_legacy_cycle_matches_exact_baseline(synthetic_repo: Path):
    _write_module(synthetic_repo, "plex_renamer.c1", "plex_renamer.c2")
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c1")
    graph = _graph_for(synthetic_repo)

    assert _cycle_findings(graph, graph["cycles"]) == []


def test_new_cycle_is_reported_when_no_baseline_component_contains_it(synthetic_repo: Path):
    _write_module(synthetic_repo, "plex_renamer.c1", "plex_renamer.c2")
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c1")

    findings = _cycle_findings(_graph_for(synthetic_repo), [])

    assert [finding["rule"] for finding in findings] == ["new-cycle"]
    assert findings[0]["symbol"] == "plex_renamer.c1, plex_renamer.c2"


def test_cycle_that_adds_a_module_is_reported_as_enlarged(synthetic_repo: Path):
    _write_module(synthetic_repo, "plex_renamer.c1", "plex_renamer.c2")
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c3")
    _write_module(synthetic_repo, "plex_renamer.c3", "plex_renamer.c1")
    baseline = [
        {
            "modules": ["plex_renamer.c1", "plex_renamer.c2"],
            "edges": [
                ["plex_renamer.c1", "plex_renamer.c2"],
                ["plex_renamer.c2", "plex_renamer.c1"],
            ],
        }
    ]

    findings = _cycle_findings(_graph_for(synthetic_repo), baseline)

    assert [finding["rule"] for finding in findings] == ["enlarged-cycle"]


def test_cycle_with_same_members_and_new_internal_edge_is_reported_as_enlarged(
    synthetic_repo: Path,
):
    _write_module(
        synthetic_repo,
        "plex_renamer.c1",
        "plex_renamer.c2",
        "plex_renamer.c3",
    )
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c3")
    _write_module(synthetic_repo, "plex_renamer.c3", "plex_renamer.c1")
    baseline = [
        {
            "modules": ["plex_renamer.c1", "plex_renamer.c2", "plex_renamer.c3"],
            "edges": [
                ["plex_renamer.c1", "plex_renamer.c2"],
                ["plex_renamer.c2", "plex_renamer.c3"],
                ["plex_renamer.c3", "plex_renamer.c1"],
            ],
        }
    ]

    findings = _cycle_findings(_graph_for(synthetic_repo), baseline)

    assert [finding["rule"] for finding in findings] == ["enlarged-cycle"]


def test_cycle_that_shrinks_with_only_baseline_edges_is_allowed(synthetic_repo: Path):
    _write_module(synthetic_repo, "plex_renamer.c1", "plex_renamer.c2")
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c1")
    baseline = [
        {
            "modules": ["plex_renamer.c1", "plex_renamer.c2", "plex_renamer.c3"],
            "edges": [
                ["plex_renamer.c1", "plex_renamer.c2"],
                ["plex_renamer.c2", "plex_renamer.c1"],
                ["plex_renamer.c2", "plex_renamer.c3"],
                ["plex_renamer.c3", "plex_renamer.c1"],
            ],
        }
    ]

    assert _cycle_findings(_graph_for(synthetic_repo), baseline) == []


def test_shrunk_cycle_with_novel_edge_is_reported(synthetic_repo: Path):
    _write_module(synthetic_repo, "plex_renamer.c1", "plex_renamer.c2")
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c1")
    baseline = [
        {
            "modules": ["plex_renamer.c1", "plex_renamer.c2", "plex_renamer.c3"],
            "edges": [
                ["plex_renamer.c1", "plex_renamer.c2"],
                ["plex_renamer.c2", "plex_renamer.c3"],
                ["plex_renamer.c3", "plex_renamer.c1"],
            ],
        }
    ]

    findings = _cycle_findings(_graph_for(synthetic_repo), baseline)

    assert [finding["rule"] for finding in findings] == ["enlarged-cycle"]


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
    (synthetic_repo / "plex_renamer" / "__main__.py").write_text('"""Entry."""\n', encoding="utf-8")
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.__main__"]["entrypoint"] is True
    assert g["modules"]["plex_renamer.beta"]["entrypoint"] is False


def test_malformed_pyproject_schema_does_not_abort(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "__main__.py").write_text('"""Entry."""\n', encoding="utf-8")
    (synthetic_repo / "pyproject.toml").write_text('project = "not a table"\n', encoding="utf-8")
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.__main__"]["entrypoint"] is True
    assert g["modules"]["plex_renamer.beta"]["entrypoint"] is False


def test_effects_detected_for_mutating_module(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "mover.py").write_text(
        textwrap.dedent('''\
        """Mover."""
        import shutil
        import subprocess
        from pathlib import Path


        def relocate(src: Path, dst: Path) -> None:
            """Move a file."""
            shutil.move(str(src), str(dst))


        def cleanup(path: Path) -> None:
            """Delete a file."""
            path.unlink()


        def probe() -> None:
            """Spawn a process."""
            subprocess.run(["git", "status"], check=False)
    '''),
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.mover"]["effects"] == [
        "file-delete",
        "file-move",
        "subprocess",
    ]


def test_effects_write_env_network(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "writer.py").write_text(
        textwrap.dedent('''\
        """Writer."""
        import os
        import requests
        from pathlib import Path


        def save(path: Path, body: str) -> None:
            """Write output."""
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)


        def token() -> str:
            """Read config from environment."""
            return os.environ.get("TOKEN", "")
    '''),
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.writer"]["effects"] == ["env", "file-write", "network"]


def test_effects_empty_for_pure_module(synthetic_repo: Path):
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.beta"]["effects"] == []


def test_str_replace_not_flagged_as_file_move(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "parser.py").write_text(
        textwrap.dedent('''\
        """Parser."""


        def clean(name: str) -> str:
            """Normalize separators."""
            return name.replace(".", " ")
    '''),
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.parser"]["effects"] == []


def test_path_replace_still_flagged(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "swapper.py").write_text(
        textwrap.dedent('''\
        """Swapper."""
        from pathlib import Path


        def swap(a: Path, b: Path) -> None:
            """Replace b with a."""
            a.replace(b)
    '''),
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.swapper"]["effects"] == ["file-move"]


def test_reexport_through_init_attributes_origin(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "__init__.py").write_text(
        '"""Mini package."""\nfrom .alpha import used_function\n', encoding="utf-8"
    )
    (synthetic_repo / "plex_renamer" / "delta.py").write_text(
        '"""Delta."""\nfrom plex_renamer import used_function\n\n\n'
        'def go():\n    """Go."""\n    return used_function(2)\n',
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    alpha_syms = {s["name"]: s for s in g["modules"]["plex_renamer.alpha"]["symbols"]}
    assert "plex_renamer.delta" in alpha_syms["used_function"]["imported_by"]


def test_similarly_named_external_package_stays_external(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "epsilon.py").write_text(
        '"""Epsilon."""\nimport plex_renamerx\n', encoding="utf-8"
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.epsilon"]["imports"] == []
    assert g["modules"]["plex_renamer.epsilon"]["external_imports"] == ["plex_renamerx"]


def test_class_and_private_symbols(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "shapes.py").write_text(
        textwrap.dedent('''\
        """Shapes."""


        class Circle:
            """Round."""


        def _hidden():
            """Private."""
    '''),
        encoding="utf-8",
    )
    g = _graph_for(synthetic_repo)
    syms = {s["name"]: s for s in g["modules"]["plex_renamer.shapes"]["symbols"]}
    assert syms["Circle"]["kind"] == "class"
    assert syms["Circle"]["public"] is True
    assert syms["_hidden"]["public"] is False


def test_syntax_error_aborts_graph_with_path_and_line(synthetic_repo: Path):
    import pytest

    (synthetic_repo / "plex_renamer" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"plex_renamer/broken\.py:1"):
        _graph_for(synthetic_repo)


def test_cli_graph_syntax_error_is_hard_failure(synthetic_repo: Path, capsys):
    from audit import __main__ as cli

    (synthetic_repo / "plex_renamer" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    assert cli.main(["--repo-root", str(synthetic_repo)]) == 1
    out = capsys.readouterr().out
    assert "graph: failed" in out
    assert "plex_renamer/broken.py:1" in out


def test_from_pkg_import_submodule_is_module_edge(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "zeta.py").write_text(
        '"""Zeta."""\nfrom plex_renamer import alpha\n', encoding="utf-8"
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.zeta"]["imports"] == ["plex_renamer.alpha"]


def test_absolute_import_module_edge(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "eta.py").write_text(
        '"""Eta."""\nimport plex_renamer.alpha\n', encoding="utf-8"
    )
    g = _graph_for(synthetic_repo)
    assert g["modules"]["plex_renamer.eta"]["imports"] == ["plex_renamer.alpha"]


def test_new_cycle_sharing_one_module_with_unrelated_legacy_cycle_is_new(
    synthetic_repo: Path,
):
    _write_module(synthetic_repo, "plex_renamer.c1", "plex_renamer.c2")
    _write_module(synthetic_repo, "plex_renamer.c2", "plex_renamer.c1")
    _write_module(synthetic_repo, "plex_renamer.c3", "plex_renamer.c4")
    _write_module(synthetic_repo, "plex_renamer.c4", "plex_renamer.c3")
    baseline = [
        {
            "modules": ["plex_renamer.c2", "plex_renamer.c5"],
            "edges": [
                ["plex_renamer.c2", "plex_renamer.c5"],
                ["plex_renamer.c5", "plex_renamer.c2"],
            ],
        }
    ]

    findings = _cycle_findings(_graph_for(synthetic_repo), baseline)

    rules = sorted(finding["rule"] for finding in findings)
    assert rules == ["new-cycle", "new-cycle"]
