"""Stage 6b: human-readable maps with generated/curated marker sections."""
from __future__ import annotations

import re
from pathlib import Path

from . import _artifacts

_package_of = _artifacts.package_of

START = "<!-- audit:generated:start {name} -->"
END = "<!-- audit:generated:end {name} -->"

KNOWN_TOOLS = ("ruff", "vulture", "radon", "deps", "contracts")
DEAD_SECTIONS = (
    ("High confidence", {"high-confidence"}),
    ("Medium confidence", {"medium-confidence"}),
    ("Protected or ambiguous", {
        "entrypoint", "dynamic-or-unresolved", "referenced", "low-confidence", "unassessed",
    }),
    ("Test referenced", {"test-referenced"}),
)


def replace_generated(existing: str | None, section: str, body: str) -> str:
    start = START.format(name=section)
    end = END.format(name=section)
    block = f"{start}\n{body.rstrip()}\n{end}"
    if existing and start in existing and end in existing:
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        return pattern.sub(lambda _m: block, existing, count=1)
    if existing:
        return existing.rstrip() + "\n\n" + block + "\n"
    return block + "\n"


def _mermaid_packages(graph: dict) -> str:
    edges: set[tuple[str, str]] = set()
    for mod in graph["modules"].values():
        src = _package_of(mod["path"])
        for target in mod["imports"]:
            dst = _package_of(graph["modules"][target]["path"])
            if src != dst:
                edges.add((src, dst))
    lines = ["```mermaid", "graph LR"]
    packages = sorted({_package_of(m["path"]) for m in graph["modules"].values()})
    lines += [f"    {p}" for p in packages]
    lines += [f"    {a} --> {b}" for a, b in sorted(edges)]
    lines.append("```")
    return "\n".join(lines)


def _top10(metrics: dict, key: str, reverse: bool = True) -> list[str]:
    items = [(path, rec) for path, rec in metrics["modules"].items() if rec.get(key) is not None]
    items.sort(key=lambda kv: kv[1][key], reverse=reverse)
    return [f"| `{path}` | {rec[key]} |" for path, rec in items[:10]]


def _tool_status(metrics: dict, tool: str) -> dict:
    status = metrics.get("tool_status", {}).get(tool)
    if not isinstance(status, dict):
        return {"ok": False, "reason": "status missing from analysis artifact"}
    if status.get("ok") is not True:
        return {"ok": False, "reason": status.get("reason") or "no reason recorded"}
    return {"ok": True, "reason": None}


def _unavailable(metrics: dict, tool: str) -> str:
    reason = _tool_status(metrics, tool)["reason"]
    return f"_Unavailable: {tool} analyzer did not complete ({reason})._"


def _analyzer_status(metrics: dict) -> str:
    statuses = metrics.get("tool_status", {})
    tools = list(KNOWN_TOOLS) + sorted(set(statuses) - set(KNOWN_TOOLS))
    rows = []
    for tool in tools:
        status = _tool_status(metrics, tool)
        label = "available" if status["ok"] else "unavailable"
        detail = status["reason"] or "-"
        rows.append(f"| {tool} | {label} | {detail} |")
    return "| Analyzer | Status | Detail |\n|---|---|---|\n" + "\n".join(rows)


def _reference_evidence(finding: dict) -> str:
    production = ", ".join(finding.get("production_references", [])) or "none"
    tests = ", ".join(finding.get("test_references", [])) or "none"
    confidence = finding.get("confidence")
    confidence_text = f"{confidence}%" if confidence is not None else "unknown"
    return (
        f"Vulture {confidence_text}; production refs: {production}; test refs: {tests}; "
        f"assessment: {finding.get('assessment', 'unassessed')}"
    )


def _dead_line(finding: dict, checkable: bool = True) -> str:
    check = "[x] " if finding.get("allowlisted") else ("[ ] " if checkable else "")
    suffix = _reference_evidence(finding)
    if finding.get("allowlisted"):
        suffix += f"; allowlist: {finding.get('allowlist_reason') or 'no reason recorded'}"
    return (
        f"- {check}`{finding['path']}:{finding['line']}` {finding.get('symbol') or '(unknown)'} "
        f"({suffix})"
    )


