from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from audit import _graph, _inventory, _metrics, _render_code_index


def _rendered(
    repo: Path, *, analysis: dict | None = None, coverage: dict | None = None
) -> dict[str, str]:
    inv = _inventory.build_inventory(repo)
    graph = _graph.build_graph(repo, inv)
    analysis = analysis or {"findings": [], "per_file": {}, "tool_status": {}}
    coverage = coverage or {"available": False, "modules": {}}
    metrics = _metrics.build_metrics(inv, graph, analysis, coverage)
    return _render_code_index.render(repo, inv, graph, metrics, analysis)


def test_index_lists_every_module_once(synthetic_repo: Path):
    out = _rendered(synthetic_repo)
    assert all(path.startswith("docs/audit/code-index/") for path in out)
    assert all("/llm/" not in path for path in out)
    index = out["docs/audit/code-index/INDEX.md"]
    assert "# Code Index" in index
    assert index.count("alpha.py") == 1
    assert "Alpha module: scoring helpers." in index
    assert "regenerate: scripts\\audit.cmd" in index


def test_package_file_has_symbols_and_users(synthetic_repo: Path):
    out = _rendered(synthetic_repo)
    root = out["docs/audit/code-index/root.md"]
    assert "used_function(value) -> int" in root
    assert "used by: plex_renamer.beta" in root
    assert "tests/test_alpha.py" in root  # test mapping


def test_missing_docstring_marked(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "bare.py").write_text("X = 1\n", encoding="utf-8")
    out = _rendered(synthetic_repo)
    assert "(no docstring)" in out["docs/audit/code-index/INDEX.md"]


def test_public_symbol_missing_docstring_is_marked(synthetic_repo: Path):
    (synthetic_repo / "plex_renamer" / "bare.py").write_text(
        "def public_api() -> None:\n    pass\n",
        encoding="utf-8",
    )

    out = _rendered(synthetic_repo)

    detail = out["docs/audit/code-index/root.md"]
    assert "`public_api() -> None` — (no docstring)" in detail


def _make_junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")


def test_input_digest_stamps_every_output(synthetic_repo: Path, monkeypatch):
    inv = _inventory.build_inventory(synthetic_repo)
    graph = _graph.build_graph(synthetic_repo, inv)
    metrics = _metrics.build_metrics(
        inv,
        graph,
        {"findings": [], "per_file": {}, "tool_status": {}},
        {"available": False, "modules": {}},
    )
    metrics["input_digest"] = "abcdef123456" + "0" * 52
    monkeypatch.setattr(_render_code_index._artifacts, "current_commit", lambda _repo: "current999")
    out = _render_code_index.render(synthetic_repo, inv, graph, metrics)
    assert all("Generated from audit input abcdef123456" in text for text in out.values())
    assert all("current999" not in text for text in out.values())


def test_degraded_analyzer_warning_is_in_every_output(synthetic_repo: Path):
    analysis = {
        "findings": [],
        "per_file": {},
        "tool_status": {"radon": {"ok": False, "reason": "timed out"}},
    }
    out = _rendered(synthetic_repo, analysis=analysis)
    assert all("Analyzer `radon` unavailable (timed out)" in text for text in out.values())


def test_failed_vulture_warns_that_dead_counts_and_clean_claims_are_unavailable(
    synthetic_repo: Path,
):
    analysis = {
        "findings": [],
        "per_file": {},
        "tool_status": {"vulture": {"ok": False, "reason": "crashed"}},
    }

    out = _rendered(synthetic_repo, analysis=analysis)

    assert all("dead-code counts and clean claims are unavailable" in text for text in out.values())
    assert all("\u2020 dead" not in text for text in out.values())


def test_ignored_coverage_warning_is_in_every_output(synthetic_repo: Path):
    coverage = {
        "available": True,
        "stale": True,
        "partial": False,
        "failed": False,
        "modules": {"plex_renamer/alpha.py": {"statements": 10, "covered": 2, "percent": 20.0}},
    }
    out = _rendered(synthetic_repo, coverage=coverage)
    assert all("Coverage evidence ignored" in text for text in out.values())
    assert all("coverage percentages are omitted" in text for text in out.values())
    assert "cov 20%" not in out["docs/audit/code-index/INDEX.md"]


def test_dead_suffix_separates_confidence_tiers_and_keeps_legacy_fallback():
    record = {
        "flags": ["dead-code"],
        "dead_candidates": 6,
        "dead_tiers": {
            "high-confidence": 1,
            "medium-confidence": 2,
            "low-confidence": 0,
            "test-referenced": 1,
            "protected-or-ambiguous": 1,
            "allowlisted": 1,
        },
    }
    suffix = _render_code_index._flags_suffix(record)
    assert "high x1" in suffix and "medium x2" in suffix
    assert "test-referenced x1" in suffix and "protected/ambiguous x1" in suffix
    assert "allowlisted x1" in suffix
    legacy = _render_code_index._flags_suffix(
        {
            "flags": ["dead-code"],
            "dead_candidates": 6,
            "dead_high_confidence": 2,
        }
    )
    assert "dead x6" in legacy and "high" not in legacy


