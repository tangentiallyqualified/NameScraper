"""Stage 3: run ruff, vulture, radon; normalize findings; cross-check dead code."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

from . import _artifacts

RUFF_SELECT = "F401,F811,F841"
COMPLEXITY_THRESHOLD = 10


def _rel_to_repo(repo_root: Path, filename: str) -> str:
    try:
        return Path(filename).resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(filename).replace("\\", "/")


def _run_ruff(repo_root: Path) -> list[dict]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--output-format=json",
            "--select",
            RUFF_SELECT,
            "--no-cache",
            "plex_renamer",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=300,
    )
    if result.returncode not in (0, 1):  # 1 = findings present
        raise RuntimeError(f"ruff failed: {result.stderr.strip()[:200]}")
    if result.returncode == 1 and not result.stdout.strip():
        raise RuntimeError(f"ruff exited 1 with no output: {result.stderr.strip()[:200]}")
    findings = []
    for item in json.loads(result.stdout or "[]"):
        path = _rel_to_repo(repo_root, item["filename"])
        findings.append(
            {
                "source": "ruff",
                "rule": item["code"],
                "path": path,
                "line": item["location"]["row"],
                "symbol": None,
                "message": item["message"],
                "confidence": 100,
                "category": "unused-import" if item["code"] == "F401" else "unused-name",
            }
        )
    return findings


def _run_vulture(repo_root: Path) -> list[dict]:
    import vulture

    v = vulture.Vulture()
    v.scavenge([str(repo_root / "plex_renamer")])
    findings = []
    for item in v.get_unused_code():
        rel = _rel_to_repo(repo_root, str(item.filename))
        findings.append(
            {
                "source": "vulture",
                "rule": f"unused-{item.typ}",
                "path": rel,
                "line": item.first_lineno,
                "symbol": str(item.name),
                "message": f"unused {item.typ} '{item.name}'",
                "confidence": item.confidence,
                "category": "dead-code",
            }
        )
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
                findings.append(
                    {
                        "source": "radon",
                        "rule": "CC",
                        "path": rec["path"],
                        "line": b.lineno,
                        "symbol": b.name,
                        "message": f"cyclomatic complexity {b.complexity}",
                        "confidence": 100,
                        "category": "complexity",
                    }
                )
    return findings, per_file


def _assess_dead_code(findings: list[dict], graph: dict, inventory: dict | None = None) -> None:
    production_refs_by_symbol: dict[tuple[str, str], list[str]] = {}
    module_by_path: dict[str, str] = {}
    entrypoint_paths: set[str] = set()
    for module_name, mod in graph["modules"].items():
        module_by_path[mod["path"]] = module_name
        if mod.get("entrypoint"):
            entrypoint_paths.add(mod["path"])
        for sym in mod["symbols"]:
            production_refs_by_symbol[(mod["path"], sym["name"])] = sorted(
                sym.get("imported_by", [])
            )

    test_refs_by_symbol: dict[str, set[str]] = {}
    for test in (inventory or {}).get("test_files", []):
        for qualified_symbol in test.get("imports_symbols", []):
            test_refs_by_symbol.setdefault(qualified_symbol, set()).add(test["path"])

    for f in findings:
        if f["category"] != "dead-code":
            continue
        key = (f["path"], f["symbol"] or "")
        production_refs = production_refs_by_symbol.get(key)
        module_name = module_by_path.get(f["path"])
        qualified_symbol = (
            f"{module_name}.{f['symbol']}" if module_name and f.get("symbol") else None
        )
        test_refs = sorted(test_refs_by_symbol.get(qualified_symbol or "", set()))
        f["production_references"] = production_refs or []
        f["test_references"] = test_refs
        f["allowlist_reason"] = None

        if f["path"] in entrypoint_paths:
            f["assessment"] = "entrypoint"
        elif test_refs:
            f["assessment"] = "test-referenced"
        elif production_refs is None:
            f["assessment"] = "dynamic-or-unresolved"
        elif production_refs:
            f["assessment"] = "referenced"
        elif f.get("confidence", 0) >= 80:
            f["assessment"] = "high-confidence"
        elif f.get("confidence", 0) >= 60:
            f["assessment"] = "medium-confidence"
        else:
            f["assessment"] = "low-confidence"


def _apply_allowlist(findings: list[dict], allowlist_text: str) -> None:
    entries = tomllib.loads(allowlist_text).get("ignore", [])
    for f in findings:
        matched = next(
            (
                e
                for e in entries
                if (("symbol" not in e) or fnmatch.fnmatch(f["symbol"] or "", e["symbol"]))
                and (("path" not in e) or fnmatch.fnmatch(f["path"], e["path"]))
                and ("symbol" in e or "path" in e)
            ),
            None,
        )
        f["allowlisted"] = matched is not None
        f["allowlist_reason"] = matched.get("reason") if matched is not None else None


_REQ_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(requirement: str) -> str:
    m = _REQ_NAME.match(requirement.strip())
    return m.group(0) if m else requirement.strip()


@lru_cache(maxsize=1)
def _dist_top_levels() -> dict[str, set[str]]:
    """Normalized installed-distribution name -> top-level import names it provides."""
    from importlib.metadata import packages_distributions

    mapping: dict[str, set[str]] = {}
    for top_level, dists in packages_distributions().items():
        for dist in dists:
            mapping.setdefault(_normalize_dist(dist), set()).add(top_level)
    return mapping


def _tops_for(deps: set[str], dist_tops: dict[str, set[str]]) -> set[str]:
    tops: set[str] = set()
    for dep in deps:
        # fall back to a name guess when the distribution is not installed
        tops |= dist_tops.get(dep, {dep.replace("-", "_")})
    return tops


def _dep_finding(rule: str, symbol: str, message: str) -> dict:
    return {
        "source": "deps",
        "rule": rule,
        "path": "pyproject.toml",
        "line": 1,
        "symbol": symbol,
        "message": message,
        "confidence": 100,
        "category": "dependency",
    }


def _module_prefixed(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _cycle_matches_legacy(
    modules: set[str],
    edges: set[tuple[str, str]],
    legacy_modules: set[str],
    legacy_edges: set[tuple[str, str]],
) -> bool:
    """A cycle is legacy-compliant only if every module AND every edge already existed."""
    return modules <= legacy_modules and edges <= legacy_edges


def _cycle_contract_findings(graph: dict, baseline_text: str) -> list[dict]:
    baseline = json.loads(baseline_text)
    baseline_cycles = [
        (
            set(cycle["modules"]),
            {tuple(edge) for edge in cycle["edges"]},
        )
        for cycle in baseline["cycles"]
    ]
    findings = []
    for cycle in graph.get("cycles", []):
        modules = set(cycle["modules"])
        edges = {tuple(edge) for edge in cycle["edges"]}
        if any(
            _cycle_matches_legacy(modules, edges, legacy_modules, legacy_edges)
            for legacy_modules, legacy_edges in baseline_cycles
        ):
            continue
        rule = (
            "enlarged-cycle"
            if any(
                legacy_modules <= modules or modules <= legacy_modules
                for legacy_modules, _legacy_edges in baseline_cycles
            )
            else "new-cycle"
        )
        symbol = ", ".join(cycle["modules"])
        findings.append(
            {
                "source": "contracts",
                "rule": rule,
                "path": "scripts/audit/cycle-baseline.json",
                "line": 1,
                "symbol": symbol,
                "message": f"{rule.replace('-', ' ')}: {symbol}",
                "confidence": 100,
                "category": "layer-violation",
            }
        )
    return findings


def _check_contracts(
    graph: dict, contract_config: dict, cycle_baseline_text: str | None = None
) -> list[dict]:
    rules = contract_config.get("forbid", [])
    findings = []
    for name, mod in sorted(graph["modules"].items()):
        for target in mod["imports"]:
            for rule in rules:
                if _module_prefixed(name, rule["from"]) and _module_prefixed(target, rule["to"]):
                    reason = rule.get("reason", "")
                    findings.append(
                        {
                            "source": "contracts",
                            "rule": "forbidden-import",
                            "path": mod["path"],
                            "line": 1,
                            "symbol": target,
                            "message": f"{name} imports {target} - forbidden by contract "
                            f"{rule['from']} -> {rule['to']} ({reason})",
                            "confidence": 100,
                            "category": "layer-violation",
                        }
                    )
    if cycle_baseline_text is not None:
        findings.extend(_cycle_contract_findings(graph, cycle_baseline_text))
    return findings


def _contract_findings(
    graph: dict,
    contracts_text: str,
    cycle_baseline_text: str | None,
) -> list[dict]:
    if not contracts_text:
        return []
    contract_config = tomllib.loads(contracts_text)
    baseline_name = contract_config.get("cycles", {}).get("baseline")
    if cycle_baseline_text is None and baseline_name:
        baseline_path = Path(__file__).parent / baseline_name
        cycle_baseline_text = baseline_path.read_text(encoding="utf-8")
    return _check_contracts(graph, contract_config, cycle_baseline_text)


def _check_dependencies(graph: dict, pyproject_text: str) -> list[dict]:
    project = tomllib.loads(pyproject_text).get("project", {})
    runtime = {_normalize_dist(_req_name(r)) for r in project.get("dependencies", [])}
    dev: set[str] = set()
    for reqs in project.get("optional-dependencies", {}).values():
        dev |= {_normalize_dist(_req_name(r)) for r in reqs}

    imported: set[str] = set()
    for mod in graph["modules"].values():
        imported |= set(mod.get("external_imports", []))
    imported -= set(sys.stdlib_module_names)

    dist_tops = _dist_top_levels()
    tops_by_runtime_dep = {dep: _tops_for({dep}, dist_tops) for dep in runtime}
    findings = []
    for dep in sorted(runtime):
        if not (tops_by_runtime_dep[dep] & imported):
            findings.append(
                _dep_finding(
                    "unused-dependency",
                    dep,
                    f"declared dependency '{dep}' is never imported by plex_renamer",
                )
            )
    runtime_tops = set().union(*tops_by_runtime_dep.values())
    dev_tops = _tops_for(dev, dist_tops)
    for top in sorted(imported):
        if top in runtime_tops:
            continue
        if top in dev_tops:
            findings.append(
                _dep_finding(
                    "dev-dependency-in-prod",
                    top,
                    f"'{top}' is imported by plex_renamer but only declared as a dev dependency",
                )
            )
        else:
            findings.append(
                _dep_finding(
                    "undeclared-dependency",
                    top,
                    f"'{top}' is imported by plex_renamer but not declared in pyproject.toml",
                )
            )
    return findings


def run_analysis(
    repo_root: Path,
    inventory: dict,
    graph: dict,
    allowlist_text: str | None = None,
    pyproject_text: str | None = None,
    contracts_text: str | None = None,
    cycle_baseline_text: str | None = None,
) -> dict:
    if allowlist_text is None:
        default = Path(__file__).parent / "allowlist.toml"
        allowlist_text = (
            default.read_text(encoding="utf-8") if default.exists() else "ignore = []\n"
        )

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

    try:
        if pyproject_text is None:
            pyproject_path = repo_root / "pyproject.toml"
            pyproject_text = (
                pyproject_path.read_text(encoding="utf-8") if pyproject_path.exists() else ""
            )
        if pyproject_text:
            findings.extend(_check_dependencies(graph, pyproject_text))
        tool_status["deps"] = {"ok": True, "reason": None}
    except Exception as exc:
        tool_status["deps"] = {"ok": False, "reason": str(exc)[:200]}

    try:
        if contracts_text is None:
            default_contracts = Path(__file__).parent / "contracts.toml"
            contracts_text = (
                default_contracts.read_text(encoding="utf-8") if default_contracts.exists() else ""
            )
        findings.extend(_contract_findings(graph, contracts_text, cycle_baseline_text))
        tool_status["contracts"] = {"ok": True, "reason": None}
    except Exception as exc:
        tool_status["contracts"] = {"ok": False, "reason": str(exc)[:200]}

    _assess_dead_code(findings, graph, inventory)
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
    print(
        _artifacts.ascii_safe(
            f"analyze: {n} findings" + (f"; unavailable: {', '.join(bad)}" if bad else "")
        )
    )
    return 2 if bad else 0
