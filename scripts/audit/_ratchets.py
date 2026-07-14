"""No-new-debt comparisons for normalized audit findings and numeric ceilings."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from . import _analyze, _graph, _inventory

_POLICY = tomllib.loads((Path(__file__).parent / "policy.toml").read_text(encoding="utf-8"))
MAX_CYCLOMATIC_COMPLEXITY = _POLICY["quality"]["max_cyclomatic_complexity"]
MAX_PYTHON_FILE_LOC = _POLICY["quality"]["max_python_file_loc"]

Finding = dict[str, object]


class QualityEvidenceError(RuntimeError):
    """Raised when complete quality evidence cannot be collected."""


_SCOPE_NODES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _module_qualifier(path: str) -> str:
    parts = list(Path(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or Path(path).stem


def _scope_entries(repo_root: Path, path: str) -> list[tuple[int, int, int, str]]:
    module = _module_qualifier(path)
    try:
        tree = ast.parse((repo_root / path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []

    entries: list[tuple[int, int, int, str]] = []

    def visit(node: ast.AST, qualifier: str, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            child_qualifier = qualifier
            child_depth = depth
            if isinstance(child, _SCOPE_NODES):
                child_qualifier = f"{qualifier}.{child.name}"
                child_depth = depth + 1
                entries.append(
                    (
                        child.lineno,
                        getattr(child, "end_lineno", child.lineno),
                        child_depth,
                        child_qualifier,
                    )
                )
            visit(child, child_qualifier, child_depth)

    visit(tree, module, 0)
    return entries


def _qualified_scope(
    repo_root: Path,
    path: str,
    line: int,
    cache: dict[str, list[tuple[int, int, int, str]]],
) -> str:
    if path not in cache:
        cache[path] = _scope_entries(repo_root, path)
    candidates = [entry for entry in cache[path] if entry[0] <= line <= entry[1]]
    if not candidates:
        return _module_qualifier(path)
    return max(candidates, key=lambda entry: (entry[2], entry[0], -entry[1]))[3]


def _suffix_occurrences(findings: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for finding in findings:
        key = (
            str(finding.get("source") or finding.get("analyzer") or "unknown"),
            str(finding.get("rule") or "unknown"),
            str(finding.get("path") or "").replace("\\", "/"),
            str(finding.get("symbol") or "unknown"),
        )
        groups.setdefault(key, []).append(finding)

    qualified: list[dict] = []
    for key in sorted(groups):
        _analyzer, _rule, _path, base_symbol = key
        ordered = sorted(
            groups[key],
            key=lambda finding: (
                int(finding.get("line") or 0),
                int(finding.get("column") or 0),
                str(finding.get("message") or ""),
            ),
        )
        for occurrence, finding in enumerate(ordered, 1):
            qualified.append({**finding, "symbol": f"{base_symbol}#{occurrence}"})
    return qualified


def _identity(finding: dict) -> tuple[str, str, str, str | None]:
    return (
        str(finding.get("analyzer") or finding.get("source") or "unknown"),
        str(finding.get("rule") or "unknown"),
        str(finding.get("path") or "").replace("\\", "/"),
        str(finding["symbol"]) if finding.get("symbol") is not None else None,
    )


def _identity_sort_key(identity: tuple[str, str, str, str | None]) -> tuple[str, str, str, str]:
    analyzer, rule, path, symbol = identity
    return path, analyzer, rule, symbol or ""


def build_baseline(current: dict) -> dict:
    """Normalize current evidence into the compact committed baseline schema."""
    identities = {_identity(finding) for finding in current.get("findings", [])}
    findings = [
        {
            "analyzer": analyzer,
            "path": path,
            "rule": rule,
            "symbol": symbol,
        }
        for analyzer, rule, path, symbol in sorted(identities, key=_identity_sort_key)
    ]
    thresholds = {
        "max_complexity": MAX_CYCLOMATIC_COMPLEXITY,
        "loc": MAX_PYTHON_FILE_LOC,
    }
    ceilings: dict[str, dict[str, int]] = {}
    for path, metrics in sorted(current.get("modules", {}).items()):
        saved = {
            metric: value
            for metric, threshold in thresholds.items()
            if isinstance((value := metrics.get(metric)), int) and value > threshold
        }
        if saved:
            ceilings[path.replace("\\", "/")] = saved
    return {"schema_version": 1, "findings": findings, "ceilings": ceilings}


def _finding_violation(identity: tuple[str, str, str, str | None], kind: str) -> Finding:
    analyzer, rule, path, symbol = identity
    message = (
        f"new {analyzer}/{rule} finding"
        if kind == "new-debt"
        else f"baseline {analyzer}/{rule} finding is no longer present"
    )
    return {
        "analyzer": analyzer,
        "baseline": None,
        "current": None,
        "kind": kind,
        "message": message,
        "metric": None,
        "path": path,
        "rule": rule,
        "symbol": symbol,
    }


def _metric_violation(
    path: str,
    metric: str,
    kind: str,
    current: int | None,
    baseline: int | None,
) -> Finding:
    analyzer, rule = ("radon", "CC") if metric == "max_complexity" else ("inventory", "LOC")
    if kind == "enlarged-debt":
        message = f"{metric} increased from {baseline} to {current}"
    elif kind == "stale-baseline":
        message = f"baseline {metric} ceiling {baseline} is stale; current is {current}"
    else:
        message = f"new {metric} debt at {current}"
    return {
        "analyzer": analyzer,
        "baseline": baseline,
        "current": current,
        "kind": kind,
        "message": message,
        "metric": metric,
        "path": path.replace("\\", "/"),
        "rule": rule,
        "symbol": None,
    }


def _sort_key(finding: Finding) -> tuple[str, str, str, str, str, str]:
    return (
        str(finding["path"]),
        str(finding["analyzer"]),
        str(finding["rule"]),
        str(finding["symbol"] or ""),
        str(finding["kind"]),
        str(finding["metric"] or ""),
    )


def _normalized_metric_map(records: dict) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for path, metrics in sorted(records.items()):
        normalized.setdefault(path.replace("\\", "/"), {}).update(metrics)
    return normalized


def evaluate_ratchets(current: dict, baseline: dict) -> list[Finding]:
    """Return deterministic ratchet violations between current and baseline evidence."""
    current_findings = {_identity(finding) for finding in current.get("findings", [])}
    baseline_findings = {_identity(finding) for finding in baseline.get("findings", [])}
    violations = [
        _finding_violation(identity, "new-debt")
        for identity in sorted(current_findings - baseline_findings, key=_identity_sort_key)
    ]
    violations.extend(
        _finding_violation(identity, "stale-baseline")
        for identity in sorted(baseline_findings - current_findings, key=_identity_sort_key)
    )
    current_modules = _normalized_metric_map(current.get("modules", {}))
    baseline_ceilings = _normalized_metric_map(baseline.get("ceilings", {}))
    thresholds = {
        "max_complexity": MAX_CYCLOMATIC_COMPLEXITY,
        "loc": MAX_PYTHON_FILE_LOC,
    }
    for path, metrics in current_modules.items():
        ceilings = baseline_ceilings.get(path, {})
        for metric, threshold in thresholds.items():
            current_value = metrics.get(metric)
            if not isinstance(current_value, int) or current_value <= threshold:
                continue
            baseline_value = ceilings.get(metric)
            if not isinstance(baseline_value, int):
                violations.append(_metric_violation(path, metric, "new-debt", current_value, None))
            elif current_value > baseline_value:
                violations.append(
                    _metric_violation(path, metric, "enlarged-debt", current_value, baseline_value)
                )
    for path, ceilings in baseline_ceilings.items():
        metrics = current_modules.get(path, {})
        for metric, baseline_value in ceilings.items():
            current_value = metrics.get(metric)
            threshold = thresholds.get(metric)
            if isinstance(baseline_value, int) and (
                (isinstance(threshold, int) and baseline_value <= threshold)
                or (
                    current_value != baseline_value
                    and (not isinstance(current_value, int) or current_value < baseline_value)
                )
            ):
                violations.append(
                    _metric_violation(path, metric, "stale-baseline", current_value, baseline_value)
                )
    return sorted(violations, key=_sort_key)


def _run_policy_ruff(repo_root: Path) -> list[dict]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--output-format=json",
            "--no-cache",
            "plex_renamer",
            "tests",
            "scripts",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode not in (0, 1):
        raise QualityEvidenceError(f"ruff failed: {result.stderr.strip()[:200]}")
    if result.returncode == 1 and not result.stdout.strip():
        raise QualityEvidenceError(f"ruff exited 1 with no output: {result.stderr.strip()[:200]}")
    findings = []
    scope_cache: dict[str, list[tuple[int, int, int, str]]] = {}
    for item in json.loads(result.stdout or "[]"):
        path = _analyze._rel_to_repo(repo_root, item["filename"])
        line = item["location"]["row"]
        scope = _qualified_scope(repo_root, path, line, scope_cache)
        rule_anchor = str(item.get("name") or item["code"])
        message_anchor = " ".join(str(item.get("message") or rule_anchor).split())
        findings.append(
            {
                "source": "ruff",
                "rule": item["code"],
                "path": path,
                "line": line,
                "column": item["location"].get("column", 0),
                "symbol": f"{scope}::{rule_anchor}::{message_anchor}",
                "message": item["message"],
                "confidence": 100,
                "category": "lint",
                "allowlisted": False,
                "allowlist_reason": None,
            }
        )
    return _suffix_occurrences(findings)


def _qualify_vulture_findings(repo_root: Path, findings: list[dict]) -> list[dict]:
    scope_cache: dict[str, list[tuple[int, int, int, str]]] = {}
    qualified = []
    for finding in findings:
        path = str(finding.get("path") or "").replace("\\", "/")
        raw_symbol = str(finding.get("symbol") or finding.get("rule") or "unknown")
        scope = _qualified_scope(repo_root, path, int(finding.get("line") or 0), scope_cache)
        symbol = scope if scope.rsplit(".", 1)[-1] == raw_symbol else f"{scope}.{raw_symbol}"
        qualified.append({**finding, "path": path, "symbol": symbol})
    return _suffix_occurrences(qualified)


def collect_current(repo_root: Path) -> dict:
    """Collect fresh expanded-policy finding, complexity, and LOC evidence."""
    inventory = _inventory.build_inventory(repo_root)
    graph = _graph.build_graph(repo_root, inventory)
    analysis = _analyze.run_analysis(repo_root, inventory, graph)
    policy_ruff = _run_policy_ruff(repo_root)
    failed = sorted(
        analyzer
        for analyzer, status in analysis.get("tool_status", {}).items()
        if analyzer != "ruff" and status.get("ok") is not True
    )
    if failed:
        raise QualityEvidenceError("quality evidence unavailable from: " + ", ".join(failed))

    analysis_findings = [
        finding for finding in analysis.get("findings", []) if finding.get("source") != "ruff"
    ]
    raw_findings = (
        [finding for finding in analysis_findings if finding.get("source") != "vulture"]
        + _qualify_vulture_findings(
            repo_root,
            [finding for finding in analysis_findings if finding.get("source") == "vulture"],
        )
        + policy_ruff
    )
    findings = [
        {
            "analyzer": finding.get("source"),
            "rule": finding.get("rule"),
            "path": finding.get("path"),
            "symbol": finding.get("symbol"),
        }
        for finding in raw_findings
        if not finding.get("allowlisted") and finding.get("category") != "complexity"
    ]
    findings.sort(key=lambda finding: _identity_sort_key(_identity(finding)))
    per_file = analysis.get("per_file", {})
    modules = {
        record["path"]: {
            "max_complexity": per_file.get(record["path"], {}).get("max_complexity"),
            "loc": record["loc"],
        }
        for record in inventory["python_files"]
    }
    return {"findings": findings, "modules": modules}


def _load_baseline(repo_root: Path) -> dict:
    path = repo_root / "scripts" / "audit" / "quality-baseline.json"
    if not path.exists():
        raise QualityEvidenceError(
            "quality baseline missing; generate scripts/audit/quality-baseline.json"
        )
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if (
        baseline.get("schema_version") != 1
        or not isinstance(baseline.get("findings"), list)
        or not isinstance(baseline.get("ceilings"), dict)
    ):
        raise QualityEvidenceError("quality baseline has an unsupported schema")
    return baseline


def run_quality_check(repo_root: Path) -> int:
    """Collect evidence, print sorted ratchet results, and return a CLI status."""
    try:
        violations = evaluate_ratchets(collect_current(repo_root), _load_baseline(repo_root))
    except (OSError, ValueError, QualityEvidenceError) as exc:
        print(f"quality: failed - {exc}")
        return 1
    if not violations:
        print("quality: baseline current; no new or enlarged debt")
        return 0

    for finding in violations:
        symbol = f" [{finding['symbol']}]" if finding["symbol"] else ""
        print(
            f"quality: {finding['kind']}: {finding['path']}: "
            f"{finding['analyzer']}/{finding['rule']}{symbol}"
        )
    debt = sum(finding["kind"] != "stale-baseline" for finding in violations)
    stale = len(violations) - debt
    stale_label = "entry" if stale == 1 else "entries"
    print(f"quality: {debt} new/enlarged debt; {stale} stale baseline {stale_label}")
    return 1