def _dead_checklist(analysis: dict, metrics: dict) -> str:
    findings = [f for f in analysis.get("findings", []) if f["category"] == "dead-code"]
    parts = []
    dead_usable = (
        _tool_status(metrics, "vulture")["ok"]
        and metrics.get("dead_code", {}).get("usable", True) is not False
    )
    unavailable = "_Dead-code evidence unavailable; no clean conclusion can be drawn._"
    if not dead_usable:
        parts.append(_unavailable(metrics, "vulture") + " Any findings below are incomplete evidence.")

    for title, assessments in DEAD_SECTIONS:
        tier = sorted(
            (
                f for f in findings
                if not f.get("allowlisted")
                and f.get("assessment", "unassessed") in assessments
            ),
            key=lambda f: (f["path"], f.get("line", 0), f.get("symbol") or ""),
        )
        body = "\n".join(_dead_line(f) for f in tier) if tier else (
            "_None._" if dead_usable else unavailable
        )
        parts.append(f"### {title}\n\n{body}")

    allowlisted = sorted(
        (f for f in findings if f.get("allowlisted")),
        key=lambda f: (f["path"], f.get("line", 0), f.get("symbol") or ""),
    )
    allowlisted_body = (
        "\n".join(_dead_line(f, checkable=False) for f in allowlisted)
        if allowlisted else ("_None._" if dead_usable else unavailable)
    )
    parts.append(f"### Allowlisted\n\n{allowlisted_body}")

    if not findings and dead_usable:
        parts.insert(0, "_No dead-code candidates found._")
    return "\n\n".join(parts)


def _finding_list(analysis: dict, category: str, empty: str) -> str:
    lines = [
        f"- `{f['path']}` {f['symbol'] or ''} ({f['rule']}) - {f['message']}"
        for f in analysis.get("findings", [])
        if f["category"] == category and not f.get("allowlisted")
    ]
    return "\n".join(lines) if lines else empty


def _tool_scoped_findings(analysis: dict, metrics: dict, category: str,
                          empty: str, tool: str) -> str:
    if not _tool_status(metrics, tool)["ok"]:
        return _unavailable(metrics, tool)
    return _finding_list(analysis, category, empty)


def _coverage_reason(metrics: dict) -> str:
    coverage = metrics.get("coverage", {})
    headline = metrics.get("headline", {})
    reasons = []
    if coverage and not coverage.get("available"):
        reasons.append("unavailable")
    if coverage.get("stale") or (not coverage and headline.get("coverage_stale")):
        reasons.append("stale")
    if coverage.get("partial") or (not coverage and headline.get("coverage_partial")):
        reasons.append("partial")
    if coverage.get("failed") or (not coverage and headline.get("coverage_failed")):
        reasons.append("failed")
    if coverage.get("reason"):
        reasons.append(str(coverage["reason"]))
    return "; ".join(reasons) or "freshness could not be established"


def _coverage_provenance(metrics: dict) -> str:
    coverage = metrics.get("coverage", {})
    status = "usable" if coverage.get("usable") else "ignored"
    commit = coverage.get("collected_at_commit") or "unknown"
    age = coverage.get("age_commits")
    age_text = str(age) if age is not None else "unknown"
    reason = "-" if coverage.get("usable") else _coverage_reason(metrics)
    return (
        "| Status | Source | Collected commit | Age (commits) | Detail |\n"
        "|---|---|---|---:|---|\n"
        f"| {status} | {coverage.get('source') or 'unknown'} | {commit} | {age_text} | {reason} |"
    )


def _least_covered(metrics: dict) -> str:
    if not metrics.get("coverage", {}).get("usable"):
        return f"_Coverage evidence ignored: {_coverage_reason(metrics)}._"
    rows = [
        (path, rec)
        for path, rec in metrics["modules"].items()
        if rec.get("coverage_percent") is not None
        and (rec.get("coverage_statements") or 0) > 0
    ]
    rows.sort(key=lambda item: (item[1]["coverage_percent"], item[0]))
    if not rows:
        return "_No measured modules._"
    lines = [
        f"| `{path}` | {rec.get('coverage_statements', 'n/a')} | "
        f"{rec.get('coverage_covered', 'n/a')} | {rec['coverage_percent']}% |"
        for path, rec in rows[:10]
    ]
    return "| Module | Statements | Covered | Coverage |\n|---|---:|---:|---:|\n" + "\n".join(lines)


def _effects_table(graph: dict) -> str:
    rows = [
        f"| `{mod['path']}` | {', '.join(mod['effects'])} |"
        for _name, mod in sorted(graph["modules"].items(), key=lambda kv: kv[1]["path"])
        if mod.get("effects")
    ]
    if not rows:
        return "_No external effects detected._"
    return "| Module | Effects |\n|---|---|\n" + "\n".join(rows)


