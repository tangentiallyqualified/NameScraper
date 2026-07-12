"""Stage 6b: human-readable maps with generated/curated marker sections."""
from __future__ import annotations

import re
from pathlib import Path

from . import _artifacts

START = "<!-- audit:generated:start {name} -->"
END = "<!-- audit:generated:end {name} -->"


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


def _package_of(path: str) -> str:
    parts = Path(path).parts
    return parts[1] if len(parts) > 2 else "root"


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


def _dead_checklist(analysis: dict) -> str:
    lines = []
    for f in analysis.get("findings", []):
        if f["category"] != "dead-code" or f.get("allowlisted"):
            continue
        lines.append(f"- [ ] `{f['path']}:{f['line']}` {f['symbol']} ({f.get('assessment', 'unassessed')})")
    return "\n".join(lines) if lines else "_No dead-code candidates. Clean._"


def _finding_list(analysis: dict, category: str, empty: str) -> str:
    lines = [
        f"- `{f['path']}` {f['symbol'] or ''} ({f['rule']}) - {f['message']}"
        for f in analysis.get("findings", [])
        if f["category"] == category and not f.get("allowlisted")
    ]
    return "\n".join(lines) if lines else empty


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
    cov = f"{h['avg_coverage']}%" if h["avg_coverage"] is not None else "n/a"
    parts = [
        "## Architecture\n\n" + _mermaid_packages(graph),
        "## Headline metrics\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"| Modules | {h['files']} |\n| Total LOC | {h['total_loc']} |\n"
        f"| Avg coverage | {cov} |\n| Import cycles | {h['cycles']} |\n"
        f"| Modules over complexity threshold | {h['modules_over_complexity']} |\n"
        f"| Dead symbols (high confidence) | {h['dead_high_confidence']} |",
        "## Largest modules\n\n| Module | LOC |\n|---|---|\n" + "\n".join(_top10(metrics, "loc")),
        "## Most complex\n\n| Module | Max CC |\n|---|---|\n" + "\n".join(_top10(metrics, "max_complexity")),
        "## Most depended upon\n\n| Module | Fan-in |\n|---|---|\n" + "\n".join(_top10(metrics, "fan_in")),
        "## Dependency issues\n\n"
        + _finding_list(analysis, "dependency", "_None. Declared dependencies match imports._"),
        "## Layer contracts\n\n"
        + _finding_list(analysis, "layer-violation", "_No violations._"),
        "## External effects\n\n" + _effects_table(graph),
        "## Dead-code review checklist\n\n" + _dead_checklist(analysis),
    ]
    commit = _artifacts.current_commit(repo_root) or "unknown"
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
