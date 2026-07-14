"""Stable qualified analyzer identities for quality ratchets."""

from __future__ import annotations

import ast
from pathlib import Path

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


def qualified_scope(
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


def _occurrence_group_key(finding: dict) -> tuple[str, str, str, str]:
    return (
        str(finding.get("source") or finding.get("analyzer") or "unknown"),
        str(finding.get("rule") or "unknown"),
        str(finding.get("path") or "").replace("\\", "/"),
        str(finding.get("symbol") or "unknown"),
    )


def _occurrence_order_key(finding: dict) -> tuple[int, int, str]:
    return (
        int(finding.get("line") or 0),
        int(finding.get("column") or 0),
        str(finding.get("message") or ""),
    )


def suffix_occurrences(findings: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for finding in findings:
        groups.setdefault(_occurrence_group_key(finding), []).append(finding)

    qualified: list[dict] = []
    for key in sorted(groups):
        base_symbol = key[3]
        for occurrence, finding in enumerate(sorted(groups[key], key=_occurrence_order_key), 1):
            qualified.append({**finding, "symbol": f"{base_symbol}#{occurrence}"})
    return qualified


def qualify_vulture_findings(repo_root: Path, findings: list[dict]) -> list[dict]:
    scope_cache: dict[str, list[tuple[int, int, int, str]]] = {}
    qualified = []
    for finding in findings:
        path = str(finding.get("path") or "").replace("\\", "/")
        raw_symbol = str(finding.get("symbol") or finding.get("rule") or "unknown")
        scope = qualified_scope(repo_root, path, int(finding.get("line") or 0), scope_cache)
        symbol = scope if scope.rsplit(".", 1)[-1] == raw_symbol else f"{scope}.{raw_symbol}"
        qualified.append({**finding, "path": path, "symbol": symbol})
    return suffix_occurrences(qualified)
