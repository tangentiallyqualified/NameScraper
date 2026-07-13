from __future__ import annotations

from pathlib import Path

from audit import _render_human


def test_replace_generated_preserves_curated_text():
    existing = (
        "# Map\n\nMy hand-written intro.\n\n"
        "<!-- audit:generated:start metrics -->\nold table\n<!-- audit:generated:end metrics -->\n\n"
        "My hand-written outro.\n"
    )
    merged = _render_human.replace_generated(existing, "metrics", "new table")
    assert "My hand-written intro." in merged
    assert "My hand-written outro." in merged
    assert "new table" in merged
    assert "old table" not in merged


def test_replace_generated_creates_section_when_missing():
    merged = _render_human.replace_generated(None, "metrics", "table v1")
    assert "audit:generated:start metrics" in merged
    assert "table v1" in merged


def _run_all_stages(repo: Path) -> None:
    from audit import _artifacts, _graph, _inventory, _metrics
    _inventory.run(repo, None)
    _graph.run(repo, None)
    _artifacts.write_artifact(repo, "analysis", {
        "findings": [{"source": "vulture", "path": "plex_renamer/alpha.py", "line": 9,
                      "symbol": "dead_function", "category": "dead-code",
                      "assessment": "high-confidence", "allowlisted": False,
                      "rule": "unused-function", "message": "unused function 'dead_function'",
                      "confidence": 60}],
        "per_file": {}, "tool_status": {}})
    _artifacts.write_artifact(repo, "coverage", {"available": False, "modules": {}})
    _metrics.run(repo, None)


def test_overview_contains_mermaid_and_dead_checklist(synthetic_repo: Path):
    _run_all_stages(synthetic_repo)
    assert _render_human.run(synthetic_repo, None) == 0
    overview = (synthetic_repo / "docs" / "audit" / "maps" / "overview.md").read_text(encoding="utf-8")
    assert "```mermaid" in overview
    assert "- [ ] `plex_renamer/alpha.py:9` dead_function" in overview
    assert "Vulture 60%" in overview
    assert "assessment: high-confidence" in overview


def test_rerun_preserves_curated_prose(synthetic_repo: Path):
    _run_all_stages(synthetic_repo)
    _render_human.run(synthetic_repo, None)
    overview_path = synthetic_repo / "docs" / "audit" / "maps" / "overview.md"
    content = overview_path.read_text(encoding="utf-8")
    overview_path.write_text("CURATED NOTE\n\n" + content, encoding="utf-8")
    _render_human.run(synthetic_repo, None)
    assert overview_path.read_text(encoding="utf-8").startswith("CURATED NOTE")


def test_replace_generated_appends_when_markers_absent():
    merged = _render_human.replace_generated("Just prose, no markers.", "metrics", "new table")
    assert merged.startswith("Just prose, no markers.")
    assert "audit:generated:start metrics" in merged
    assert "new table" in merged


def test_overview_shows_partial_coverage_reason(synthetic_repo: Path):
    graph = {"modules": {}}
    metrics = {
        "modules": {},
        "headline": {
            "files": 0, "total_loc": 0, "avg_coverage": None, "coverage_partial": True,
            "cycles": 0, "modules_over_complexity": 0, "dead_high_confidence": 0,
        },
    }
    analysis = {"findings": []}
    overview = _render_human.render_overview(synthetic_repo, graph, metrics, analysis)
    assert "n/a (partial coverage run ignored)" in overview


def _report_metrics(**overrides) -> dict:
    metrics = {
        "commit": "artifact123",
        "modules": {},
        "headline": {
            "files": 0, "total_loc": 0, "avg_coverage": None,
            "module_avg_coverage": None, "cycles": 0,
            "modules_over_complexity": 0, "dead_high_confidence": 0,
            "coverage_usable": False,
        },
        "coverage": {
            "available": False, "usable": False, "source": None,
            "collected_at_commit": None, "age_commits": None,
            "stale": False, "partial": False, "failed": False,
            "reason": "no data",
        },
        "tool_status": {
            tool: {"ok": True, "reason": None}
            for tool in ("ruff", "vulture", "radon", "deps", "contracts")
        },
    }
    metrics.update(overrides)
    return metrics


def test_overview_uses_artifact_commit_and_shows_analyzer_status(synthetic_repo: Path):
    overview = _render_human.render_overview(
        synthetic_repo, {"modules": {}}, _report_metrics(), {"findings": []}
    )
    assert "## Analyzer status" in overview
    assert "| vulture | available |" in overview
    assert "Generated at commit artifact123" in overview


