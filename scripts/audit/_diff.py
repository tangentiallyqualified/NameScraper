"""Stage 7: diff current metrics against committed baseline; write CHANGES.md."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import _artifacts

BASELINE_REL = Path("docs") / "audit" / "baseline.json"
CHANGES_REL = Path("docs") / "audit" / "CHANGES.md"
HISTORY_CAP = 10
LOC_RATIO = 1.5
CC_DELTA = 5
COVERAGE_DELTA = 10.0
BASELINE_FIELDS = ("sha256", "loc", "max_complexity", "coverage_percent", "dead_candidates")


def compare(baseline: dict | None, metrics: dict) -> dict:
    current = metrics["modules"]
    if baseline is None:
        return {"added": sorted(current), "removed": [], "renamed": [],
                "movements": [], "first_run": True}
    old = baseline["modules"]
    added = sorted(set(current) - set(old))
    removed = sorted(set(old) - set(current))

    renamed = []
    removed_by_sha = {old[p]["sha256"]: p for p in removed}
    still_added = []
    for p in added:
        match = removed_by_sha.pop(current[p]["sha256"], None)
        if match:
            renamed.append({"from": match, "to": p})
            removed.remove(match)
        else:
            still_added.append(p)
    added = still_added

    movements: list[str] = []
    for path in sorted(set(current) & set(old)):
        now, was = current[path], old[path]
        if was["loc"] and now["loc"] / was["loc"] >= LOC_RATIO:
            movements.append(f"`{path}`: loc {was['loc']} -> {now['loc']}")
        if now["max_complexity"] - was["max_complexity"] >= CC_DELTA:
            movements.append(f"`{path}`: max_complexity {was['max_complexity']} -> {now['max_complexity']}")
        if (was.get("coverage_percent") is not None and now.get("coverage_percent") is not None
                and abs(now["coverage_percent"] - was["coverage_percent"]) >= COVERAGE_DELTA):
            movements.append(f"`{path}`: coverage {was['coverage_percent']} -> {now['coverage_percent']}")
        if now["dead_candidates"] > was["dead_candidates"]:
            movements.append(f"`{path}`: dead candidates {was['dead_candidates']} -> {now['dead_candidates']}")
    return {"added": added, "removed": removed, "renamed": renamed,
            "movements": movements, "first_run": False}


def _section(repo_root: Path, result: dict, baseline: dict | None, metrics: dict) -> str:
    commit = _artifacts.current_commit(repo_root) or "unknown"
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_commit = (baseline.get("commit") or "unknown") if baseline else "none (first run)"
    h = metrics["headline"]
    lines = [f"## Audit {date} ({commit}) vs baseline ({base_commit})", ""]
    lines.append(f"- Headline: {h['files']} modules, {h['total_loc']} LOC, "
                 f"{h['dead_high_confidence']} high-confidence dead symbols, {h['cycles']} cycles")
    if result["first_run"]:
        lines.append("- First audit run: baseline established.")
    else:
        if result["added"]:
            lines.append("- Added: " + ", ".join(f"`{p}`" for p in result["added"]))
        if result["removed"]:
            lines.append("- Removed: " + ", ".join(f"`{p}`" for p in result["removed"]))
        for r in result["renamed"]:
            lines.append(f"- Renamed: `{r['from']}` -> `{r['to']}`")
        if result["movements"]:
            lines.append("- Notable movements:")
            lines += [f"  - {m}" for m in result["movements"]]
        if not any((result["added"], result["removed"], result["renamed"], result["movements"])):
            lines.append("- No notable changes since baseline.")
    return "\n".join(lines)


def run(repo_root: Path, options) -> int:
    metrics = _artifacts.read_artifact(repo_root, "metrics")
    baseline_path = repo_root / BASELINE_REL
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    result = compare(baseline, metrics)

    changes_path = repo_root / CHANGES_REL
    header = "# Audit Change Log\n\n"
    body = ""
    if changes_path.exists():
        existing = changes_path.read_text(encoding="utf-8")
        body = existing.split("# Audit Change Log", 1)[-1].lstrip("\n")
    sections = re.split(r"(?=^## Audit )", body, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]
    new_section = _section(repo_root, result, baseline, metrics).strip()
    new_body = "\n\n".join([new_section] + sections[: HISTORY_CAP - 1])
    changes_path.parent.mkdir(parents=True, exist_ok=True)
    changes_path.write_text(header + new_body.rstrip() + "\n", encoding="utf-8")

    new_baseline = {
        "commit": metrics.get("commit") or _artifacts.current_commit(repo_root),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modules": {p: {k: r[k] for k in BASELINE_FIELDS} for p, r in metrics["modules"].items()},
        "headline": metrics["headline"],
    }
    baseline_path.write_text(json.dumps(new_baseline, indent=1, sort_keys=True), encoding="utf-8")
    n = len(result["movements"])
    print(f"diff: {len(result['added'])} added, {len(result['removed'])} removed, {n} movements; baseline refreshed")
    return 0
