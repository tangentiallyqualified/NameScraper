"""Stage 5: merge graph + analysis + coverage into per-module metrics."""
from __future__ import annotations

from pathlib import Path

from . import _artifacts

COMPLEXITY_FLAG = 10
LOW_COVERAGE_FLAG = 50.0

DEAD_TIER_KEYS = (
    "high-confidence",
    "medium-confidence",
    "low-confidence",
    "test-referenced",
    "protected-or-ambiguous",
    "allowlisted",
)


def _coverage_provenance(coverage: dict) -> dict:
    """Keep coverage origin/trust evidence without duplicating bulky module data."""
    usable = (
        coverage.get("available") is True
        and coverage.get("stale") is False
        and not coverage.get("partial", False)
        and not coverage.get("failed", False)
    )
    return {
        "available": coverage.get("available", False),
        "usable": usable,
        "reason": coverage.get("reason"),
        "source": coverage.get("source"),
        "collected_at_commit": coverage.get("collected_at_commit"),
        "age_commits": coverage.get("age_commits"),
        "stale": coverage.get("stale"),
        "partial": coverage.get("partial", False),
        "failed": coverage.get("failed", False),
        "scope_id": coverage.get("scope_id"),
        "scope": coverage.get("scope"),
        "module_count": len(coverage.get("modules", {})),
    }


def _dead_tier(finding: dict) -> str:
    if finding.get("allowlisted"):
        return "allowlisted"
    assessment = finding.get("assessment")
    if assessment in {
        "high-confidence", "medium-confidence", "low-confidence", "test-referenced",
    }:
        return assessment
    return "protected-or-ambiguous"


def _dead_counts(findings: list[dict]) -> dict:
    tiers = {key: 0 for key in DEAD_TIER_KEYS}
    for finding in findings:
        tiers[_dead_tier(finding)] += 1
    candidates = sum(value for key, value in tiers.items() if key != "allowlisted")
    high = tiers["high-confidence"]
    return {
        "dead_candidates": candidates,
        "dead_high_confidence": high,
        # Compatibility: historically this meant every non-high candidate.
        "dead_low_confidence": candidates - high,
        "dead_medium_confidence": tiers["medium-confidence"],
        "dead_exact_low_confidence": tiers["low-confidence"],
        "dead_test_referenced": tiers["test-referenced"],
        "dead_protected_ambiguous": tiers["protected-or-ambiguous"],
        "dead_allowlisted": tiers["allowlisted"],
        "dead_tiers": tiers,
    }


def _unavailable_dead_counts() -> dict:
    return {
        "dead_candidates": None,
        "dead_high_confidence": None,
        "dead_low_confidence": None,
        "dead_medium_confidence": None,
        "dead_exact_low_confidence": None,
        "dead_test_referenced": None,
        "dead_protected_ambiguous": None,
        "dead_allowlisted": None,
        "dead_tiers": None,
    }


