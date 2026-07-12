"""Stage 3: run ruff, vulture, radon; normalize findings; cross-check dead code."""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from . import _artifacts

RUFF_SELECT = "F401,F811,F841"
COMPLEXITY_THRESHOLD = 10


def _run_ruff(repo_root: Path) -> list[dict]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format=json",
         "--select", RUFF_SELECT, "--no-cache", "plex_renamer"],
        cwd=repo_root, capture_output=True, text=True, timeout=300,
    )
    if result.returncode not in (0, 1):  # 1 = findings present
        raise RuntimeError(f"ruff failed: {result.stderr.strip()[:200]}")
    findings = []
    for item in json.loads(result.stdout or "[]"):
        rel = Path(item["filename"]).resolve()
        try:
            path = rel.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            path = item["filename"].replace("\\", "/")
        findings.append({
            "source": "ruff", "rule": item["code"], "path": path,
            "line": item["location"]["row"], "symbol": None,
            "message": item["message"], "confidence": 100,
            "category": "unused-import" if item["code"] == "F401" else "unused-name",
        })
    return findings


def _run_vulture(repo_root: Path) -> list[dict]:
    import vulture

    v = vulture.Vulture()
    v.scavenge([str(repo_root / "plex_renamer")])
    findings = []
    for item in v.get_unused_code():
        path = Path(str(item.filename)).resolve()
        try:
            rel = path.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = str(item.filename).replace("\\", "/")
        findings.append({
            "source": "vulture", "rule": f"unused-{item.typ}", "path": rel,
            "line": item.first_lineno, "symbol": str(item.name),
            "message": f"unused {item.typ} '{item.name}'",
            "confidence": item.confidence, "category": "dead-code",
        })
    return findings


def _run_radon(repo_root: Path, inventory: dict) -> tuple[list[dict], dict]:
    from radon.complexity import cc_visit
    from radon.metrics import mi_visit

    findings: list[dict] = []
    per_file: dict[str, dict] = {}
    for rec in inventory["python_files"]:
        code = (repo_root / rec["path"]).read_text(encoding="utf-8", errors="replace")
        try:
            blocks = cc_visit(code)
            mi = mi_visit(code, multi=True)
        except SyntaxError:
            continue
        comps = [b.complexity for b in blocks]
        per_file[rec["path"]] = {
            "max_complexity": max(comps, default=0),
            "avg_complexity": round(sum(comps) / len(comps), 1) if comps else 0.0,
            "maintainability": round(mi, 1),
        }
        for b in blocks:
            if b.complexity > COMPLEXITY_THRESHOLD:
                findings.append({
                    "source": "radon", "rule": "CC", "path": rec["path"],
                    "line": b.lineno, "symbol": b.name,
                    "message": f"cyclomatic complexity {b.complexity}",
                    "confidence": 100, "category": "complexity",
                })
    return findings, per_file


def _assess_dead_code(findings: list[dict], graph: dict) -> None:
    fan_in_by_symbol: dict[tuple[str, str], int] = {}
    for mod in graph["modules"].values():
        for sym in mod["symbols"]:
            fan_in_by_symbol[(mod["path"], sym["name"])] = len(sym["imported_by"])
    for f in findings:
        if f["category"] != "dead-code":
            continue
        refs = fan_in_by_symbol.get((f["path"], f["symbol"] or ""))
        f["assessment"] = "high-confidence" if refs == 0 else "low-confidence"


def _apply_allowlist(findings: list[dict], allowlist_text: str) -> None:
    entries = tomllib.loads(allowlist_text).get("ignore", [])
    for f in findings:
        f["allowlisted"] = any(
            (("symbol" not in e) or fnmatch.fnmatch(f["symbol"] or "", e["symbol"]))
            and (("path" not in e) or fnmatch.fnmatch(f["path"], e["path"]))
            and ("symbol" in e or "path" in e)
            for e in entries
        )


def run_analysis(repo_root: Path, inventory: dict, graph: dict,
                 allowlist_text: str | None = None) -> dict:
    if allowlist_text is None:
        default = Path(__file__).parent / "allowlist.toml"
        allowlist_text = default.read_text(encoding="utf-8") if default.exists() else "ignore = []\n"

    findings: list[dict] = []
    per_file: dict[str, dict] = {}
    tool_status: dict[str, dict] = {}
    for tool, runner in (("ruff", _run_ruff), ("vulture", _run_vulture)):
        try:
            findings.extend(runner(repo_root))
            tool_status[tool] = {"ok": True, "reason": None}
        except Exception as exc:  # degrade, never abort
            tool_status[tool] = {"ok": False, "reason": str(exc)[:200]}
    try:
        radon_findings, per_file = _run_radon(repo_root, inventory)
        findings.extend(radon_findings)
        tool_status["radon"] = {"ok": True, "reason": None}
    except Exception as exc:
        tool_status["radon"] = {"ok": False, "reason": str(exc)[:200]}

    _assess_dead_code(findings, graph)
    _apply_allowlist(findings, allowlist_text)
    findings.sort(key=lambda f: (f["path"], f["line"], f["source"]))
    return {"findings": findings, "per_file": per_file, "tool_status": tool_status}


def run(repo_root: Path, options) -> int:
    inventory = _artifacts.read_artifact(repo_root, "inventory")
    graph = _artifacts.read_artifact(repo_root, "graph")
    analysis = run_analysis(repo_root, inventory, graph)
    _artifacts.write_artifact(repo_root, "analysis", analysis)
    bad = [t for t, s in analysis["tool_status"].items() if not s["ok"]]
    n = len([f for f in analysis["findings"] if not f["allowlisted"]])
    print(f"analyze: {n} findings" + (f"; unavailable: {', '.join(bad)}" if bad else ""))
    return 2 if bad else 0