def test_run_writes_files(synthetic_repo: Path):
    from audit import _artifacts

    for stage in (_inventory, _graph):
        stage.run(synthetic_repo, None)
    _artifacts.write_artifact(
        synthetic_repo, "analysis", {"findings": [], "per_file": {}, "tool_status": {}}
    )
    _artifacts.write_artifact(synthetic_repo, "coverage", {"available": False, "modules": {}})
    _metrics.run(synthetic_repo, None)
    assert _render_code_index.run(synthetic_repo, None) == 0
    assert (synthetic_repo / "docs" / "audit" / "code-index" / "INDEX.md").exists()


def test_run_removes_stale_owned_outputs_and_preserves_unrelated_audit_files(synthetic_repo: Path):
    from audit import _artifacts

    for stage in (_inventory, _graph):
        stage.run(synthetic_repo, None)
    _artifacts.write_artifact(
        synthetic_repo, "analysis", {"findings": [], "per_file": {}, "tool_status": {}}
    )
    _artifacts.write_artifact(synthetic_repo, "coverage", {"available": False, "modules": {}})
    _metrics.run(synthetic_repo, None)

    audit_dir = synthetic_repo / "docs" / "audit"
    legacy_dir = audit_dir / "llm"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "INDEX.md").write_text("legacy index\n", encoding="utf-8")
    (legacy_dir / "root.md").write_text("legacy package\n", encoding="utf-8")
    code_index_dir = audit_dir / "code-index"
    code_index_dir.mkdir(parents=True)
    stale_page = code_index_dir / "obsolete.md"
    stale_page.write_text("obsolete package\n", encoding="utf-8")
    renderer_unowned = code_index_dir / "metadata.json"
    renderer_unowned.write_bytes(b'{"preserve": true}\n')
    unrelated = audit_dir / "operator-notes.txt"
    unrelated.write_bytes(b"keep these bytes: \\x00\\xff\n")

    assert _render_code_index.run(synthetic_repo, None) == 0

    assert not legacy_dir.exists()
    assert not stale_page.exists()
    assert renderer_unowned.read_bytes() == b'{"preserve": true}\n'
    assert unrelated.read_bytes() == b"keep these bytes: \\x00\\xff\n"


def test_stale_cleanup_never_descends_into_windows_junctions(synthetic_repo: Path):
    from audit import _artifacts

    for stage in (_inventory, _graph):
        stage.run(synthetic_repo, None)
    _artifacts.write_artifact(
        synthetic_repo, "analysis", {"findings": [], "per_file": {}, "tool_status": {}}
    )
    _artifacts.write_artifact(synthetic_repo, "coverage", {"available": False, "modules": {}})
    _metrics.run(synthetic_repo, None)
    outside = synthetic_repo / "outside-code-index"
    outside.mkdir()
    sentinel = outside / "obsolete.md"
    sentinel.write_bytes(b"outside sentinel\n")
    code_index = synthetic_repo / "docs" / "audit" / "code-index"
    code_index.mkdir(parents=True)
    junction = code_index / "outside"
    _make_junction(junction, outside)

    with pytest.raises(_render_code_index.UnsafeGeneratedOutputError, match="outside"):
        _render_code_index.run(synthetic_repo, None)

    assert sentinel.read_bytes() == b"outside sentinel\n"
    assert junction.exists()


def test_renderer_path_reparse_inspection_error_fails_closed(tmp_path: Path, monkeypatch):
    def denied(_path: Path):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "lstat", denied)

    assert _render_code_index._path_is_reparse(tmp_path / "opaque") is True


def test_run_reads_analysis_for_legacy_metrics_warning(synthetic_repo: Path):
    from audit import _artifacts

    for stage in (_inventory, _graph):
        stage.run(synthetic_repo, None)
    _artifacts.write_artifact(
        synthetic_repo,
        "analysis",
        {
            "findings": [],
            "per_file": {},
            "tool_status": {"vulture": {"ok": False, "reason": "not installed"}},
        },
    )
    _artifacts.write_artifact(
        synthetic_repo,
        "metrics",
        {
            "modules": {
                "plex_renamer/alpha.py": {
                    "module": "plex_renamer.alpha",
                    "public_symbols": 0,
                    "fan_in": 0,
                    "fan_out": 0,
                    "flags": [],
                    "dead_candidates": 0,
                },
            },
            "headline": {},
        },
    )
    assert _render_code_index.run(synthetic_repo, None) == 0
    index = (synthetic_repo / "docs" / "audit" / "code-index" / "INDEX.md").read_text(
        encoding="utf-8"
    )
    assert "Analyzer `vulture` unavailable (not installed)" in index
