"""Formatter and qualified-block complexity evidence for quality ratchets."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from . import _ratchet_identity

Finding = dict[str, Any]
MetricMap = dict[str, dict[str, Any]]


def _normalized_map(records: object) -> MetricMap:
    if not isinstance(records, dict):
        return {}
    normalized: MetricMap = {}
    raw_records = cast(dict[object, object], records)
    for path, metrics in sorted(raw_records.items(), key=lambda item: str(item[0])):
        if isinstance(metrics, dict):
            normalized[str(path).replace("\\", "/")] = cast(dict[str, Any], metrics)
    return normalized


def _loc_violation(path: str, kind: str, current: int | None, baseline: int | None) -> Finding:
    if kind == "enlarged-debt":
        message = f"loc increased from {baseline} to {current}"
    elif kind == "stale-baseline":
        message = f"baseline loc ceiling {baseline} is stale; current is {current}"
    else:
        message = f"new loc debt at {current}"
    return {
        "analyzer": "inventory",
        "baseline": baseline,
        "current": current,
        "kind": kind,
        "message": message,
        "metric": "loc",
        "path": path.replace("\\", "/"),
        "rule": "LOC",
        "symbol": None,
    }


def _new_loc_violations(
    current_modules: MetricMap, baseline_ceilings: MetricMap, threshold: int
) -> list[Finding]:
    violations: list[Finding] = []
    for path, metrics in current_modules.items():
        current_value = metrics.get("loc")
        if not isinstance(current_value, int) or current_value <= threshold:
            continue
        baseline_value = baseline_ceilings.get(path, {}).get("loc")
        if not isinstance(baseline_value, int):
            violations.append(_loc_violation(path, "new-debt", current_value, None))
        elif current_value > baseline_value:
            violations.append(_loc_violation(path, "enlarged-debt", current_value, baseline_value))
    return violations


def _stale_loc_violations(
    current_modules: MetricMap, baseline_ceilings: MetricMap, threshold: int
) -> list[Finding]:
    violations: list[Finding] = []
    for path, ceilings in baseline_ceilings.items():
        baseline_value = ceilings.get("loc")
        if not isinstance(baseline_value, int):
            continue
        current_value = current_modules.get(path, {}).get("loc")
        if baseline_value <= threshold or (
            current_value != baseline_value
            and (not isinstance(current_value, int) or current_value < baseline_value)
        ):
            violations.append(_loc_violation(path, "stale-baseline", current_value, baseline_value))
    return violations


def loc_violations(current: object, baseline: object, threshold: int) -> list[Finding]:
    current_modules = _normalized_map(current)
    baseline_ceilings = _normalized_map(baseline)
    return _new_loc_violations(
        current_modules, baseline_ceilings, threshold
    ) + _stale_loc_violations(current_modules, baseline_ceilings, threshold)


def _complexity_violation(
    path: str, symbol: str, kind: str, current: int | None, baseline: int | None
) -> Finding:
    if kind == "enlarged-debt":
        message = f"complexity increased from {baseline} to {current}"
    elif kind == "stale-baseline":
        message = f"baseline complexity ceiling {baseline} is stale; current is {current}"
    else:
        message = f"new complexity debt at {current}"
    return {
        "analyzer": "radon",
        "baseline": baseline,
        "current": current,
        "kind": kind,
        "message": message,
        "metric": "complexity",
        "path": path.replace("\\", "/"),
        "rule": "CC",
        "symbol": symbol,
    }


def _new_complexity_violations(
    current_blocks: MetricMap, baseline_blocks: MetricMap, threshold: int
) -> list[Finding]:
    violations: list[Finding] = []
    for path, blocks in current_blocks.items():
        ceilings = baseline_blocks.get(path, {})
        for symbol, current_value in blocks.items():
            if not isinstance(current_value, int) or current_value <= threshold:
                continue
            baseline_value = ceilings.get(symbol)
            if not isinstance(baseline_value, int):
                violations.append(
                    _complexity_violation(path, symbol, "new-debt", current_value, None)
                )
            elif current_value > baseline_value:
                violations.append(
                    _complexity_violation(
                        path, symbol, "enlarged-debt", current_value, baseline_value
                    )
                )
    return violations


def _stale_complexity_violations(
    current_blocks: MetricMap, baseline_blocks: MetricMap, threshold: int
) -> list[Finding]:
    violations: list[Finding] = []
    for path, ceilings in baseline_blocks.items():
        blocks = current_blocks.get(path, {})
        for symbol, baseline_value in ceilings.items():
            current_value = blocks.get(symbol)
            if not isinstance(baseline_value, int):
                continue
            if baseline_value <= threshold or (
                current_value != baseline_value
                and (not isinstance(current_value, int) or current_value < baseline_value)
            ):
                violations.append(
                    _complexity_violation(
                        path, symbol, "stale-baseline", current_value, baseline_value
                    )
                )
    return violations


def complexity_violations(
    current: dict[str, Any], baseline: dict[str, Any], threshold: int
) -> list[Finding]:
    current_blocks = _normalized_map(current.get("complexity"))
    baseline_blocks = _normalized_map(baseline.get("complexity"))
    return _new_complexity_violations(
        current_blocks, baseline_blocks, threshold
    ) + _stale_complexity_violations(current_blocks, baseline_blocks, threshold)


def _formatting_violation(
    path: str, kind: str, current: str | None, baseline: str | None
) -> Finding:
    messages = {
        "new-debt": "new unformatted Python file",
        "enlarged-debt": "legacy unformatted Python file changed without being formatted",
        "stale-baseline": "baseline formatter debt is no longer present",
    }
    return {
        "analyzer": "ruff-format",
        "baseline": baseline,
        "current": current,
        "kind": kind,
        "message": messages[kind],
        "metric": None,
        "path": path.replace("\\", "/"),
        "rule": "format",
        "symbol": None,
    }


def _formatting_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    records = cast(dict[object, object], value)
    return {str(path).replace("\\", "/"): str(digest) for path, digest in records.items()}


def formatting_violations(current: dict[str, Any], baseline: dict[str, Any]) -> list[Finding]:
    current_debt = _formatting_map(current.get("formatting"))
    baseline_debt = _formatting_map(baseline.get("formatting"))
    violations: list[Finding] = []
    for path, current_digest in sorted(current_debt.items()):
        baseline_digest = baseline_debt.get(path)
        if baseline_digest is None:
            violations.append(_formatting_violation(path, "new-debt", current_digest, None))
        elif current_digest != baseline_digest:
            violations.append(
                _formatting_violation(path, "enlarged-debt", current_digest, baseline_digest)
            )
    violations.extend(
        _formatting_violation(path, "stale-baseline", None, baseline_debt[path])
        for path in sorted(set(baseline_debt) - set(current_debt))
    )
    return violations


def run_policy_format(repo_root: Path, python_files: list[str]) -> dict[str, str]:
    """Return raw-content hashes for the exact set of currently unformatted files."""
    unformatted: dict[str, str] = {}
    for path in python_files:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--check", "--silent", "--no-cache", path],
            cwd=repo_root,
            capture_output=True,
            encoding="utf-8",
            errors="strict",
            timeout=300,
        )
        if result.returncode == 0:
            continue
        if result.returncode != 1:
            raise ValueError(f"ruff format failed for {path}: {result.stderr.strip()[:200]}")
        try:
            digest = hashlib.sha256((repo_root / path).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f"could not hash formatter evidence for {path}") from exc
        unformatted[path] = f"sha256:{digest}"
    return unformatted


def _radon_blocks(block: Any) -> list[Any]:
    result = [block]
    for child in list(getattr(block, "closures", []) or []):
        result.extend(_radon_blocks(child))
    for child in list(getattr(block, "methods", []) or []):
        result.extend(_radon_blocks(child))
    for child in list(getattr(block, "inner_classes", []) or []):
        result.extend(_radon_blocks(child))
    return result


def quality_complexity(
    repo_root: Path, numeric_records: list[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    cc_visit = cast(Callable[[str], list[Any]], import_module("radon.complexity").cc_visit)

    scope_cache: dict[str, list[tuple[int, int, int, str]]] = {}
    result: dict[str, dict[str, int]] = {}
    for record in numeric_records:
        path = str(record["path"])
        try:
            code = (repo_root / path).read_text(encoding="utf-8-sig", errors="replace")
            roots = cc_visit(code)
        except (OSError, SyntaxError) as exc:
            raise ValueError(f"quality Radon evidence unavailable for {path}: {exc}") from exc
        unique: dict[tuple[str, int, int, str], Any] = {}
        for root in roots:
            for block in _radon_blocks(root):
                key = (
                    type(block).__name__,
                    int(getattr(block, "lineno", 0)),
                    int(getattr(block, "endline", 0)),
                    str(getattr(block, "name", "")),
                )
                unique[key] = block
        grouped: dict[str, list[Any]] = {}
        for block in unique.values():
            symbol = _ratchet_identity.qualified_scope(
                repo_root, path, int(getattr(block, "lineno", 0)), scope_cache
            )
            grouped.setdefault(symbol, []).append(block)
        blocks: dict[str, int] = {}
        for symbol, matches in sorted(grouped.items()):
            ordered = sorted(
                matches,
                key=lambda block: (
                    int(getattr(block, "lineno", 0)),
                    int(getattr(block, "endline", 0)),
                ),
            )
            for number, block in enumerate(ordered, start=1):
                qualified = f"{symbol}#{number}" if len(ordered) > 1 else symbol
                blocks[qualified] = int(block.complexity)
        result[path] = blocks
    return result
