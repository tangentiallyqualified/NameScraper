"""Stage 5: merge graph + analysis + coverage into per-module metrics."""
from __future__ import annotations

from pathlib import Path

from . import _artifacts

COMPLEXITY_FLAG = 10
LOW_COVERAGE_FLAG = 50.0


def build_metrics(inventory: dict, graph: dict, analysis: dict, coverage: dict) -> dict:
    by_path = {m["path"]: (name, m) for name, m in graph["modules"].items()}
    per_file = analysis.get("per_file", {})
    cov_modules = coverage.get("modules", {}) if coverage.get("available") else {}

    dead_by_path: dict[str, list[dict]] = {}
    for f in analysis.get("findings", []):
        if f["category"] == "dead-code" and not f.get("allowlisted"):
            dead_by_path.setdefault(f["path"], []).append(f)

    modules: dict[str, dict] = {}
    for rec in inventory["python_files"]:
        path = rec["path"]
        mod_name, mod = by_path.get(path, (None, {}))
        complexity = per_file.get(path, {})
        cov = cov_modules.get(path)
        dead = dead_by_path.get(path, [])
        dead_high = sum(1 for f in dead if f.get("assessment") == "high-confidence")
        record = {
            "module": mod_name or path,
            "loc": rec["loc"],
            "sha256": rec["sha256"],
            "max_complexity": complexity.get("max_complexity", 0),
            "avg_complexity": complexity.get("avg_complexity", 0.0),
            "fan_in": mod.get("fan_in", 0),
            "fan_out": mod.get("fan_out", 0),
            "coverage_percent": cov["percent"] if cov else None,
            "dead_candidates": len(dead),
            "dead_high_confidence": dead_high,
            "public_symbols": sum(1 for s in mod.get("symbols", []) if s["public"]),
        }
        flags = []
        if record["max_complexity"] > COMPLEXITY_FLAG:
            flags.append("complexity")
        if record["coverage_percent"] is not None and record["coverage_percent"] < LOW_COVERAGE_FLAG:
            flags.append("low-coverage")
        if record["dead_candidates"]:
            flags.append("dead-code")
        record["flags"] = flags
        modules[path] = record

    covered = [m["coverage_percent"] for m in modules.values() if m["coverage_percent"] is not None]
    headline = {
        "files": len(modules),
        "total_loc": sum(m["loc"] for m in modules.values()),
        "avg_coverage": round(sum(covered) / len(covered), 1) if covered else None,
        "dead_high_confidence": sum(m["dead_high_confidence"] for m in modules.values()),
        "dead_low_confidence": sum(m["dead_candidates"] - m["dead_high_confidence"] for m in modules.values()),
        "cycles": len(graph.get("cycles", [])),
        "modules_over_complexity": sum(1 for m in modules.values() if "complexity" in m["flags"]),
        "coverage_stale": coverage.get("stale") if coverage.get("available") else None,
    }
    return {"modules": modules, "headline": headline}


def run(repo_root: Path, options) -> int:
    metrics = build_metrics(
        _artifacts.read_artifact(repo_root, "inventory"),
        _artifacts.read_artifact(repo_root, "graph"),
        _artifacts.read_artifact(repo_root, "analysis"),
        _artifacts.read_artifact(repo_root, "coverage"),
    )
    _artifacts.write_artifact(repo_root, "metrics", metrics)
    h = metrics["headline"]
    print(f"metrics: {h['files']} modules, {h['total_loc']} LOC, "
          f"{h['dead_high_confidence']} high-confidence dead symbols")
    return 0