def render_overview(repo_root: Path, graph: dict, metrics: dict, analysis: dict) -> str:
    h = metrics["headline"]
    coverage_usable = metrics.get("coverage", {}).get("usable", h.get("coverage_usable", False))
    cov = f"{h['avg_coverage']}%" if coverage_usable and h.get("avg_coverage") is not None else "n/a"
    module_cov = (
        f"{h['module_avg_coverage']}%"
        if coverage_usable and h.get("module_avg_coverage") is not None else "n/a"
    )
    if not coverage_usable:
        cov += f" ({_coverage_reason(metrics)} coverage run ignored)"
        module_cov += " (coverage run ignored)"
    radon_ok = _tool_status(metrics, "radon")["ok"]
    vulture_ok = _tool_status(metrics, "vulture")["ok"]
    complexity_count = h.get("modules_over_complexity") if radon_ok else "n/a (radon unavailable)"
    dead_high = h.get("dead_high_confidence") if vulture_ok else "n/a (vulture unavailable)"
    complex_table = (
        "| Module | Max CC |\n|---|---|\n" + "\n".join(_top10(metrics, "max_complexity"))
        if radon_ok else _unavailable(metrics, "radon")
    )
    parts = [
        "## Architecture\n\n" + _mermaid_packages(graph),
        "## Analyzer status\n\n" + _analyzer_status(metrics),
        "## Headline metrics\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"| Modules | {h['files']} |\n| Total LOC | {h['total_loc']} |\n"
        f"| Statement coverage | {cov} |\n| Module-average coverage | {module_cov} |\n"
        f"| Import cycles | {h['cycles']} |\n"
        f"| Modules over complexity threshold | {complexity_count} |\n"
        f"| Dead symbols (high confidence) | {dead_high} |",
        "## Coverage provenance\n\n" + _coverage_provenance(metrics),
        "## Least-covered modules\n\n" + _least_covered(metrics),
        "## Largest modules\n\n| Module | LOC |\n|---|---|\n" + "\n".join(_top10(metrics, "loc")),
        "## Most complex\n\n" + complex_table,
        "## Most depended upon\n\n| Module | Fan-in |\n|---|---|\n" + "\n".join(_top10(metrics, "fan_in")),
        "## Dependency issues\n\n"
        + _tool_scoped_findings(
            analysis, metrics, "dependency", "_None. Declared dependencies match imports._", "deps"
        ),
        "## Layer contracts\n\n"
        + _tool_scoped_findings(
            analysis, metrics, "layer-violation", "_No violations._", "contracts"
        ),
        "## External effects\n\n" + _effects_table(graph),
        "## Dead-code review checklist\n\n" + _dead_checklist(analysis, metrics),
    ]
    commit = metrics.get("commit") or _artifacts.current_commit(repo_root) or "unknown"
    return "\n\n".join(parts) + f"\n\n_Generated at commit {commit} by scripts\\audit.cmd._"


def _render_package_map(package: str, graph: dict, metrics: dict) -> str:
    rows = [(path, rec) for path, rec in metrics["modules"].items() if _package_of(path) == package]
    entry, core, support = [], [], []
    for path, rec in sorted(rows):
        line = f"- `{path}` — fan-in {rec['fan_in']}, fan-out {rec['fan_out']}, LOC {rec['loc']}"
        if rec["fan_in"] == 0:
            entry.append(line)
        elif rec["fan_in"] >= 3:
            core.append(line)
        else:
            support.append(line)
    sections = []
    if entry:
        sections.append("### Entry points (nothing imports these)\n" + "\n".join(entry))
    if core:
        sections.append("### Core (widely depended upon)\n" + "\n".join(core))
    if support:
        sections.append("### Support\n" + "\n".join(support))
    return "\n\n".join(sections) if sections else "_No modules._"


def run(repo_root: Path, options) -> int:
    graph = _artifacts.read_artifact(repo_root, "graph")
    metrics = _artifacts.read_artifact(repo_root, "metrics")
    analysis = _artifacts.read_artifact(repo_root, "analysis")
    maps_dir = repo_root / "docs" / "audit" / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)

    overview_path = maps_dir / "overview.md"
    existing = overview_path.read_text(encoding="utf-8") if overview_path.exists() else None
    overview_path.write_text(
        replace_generated(existing, "overview", render_overview(repo_root, graph, metrics, analysis)),
        encoding="utf-8",
    )

    packages = sorted({_package_of(p) for p in metrics["modules"]})
    for package in packages:
        path = maps_dir / f"{package}.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        path.write_text(
            replace_generated(existing, f"map-{package}", _render_package_map(package, graph, metrics)),
            encoding="utf-8",
        )
    print(f"render-human: overview + {len(packages)} package maps under docs/audit/maps/")
    return 0
