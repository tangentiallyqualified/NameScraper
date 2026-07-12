"""Stage 6c: opt-in doc ledger staleness plus full doc inventory report."""
from __future__ import annotations

import tomllib
from pathlib import Path

from . import _artifacts

LEDGER_REL = Path("docs") / "audit" / "doc-ledger.toml"


def load_ledger(repo_root: Path) -> list[dict]:
    path = repo_root / LEDGER_REL
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return list(data.get("docs", []))


def staleness(repo_root: Path, entries: list[dict]) -> list[dict]:
    report = []
    for entry in entries:
        changed = _artifacts.changed_files_since(repo_root, entry["reviewed_commit"], *entry["sources"])
        if changed is None:
            report.append({"path": entry["path"], "reviewed_commit": entry["reviewed_commit"],
                           "stale": True, "changed_sources": [], "error": "git unavailable"})
            continue
        report.append({"path": entry["path"], "reviewed_commit": entry["reviewed_commit"],
                       "stale": bool(changed), "changed_sources": changed, "error": None})
    return report


def _render(repo_root: Path, report: list[dict], inventory: dict) -> str:
    lines = ["# Documentation status", "",
             "## Enrolled docs (opt-in ledger)", ""]
    if report:
        lines += ["| Doc | Reviewed at | Status |", "|---|---|---|"]
        for r in report:
            status = ("STALE: " + ", ".join(f"`{c}`" for c in r["changed_sources"])
                      if r["stale"] else "current")
            lines.append(f"| `{r['path']}` | {r['reviewed_commit']} | {status} |")
    else:
        lines.append("_No docs enrolled. Add entries to docs/audit/doc-ledger.toml._")
    lines += ["", "## All docs (purge worksheet)", "",
              "| Doc | Last touched | Broken refs |", "|---|---|---|"]
    for d in sorted(inventory.get("docs", []), key=lambda d: d["last_touched"]):
        broken = ", ".join(f"`{b}`" for b in d["broken_refs"]) or "-"
        lines.append(f"| `{d['path']}` | {d['last_touched'][:10]} | {broken} |")
    commit = _artifacts.current_commit(repo_root) or "unknown"
    lines += ["", f"_Generated at commit {commit} by scripts\\audit.cmd._", ""]
    return "\n".join(lines)


def run(repo_root: Path, options) -> int:
    inventory = _artifacts.read_artifact(repo_root, "inventory")
    report = staleness(repo_root, load_ledger(repo_root))
    out = repo_root / "docs" / "audit" / "doc-status.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(repo_root, report, inventory), encoding="utf-8")
    stale = sum(1 for r in report if r["stale"])
    print(f"doc-ledger: {len(report)} enrolled, {stale} stale")
    return 0