def build_metrics(inventory: dict, graph: dict, analysis: dict, coverage: dict) -> dict:
    by_path = {m["path"]: (name, m) for name, m in graph["modules"].items()}
    per_file = analysis.get("per_file", {})
    coverage_info = _coverage_provenance(coverage)
    cov_modules = coverage.get("modules", {}) if coverage_info["usable"] else {}
    tool_status = dict(analysis.get("tool_status", {}))
    radon_ok = tool_status.get("radon", {}).get("ok") is True
    vulture_status = tool_status.get("vulture")
    vulture_ok = isinstance(vulture_status, dict) and vulture_status.get("ok") is True

    dead_by_path: dict[str, list[dict]] = {}
    for f in analysis.get("findings", []):
        if f["category"] == "dead-code":
            dead_by_path.setdefault(f["path"], []).append(f)

    modules: dict[str, dict] = {}
    for rec in inventory["python_files"]:
        path = rec["path"]
        mod_name, mod = by_path.get(path, (None, {}))
        complexity = per_file.get(path, {})
        cov = cov_modules.get(path)
        dead = sorted(
            dead_by_path.get(path, []),
            key=lambda f: (f.get("line", 0), f.get("symbol") or "", f.get("assessment") or ""),
        )
        dead_counts = _dead_counts(dead) if vulture_ok else _unavailable_dead_counts()
        record = {
            "module": mod_name or path,
            "loc": rec["loc"],
            "sha256": rec["sha256"],
            "max_complexity": complexity.get("max_complexity") if radon_ok else None,
            "avg_complexity": complexity.get("avg_complexity") if radon_ok else None,
            "fan_in": mod.get("fan_in", 0),
            "fan_out": mod.get("fan_out", 0),
            "coverage_percent": cov["percent"] if cov else None,
            "coverage_statements": cov.get("statements") if cov else None,
            "coverage_covered": cov.get("covered") if cov else None,
            **dead_counts,
            "dead_evidence_usable": vulture_ok,
            "dead_symbols": [
                {
                    "symbol": f.get("symbol"),
                    "line": f.get("line"),
                    "assessment": f.get("assessment", "unassessed"),
                    "confidence": f.get("confidence"),
                }
                for f in dead
                if not f.get("allowlisted")
            ] if vulture_ok else None,
            "public_symbols": sum(1 for s in mod.get("symbols", []) if s["public"]),
        }
        flags = []
        if record["max_complexity"] is not None and record["max_complexity"] > COMPLEXITY_FLAG:
            flags.append("complexity")
        if record["coverage_percent"] is not None and record["coverage_percent"] < LOW_COVERAGE_FLAG:
            flags.append("low-coverage")
        if record["dead_candidates"]:
            flags.append("dead-code")
        record["flags"] = flags
        modules[path] = record

    covered = [m["coverage_percent"] for m in modules.values() if m["coverage_percent"] is not None]
    covered_statements = sum(m["coverage_covered"] or 0 for m in modules.values())
    total_statements = sum(m["coverage_statements"] or 0 for m in modules.values())
    statement_coverage = (
        round(100.0 * covered_statements / total_statements, 1)
        if total_statements else None
    )
    module_avg_coverage = round(sum(covered) / len(covered), 1) if covered else None
    all_dead = [
        finding
        for findings in dead_by_path.values()
        for finding in findings
    ]
    dead_headline = _dead_counts(all_dead) if vulture_ok else _unavailable_dead_counts()
    headline = {
        "files": len(modules),
        "total_loc": sum(m["loc"] for m in modules.values()),
        "statement_coverage": statement_coverage,
        "module_avg_coverage": module_avg_coverage,
        "avg_coverage": statement_coverage,
        **dead_headline,
        "dead_evidence_usable": vulture_ok,
        "cycles": len(graph.get("cycles", [])),
        "modules_over_complexity": (
            sum(1 for m in modules.values() if "complexity" in m["flags"])
            if radon_ok else None
        ),
        "coverage_stale": coverage.get("stale") if coverage.get("available") else None,
        "coverage_partial": coverage.get("partial") if coverage.get("available") else None,
        "coverage_failed": coverage.get("failed") if coverage.get("available") else None,
        "coverage_usable": coverage_info["usable"],
    }
    return {
        "modules": modules,
        "headline": headline,
        "coverage": coverage_info,
        "dead_code": {
            "usable": vulture_ok,
            "source": "vulture",
            "reason": (
                None if vulture_ok
                else (
                    vulture_status.get("reason")
                    if isinstance(vulture_status, dict) else "status missing"
                )
            ),
            "observed_findings": len(all_dead),
        },
        "tool_status": tool_status,
    }


def run(repo_root: Path, options) -> int:
    metrics = build_metrics(
        _artifacts.read_artifact(repo_root, "inventory"),
        _artifacts.read_artifact(repo_root, "graph"),
        _artifacts.read_artifact(repo_root, "analysis"),
        _artifacts.read_artifact(repo_root, "coverage"),
    )
    _artifacts.write_artifact(repo_root, "metrics", metrics)
    h = metrics["headline"]
    dead_summary = (
        f"{h['dead_high_confidence']} high-confidence dead symbols"
        if h.get("dead_evidence_usable") else "dead-code analysis unavailable"
    )
    print(f"metrics: {h['files']} modules, {h['total_loc']} LOC, {dead_summary}")
    return 0