def test_failed_analyzers_suppress_false_clean_and_zero_claims(synthetic_repo: Path):
    metrics = _report_metrics()
    for tool in ("vulture", "radon", "deps", "contracts"):
        metrics["tool_status"][tool] = {"ok": False, "reason": f"{tool} crashed"}
    overview = _render_human.render_overview(
        synthetic_repo, {"modules": {}}, metrics, {"findings": []}
    )
    assert "n/a (vulture unavailable)" in overview
    assert "n/a (radon unavailable)" in overview
    assert "None. Declared dependencies match imports" not in overview
    assert "No violations" not in overview
    assert "No dead-code candidates found" not in overview
    assert "deps analyzer did not complete" in overview
    assert "contracts analyzer did not complete" in overview
    assert "vulture analyzer did not complete" in overview


def test_failed_vulture_marks_every_empty_dead_tier_unavailable(synthetic_repo: Path):
    metrics = _report_metrics()
    metrics["tool_status"]["vulture"] = {"ok": False, "reason": "crashed"}
    metrics["dead_code"] = {
        "usable": False, "source": "vulture", "reason": "crashed",
        "observed_findings": 0,
    }

    overview = _render_human.render_overview(
        synthetic_repo, {"modules": {}}, metrics, {"findings": []}
    )
    dead_section = overview.split("## Dead-code review checklist", 1)[1]

    assert dead_section.count("_Dead-code evidence unavailable") == 5
    assert "_None._" not in dead_section


def test_dead_code_sections_are_confidence_ordered_and_show_evidence(synthetic_repo: Path):
    metrics = _report_metrics()
    findings = []
    examples = [
        ("z.py", "medium", "medium-confidence", False),
        ("a.py", "high", "high-confidence", False),
        ("b.py", "entry", "entrypoint", False),
        ("c.py", "tested", "test-referenced", False),
        ("d.py", "ignored", "low-confidence", True),
    ]
    for line, (path, symbol, assessment, allowlisted) in enumerate(examples, 1):
        findings.append({
            "category": "dead-code", "path": path, "line": line, "symbol": symbol,
            "assessment": assessment, "allowlisted": allowlisted,
            "allowlist_reason": "framework hook" if allowlisted else None,
            "confidence": 85 if assessment == "high-confidence" else 60,
            "production_references": ["plex_renamer.user"] if assessment == "entrypoint" else [],
            "test_references": ["tests/test_use.py"] if assessment == "test-referenced" else [],
        })
    overview = _render_human.render_overview(
        synthetic_repo, {"modules": {}}, metrics, {"findings": findings}
    )
    headings = [
        "### High confidence", "### Medium confidence", "### Protected or ambiguous",
        "### Test referenced", "### Allowlisted",
    ]
    positions = [overview.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "Vulture 85%; production refs: none; test refs: none" in overview
    assert "test refs: tests/test_use.py" in overview
    assert "allowlist: framework hook" in overview
    assert "- [x] `d.py:5` ignored" in overview


def test_least_covered_table_is_ordered_and_capped_at_ten(synthetic_repo: Path):
    modules = {
        f"plex_renamer/m{i:02}.py": {
            "coverage_percent": float(i), "coverage_statements": 10,
            "coverage_covered": i, "loc": 1, "max_complexity": 1, "fan_in": 0,
        }
        for i in range(12)
    }
    modules["plex_renamer/no_statements.py"] = {
        "coverage_percent": 0.0, "coverage_statements": 0,
        "coverage_covered": 0, "loc": 1, "max_complexity": 0, "fan_in": 0,
    }
    metrics = _report_metrics(modules=modules)
    metrics["coverage"].update({
        "available": True, "usable": True, "source": "imported",
        "collected_at_commit": "cov1234", "age_commits": 2, "reason": None,
    })
    metrics["headline"].update({"avg_coverage": 5.5, "module_avg_coverage": 5.5})
    overview = _render_human.render_overview(
        synthetic_repo, {"modules": {}}, metrics, {"findings": []}
    )
    least = overview.split("## Least-covered modules", 1)[1].split("## Largest modules", 1)[0]
    assert least.index("m00.py") < least.index("m09.py")
    assert "m09.py" in least
    assert "m10.py" not in least and "m11.py" not in least
    assert "no_statements.py" not in least
    assert "| usable | imported | cov1234 | 2 |" in overview


def test_stale_coverage_is_explicitly_ignored(synthetic_repo: Path):
    metrics = _report_metrics(modules={
        "plex_renamer/alpha.py": {
            "coverage_percent": None, "loc": 1, "max_complexity": 1, "fan_in": 0,
        },
    })
    metrics["coverage"].update({
        "available": True, "stale": True, "source": "imported",
        "collected_at_commit": "old1234", "age_commits": 99,
    })
    overview = _render_human.render_overview(
        synthetic_repo, {"modules": {}}, metrics, {"findings": []}
    )
    assert "| ignored | imported | old1234 | 99 | stale" in overview
    assert "Coverage evidence ignored: stale" in overview
