"""No-new-debt comparisons for normalized audit findings and numeric ceilings."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from . import (
    _analyze,
    _artifacts,
    _coverage,
    _graph,
    _inventory,
    _quality_refresh,
    _quality_static,
    _ratchet_identity,
)
from ._decisions import filter_open

_POLICY = tomllib.loads((Path(__file__).parent / "policy.toml").read_text(encoding="utf-8"))
MAX_CYCLOMATIC_COMPLEXITY = _POLICY["quality"]["max_cyclomatic_complexity"]
MAX_PYTHON_FILE_LOC = _POLICY["quality"]["max_python_file_loc"]
CHANGED_LINE_MIN_PERCENT = _POLICY["quality"]["changed_line_min_percent"]
_QUALITY_PYTHON_ROOTS = {"plex_renamer", "scripts", "tests"}

Finding = dict[str, object]


class QualityEvidenceError(RuntimeError):
    """Raised when complete quality evidence cannot be collected."""


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


_normalized_python_files = _quality_static.normalized_python_files


def _build_baseline(current: dict, legacy_python_files: list[str]) -> dict:
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
    ceilings: dict[str, dict[str, int]] = {}
    for path, metrics in sorted(current.get("modules", {}).items()):
        value = metrics.get("loc")
        saved = {"loc": value} if isinstance(value, int) and value > MAX_PYTHON_FILE_LOC else {}
        if saved:
            ceilings[path.replace("\\", "/")] = saved
    current_python_files = set(_normalized_python_files(current.get("python_files")))
    preserved_legacy_python_files = sorted(
        current_python_files & set(_normalized_python_files(legacy_python_files))
    )
    baseline = {
        "schema_version": 2,
        "findings": findings,
        "ceilings": ceilings,
        "complexity": {
            path.replace("\\", "/"): {
                str(symbol): value
                for symbol, value in sorted(blocks.items())
                if isinstance(value, int) and value > MAX_CYCLOMATIC_COMPLEXITY
            }
            for path, blocks in sorted(current.get("complexity", {}).items())
            if any(
                isinstance(value, int) and value > MAX_CYCLOMATIC_COMPLEXITY
                for value in blocks.values()
            )
        },
        "formatting": {
            path.replace("\\", "/"): str(digest)
            for path, digest in sorted(current.get("formatting", {}).items())
        },
        "typing": {"legacy_python_files": preserved_legacy_python_files},
    }
    if isinstance(current.get("coverage"), dict):
        baseline["coverage"] = _coverage.build_quality_baseline(
            current["coverage"], CHANGED_LINE_MIN_PERCENT
        )
    return baseline


def _bootstrap_quality_baseline_once(current: dict) -> dict:
    """Seed the one-time legacy inventory; routine refreshes must not call this."""
    return _build_baseline(current, _normalized_python_files(current.get("python_files")))


def build_baseline(current: dict, previous_baseline: dict, accept_enlarged: bool = False) -> dict:
    """Refresh current evidence while preserving/pruning the frozen legacy inventory."""
    if not accept_enlarged and isinstance(previous_baseline.get("coverage"), dict):
        if not isinstance(current.get("coverage"), dict):
            raise QualityEvidenceError("current coverage evidence missing")
        result = _coverage.evaluate_quality_coverage(
            current["coverage"],
            previous_baseline["coverage"],
            CHANGED_LINE_MIN_PERCENT,
        )
        if result["violations"]:
            descriptions = ", ".join(
                f"{item['kind']} ({item['path']}: {item['baseline']} -> {item['current']})"
                for item in result["violations"]
            )
            raise QualityEvidenceError(f"coverage gate failed: {descriptions}")
    previous_typing = previous_baseline.get("typing", {})
    return _build_baseline(
        current,
        _normalized_python_files(previous_typing.get("legacy_python_files")),
    )


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


def _sort_key(finding: Finding) -> tuple[str, str, str, str, str, str]:
    return (
        str(finding["path"]),
        str(finding["analyzer"]),
        str(finding["rule"]),
        str(finding["symbol"] or ""),
        str(finding["kind"]),
        str(finding["metric"] or ""),
    )


def _finding_ratchet_violations(current: dict, baseline: dict) -> list[Finding]:
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
    return violations


def evaluate_ratchets(current: dict, baseline: dict) -> list[Finding]:
    """Return deterministic ratchet violations between current and baseline evidence."""
    violations = _finding_ratchet_violations(current, baseline)
    violations.extend(
        _quality_static.loc_violations(
            current.get("modules"), baseline.get("ceilings"), MAX_PYTHON_FILE_LOC
        )
    )
    violations.extend(
        _quality_static.complexity_violations(current, baseline, MAX_CYCLOMATIC_COMPLEXITY)
    )
    violations.extend(_quality_static.formatting_violations(current, baseline))
    current_python_files = set(_normalized_python_files(current.get("python_files")))
    legacy_python_files = set(
        _normalized_python_files(baseline.get("typing", {}).get("legacy_python_files"))
    )
    violations.extend(
        {
            "analyzer": "pyright",
            "baseline": None,
            "current": None,
            "kind": "stale-baseline",
            "message": "legacy Python file is no longer present",
            "metric": None,
            "path": path,
            "rule": "legacy-file",
            "symbol": None,
        }
        for path in sorted(legacy_python_files - current_python_files)
    )
    current_coverage = current.get("coverage")
    baseline_coverage = baseline.get("coverage")
    if isinstance(current_coverage, dict) and isinstance(baseline_coverage, dict):
        coverage_result = _coverage.evaluate_quality_coverage(
            current_coverage, baseline_coverage, CHANGED_LINE_MIN_PERCENT
        )
        for item in coverage_result["violations"]:
            debt_kind, message, rule = _quality_refresh.coverage_ratchet_fields(item["kind"])
            violations.append(
                {
                    "analyzer": "coverage",
                    "baseline": item["baseline"],
                    "current": item["current"],
                    "kind": debt_kind,
                    "message": message,
                    "metric": "coverage_percent",
                    "path": item["path"],
                    "rule": rule,
                    "symbol": None,
                }
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
        encoding="utf-8",
        errors="strict",
        timeout=300,
    )
    if result.returncode not in (0, 1):
        raise QualityEvidenceError(f"ruff failed: {result.stderr.strip()[:200]}")
    if result.returncode == 1 and not result.stdout.strip():
        raise QualityEvidenceError(f"ruff exited 1 with no output: {result.stderr.strip()[:200]}")
    findings, scope_cache = [], {}
    for item in json.loads(result.stdout or "[]"):
        path = _analyze._rel_to_repo(repo_root, item["filename"])
        line = item["location"]["row"]
        scope = _ratchet_identity.qualified_scope(repo_root, path, line, scope_cache)
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
    return _ratchet_identity.suffix_occurrences(findings)


_run_policy_format = _quality_static.run_policy_format
_run_policy_pyright = _quality_static.run_policy_pyright
_quality_complexity = _quality_static.quality_complexity


def _git_tracked_files(repo_root: Path) -> set[str]:
    """Repo-relative paths git tracks under the quality roots.

    Quality-ratchet evidence must reflect only checked-in state: a
    gitignored/untracked local file (e.g. a developer scratch script) must
    not produce findings that a clean CI checkout would never see.
    """
    tracked = _artifacts.tracked_files(repo_root, *sorted(_QUALITY_PYTHON_ROOTS))
    if tracked is None:
        raise QualityEvidenceError("git ls-files failed; quality evidence needs tracked files")
    return set(tracked)


def _repository_python_records(repo_root: Path) -> list[dict]:
    tracked = _git_tracked_files(repo_root)
    records = []
    for root_name in sorted(_QUALITY_PYTHON_ROOTS):
        quality_root = repo_root / root_name
        if not quality_root.is_dir():
            continue
        for path, relative_to_root in _inventory._iter_files(quality_root):
            if relative_to_root.suffix != ".py":
                continue
            relative = Path(root_name) / relative_to_root
            relative_posix = relative.as_posix()
            if relative_posix not in tracked:
                continue
            try:
                loc = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            records.append({"path": relative_posix, "loc": loc})
    return records


def _failed_analyzers(analysis: dict) -> list[str]:
    return sorted(
        analyzer
        for analyzer, status in analysis.get("tool_status", {}).items()
        if analyzer != "ruff" and status.get("ok") is not True
    )


def _quality_findings(
    repo_root: Path,
    analysis: dict,
    policy_ruff: list[dict],
    policy_pyright: list[dict],
) -> list[dict]:
    analysis_findings = [f for f in analysis.get("findings", []) if f.get("source") != "ruff"]
    raw_findings = (
        [finding for finding in analysis_findings if finding.get("source") != "vulture"]
        + _ratchet_identity.qualify_vulture_findings(
            repo_root,
            [finding for finding in analysis_findings if finding.get("source") == "vulture"],
        )
        + policy_ruff
        + policy_pyright
    )
    findings = [
        {
            "analyzer": finding.get("source"),
            "rule": finding.get("rule"),
            "path": finding.get("path"),
            "symbol": finding.get("symbol"),
        }
        for finding in raw_findings
        if finding.get("category") != "complexity"
    ]
    findings = filter_open(repo_root, findings)
    findings.sort(key=lambda finding: _identity_sort_key(_identity(finding)))
    return findings


def _quality_modules(
    repo_root: Path, inventory: dict, analysis: dict, numeric_records: list[dict]
) -> dict[str, dict]:
    product_paths = {record["path"] for record in inventory["python_files"]}
    extra_records = [record for record in numeric_records if record["path"] not in product_paths]
    per_file = dict(analysis.get("per_file", {}))
    try:
        _extra_findings, extra_per_file = _analyze._run_radon(
            repo_root, {"python_files": extra_records}
        )
    except Exception as exc:
        raise QualityEvidenceError(f"quality Radon evidence unavailable: {exc}") from exc
    per_file.update(extra_per_file)
    return {
        record["path"]: {
            "max_complexity": per_file.get(record["path"], {}).get("max_complexity"),
            "loc": record["loc"],
        }
        for record in numeric_records
    }


def _is_untracked_quality_python(path: object, tracked: set[str]) -> bool:
    normalized = str(path or "").replace("\\", "/")
    if not normalized.endswith(".py") or normalized in tracked:
        return False
    return normalized.split("/", 1)[0] in _QUALITY_PYTHON_ROOTS


def collect_current(repo_root: Path, baseline: dict | None = None) -> dict:
    """Collect fresh expanded-policy finding, complexity, and LOC evidence."""
    inventory = _inventory.build_inventory(repo_root)
    graph = _graph.build_graph(repo_root, inventory)
    analysis = _analyze.run_analysis(repo_root, inventory, graph)
    policy_ruff = _run_policy_ruff(repo_root)
    tracked = _git_tracked_files(repo_root)
    python_records = _repository_python_records(repo_root)
    python_files = sorted(record["path"] for record in python_records)
    formatting = _run_policy_format(repo_root, python_files)
    legacy_python_files = _normalized_python_files(
        (baseline or {}).get("typing", {}).get("legacy_python_files")
    )
    policy_pyright = _run_policy_pyright(repo_root, python_files, legacy_python_files)
    failed = _failed_analyzers(analysis)
    if failed:
        raise QualityEvidenceError("quality evidence unavailable from: " + ", ".join(failed))
    findings = [
        finding
        for finding in _quality_findings(repo_root, analysis, policy_ruff, policy_pyright)
        if not _is_untracked_quality_python(finding.get("path"), tracked)
    ]
    return {
        "findings": findings,
        "modules": _quality_modules(repo_root, inventory, analysis, python_records),
        "complexity": _quality_complexity(repo_root, python_records),
        "formatting": formatting,
        "python_files": python_files,
    }


def _load_baseline(repo_root: Path) -> dict:
    path = repo_root / "scripts" / "audit" / "quality-baseline.json"
    if not path.exists():
        raise QualityEvidenceError(
            "quality baseline missing; generate scripts/audit/quality-baseline.json"
        )
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(baseline, dict)
        or baseline.get("schema_version") != 2
        or not isinstance(baseline.get("findings"), list)
        or not isinstance(baseline.get("ceilings"), dict)
        or not isinstance(baseline.get("complexity"), dict)
        or not isinstance(baseline.get("formatting"), dict)
        or not isinstance(baseline.get("typing"), dict)
        or not isinstance(baseline["typing"].get("legacy_python_files"), list)
    ):
        raise QualityEvidenceError("quality baseline has an unsupported schema")
    coverage = baseline.get("coverage")
    if coverage is not None and (
        not isinstance(coverage, dict)
        or coverage.get("changed_line_min_percent") != CHANGED_LINE_MIN_PERCENT
        or coverage.get("full_suite") is not True
        or not isinstance(coverage.get("executable_lines"), dict)
        or not isinstance(coverage.get("package_floors"), dict)
    ):
        raise QualityEvidenceError("quality baseline has unsupported coverage policy")
    return baseline


def run_quality_baseline_update(
    repo_root: Path,
    accept_enlarged: bool = False,
    expected_entries: tuple[str, ...] | list[str] = (),
) -> int:
    """Refresh a supported baseline without ever seeding newly discovered Python files."""
    try:
        previous = _load_baseline(repo_root)
        current = collect_current(repo_root, previous)
        current["coverage"] = _coverage.collect_quality_coverage(repo_root)
        _quality_refresh.gate_refresh_debt(
            evaluate_ratchets(current, previous),
            accept_enlarged,
            expected_entries,
        )
        baseline = build_baseline(current, previous, accept_enlarged)
        path = repo_root / "scripts" / "audit" / "quality-baseline.json"
        path.write_text(
            json.dumps(baseline, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except _quality_refresh.QualityBaselineRefused as exc:
        print(f"quality baseline: refused - {exc}")
        return 1
    except (OSError, ValueError, QualityEvidenceError, _coverage.CoverageEvidenceError) as exc:
        print(f"quality baseline: failed - {exc}")
        return 1

    findings = len(baseline["findings"])
    ceilings = len(baseline["ceilings"])
    legacy_files = len(baseline["typing"]["legacy_python_files"])
    legacy_label = "file" if legacy_files == 1 else "files"
    print(
        f"quality baseline: updated - {findings} findings; {ceilings} ceilings; "
        f"{legacy_files} legacy Python {legacy_label}"
    )
    return 0


def run_quality_check(repo_root: Path) -> int:
    """Collect evidence, print sorted ratchet results, and return a CLI status."""
    try:
        baseline = _load_baseline(repo_root)
        if not isinstance(baseline.get("coverage"), dict):
            raise QualityEvidenceError(
                "quality baseline coverage missing; run --update-quality-baseline"
            )
        current = collect_current(repo_root, baseline)
        current["coverage"] = _coverage.collect_quality_coverage(repo_root)
        violations = evaluate_ratchets(current, baseline)
    except (OSError, ValueError, QualityEvidenceError, _coverage.CoverageEvidenceError) as exc:
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
    return 1 if debt else 0
