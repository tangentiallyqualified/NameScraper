"""Stage 6a: tiered code index."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from . import _artifacts

_package_of = _artifacts.package_of

_DEAD_TIER_LABELS = (
    ("high-confidence", "high"),
    ("medium-confidence", "medium"),
    ("low-confidence", "low"),
    ("test-referenced", "test-referenced"),
    ("protected-or-ambiguous", "protected/ambiguous"),
    ("allowlisted", "allowlisted"),
)


def _dead_tiers(record: dict, findings: list[dict] | None = None) -> dict[str, int] | None:
    """Return additive tier counts, or None for a legacy aggregate record."""
    if record.get("dead_evidence_usable") is False:
        return None
    if isinstance(record.get("dead_tiers"), dict):
        return {key: int(record["dead_tiers"].get(key, 0)) for key, _ in _DEAD_TIER_LABELS}

    scalar_keys = {
        "high-confidence": "dead_high_confidence",
        "medium-confidence": "dead_medium_confidence",
        "low-confidence": "dead_exact_low_confidence",
        "test-referenced": "dead_test_referenced",
        "protected-or-ambiguous": "dead_protected_ambiguous",
        "allowlisted": "dead_allowlisted",
    }
    # ``dead_high_confidence`` alone existed before tiered metrics. Require at
    # least one new scalar before treating this as separated evidence.
    if any(key in record for tier, key in scalar_keys.items() if tier != "high-confidence"):
        return {tier: int(record.get(key, 0)) for tier, key in scalar_keys.items()}

    if findings is None:
        return None
    tiers = {key: 0 for key, _ in _DEAD_TIER_LABELS}
    for finding in findings:
        if finding.get("category") != "dead-code":
            continue
        if finding.get("allowlisted"):
            tier = "allowlisted"
        else:
            assessment = finding.get("assessment", "low-confidence")
            tier = assessment if assessment in {
                "high-confidence", "medium-confidence", "low-confidence", "test-referenced"
            } else "protected-or-ambiguous"
        tiers[tier] += 1
    return tiers


def _flags_suffix(record: dict, findings: list[dict] | None = None) -> str:
    marks = []
    if "complexity" in record["flags"]:
        marks.append("\u26a0 complexity")
    if "low-coverage" in record["flags"]:
        cov = record["coverage_percent"]
        marks.append(f"\u25cc cov {cov:.0f}%")
    tiers = _dead_tiers(record, findings)
    if tiers is not None and any(tiers.values()):
        summary = " | ".join(
            f"{label} x{tiers[key]}" for key, label in _DEAD_TIER_LABELS if tiers[key]
        )
        marks.append(f"\u2020 dead {summary}")
    elif "dead-code" in record["flags"]:
        marks.append(f"\u2020 dead x{record['dead_candidates']}")
    return f" [{' | '.join(marks)}]" if marks else ""


def _header(repo_root: Path, metrics: dict | None = None) -> str:
    digest = (metrics or {}).get("input_digest") or "unknown"
    return (f"<!-- Generated from audit input {digest[:12]}; do not edit. "
            f"regenerate: scripts\\audit.cmd --fast -->\n\n")


def _evidence_warnings(metrics: dict, analysis: dict | None) -> list[str]:
    """Warnings are repeated because every code-index detail file is standalone."""
    lines: list[str] = []
    status = metrics.get("tool_status")
    if not isinstance(status, dict) and analysis is not None:
        status = analysis.get("tool_status")
    expected_tools = ("ruff", "vulture", "radon", "deps", "contracts")
    if not status:
        lines.append("> WARNING: Analyzer status unavailable; findings may be incomplete.")
    else:
        for tool in expected_tools:
            if tool not in status:
                lines.append(
                    f"> WARNING: Analyzer `{tool}` unavailable (status missing); "
                    "its findings are incomplete."
                )
        for tool, detail in sorted(status.items()):
            if not isinstance(detail, dict) or not detail.get("ok"):
                reason = detail.get("reason") if isinstance(detail, dict) else None
                suffix = f" ({reason})" if reason else ""
                impact = (
                    " its dead-code counts and clean claims are unavailable."
                    if tool == "vulture" else " its findings are incomplete."
                )
                lines.append(
                    f"> WARNING: Analyzer `{tool}` unavailable{suffix};{impact}"
                )

    coverage = metrics.get("coverage")
    if isinstance(coverage, dict):
        if not coverage.get("usable"):
            reason = coverage.get("reason") or "unavailable evidence"
            lines.append(
                f"> WARNING: Coverage evidence ignored ({reason}); coverage percentages are omitted."
            )
    else:
        headline = metrics.get("headline", {})
        legacy_reasons = [
            name for name in ("stale", "partial", "failed")
            if headline.get(f"coverage_{name}")
        ]
        if legacy_reasons:
            lines.append(
                "> WARNING: Coverage evidence ignored "
                f"({', '.join(legacy_reasons)}); coverage percentages are omitted."
            )
    return lines


def _tests_by_module(inventory: dict) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for t in inventory["test_files"]:
        for mod in t["imports_modules"]:
            mapping.setdefault(mod, []).append(t["path"])
    return mapping


def render(
    repo_root: Path,
    inventory: dict,
    graph: dict,
    metrics: dict,
    analysis: dict | None = None,
) -> dict[str, str]:
    by_path = {m["path"]: (name, m) for name, m in graph["modules"].items()}
    tests_map = _tests_by_module(inventory)
    packages: dict[str, list[str]] = {}
    for path in sorted(metrics["modules"]):
        packages.setdefault(_package_of(path), []).append(path)

    findings_by_path: dict[str, list[dict]] = {}
    if analysis is not None:
        for finding in analysis.get("findings", []):
            findings_by_path.setdefault(finding.get("path", ""), []).append(finding)
    warnings = _evidence_warnings(metrics, analysis)
    warning_block = "\n".join(warnings)

    outputs: dict[str, str] = {}
    index_lines = [_header(repo_root, metrics), "# Code Index\n"]
    if warning_block:
        index_lines.append(warning_block + "\n")
    index_lines.append(
        "One line per module. Detail tiers: "
        + ", ".join(f"code-index/{p}.md" for p in sorted(packages)) + "\n"
    )
    for package in sorted(packages):
        index_lines.append(f"\n## {package}\n")
        detail = [_header(repo_root, metrics), f"# Package detail: {package}\n"]
        if warning_block:
            detail.append(warning_block + "\n")
        for path in packages[package]:
            record = metrics["modules"][path]
            mod_name, mod = by_path.get(path, (path, {"doc": "", "symbols": []}))
            purpose = mod.get("doc") or "(no docstring)"
            index_lines.append(
                f"- `{path}` \u2014 {purpose} "
                f"[pub {record['public_symbols']} | in {record['fan_in']} | out {record['fan_out']}]"
                + _flags_suffix(record, findings_by_path.get(path) if analysis is not None else None)
            )
            detail.append(f"\n### `{path}` \u2014 {purpose}")
            for sym in mod.get("symbols", []):
                if not sym["public"]:
                    continue
                line = (
                    f"- `{sym['signature']}` \u2014 "
                    f"{sym['doc'] or '(no docstring)'}"
                )
                if sym["imported_by"]:
                    line += f" (used by: {', '.join(sym['imported_by'])})"
                detail.append(line)
            tests = tests_map.get(mod_name, [])
            if tests:
                detail.append(f"- Tests: {', '.join(sorted(tests))}")
        outputs[f"docs/audit/code-index/{package}.md"] = "\n".join(detail) + "\n"
    outputs["docs/audit/code-index/INDEX.md"] = "\n".join(index_lines) + "\n"
    return outputs


def _entry_is_reparse(entry: os.DirEntry) -> bool:
    is_junction = getattr(entry, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _path_is_reparse(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


class UnsafeGeneratedOutputError(RuntimeError):
    def __init__(self, paths: list[Path]) -> None:
        self.paths = sorted(path.as_posix() for path in paths)
        super().__init__(
            "unsafe generated output contains link-like paths: "
            + ", ".join(self.paths)
        )


def _unsafe_link_paths(root: Path) -> list[Path]:
    if not os.path.lexists(root):
        return []
    if root.is_symlink() or _path_is_reparse(root):
        return [root]
    unsafe: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink() or _entry_is_reparse(entry):
                    unsafe.append(path)
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
    return sorted(unsafe)


def _remove_tree_without_following_links(root: Path) -> None:
    with os.scandir(root) as entries:
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink() or _entry_is_reparse(entry):
                raise UnsafeGeneratedOutputError([path])
            elif entry.is_dir(follow_symlinks=False):
                _remove_tree_without_following_links(path)
            else:
                path.unlink()
    root.rmdir()


def _markdown_pages_without_following_links(root: Path):
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink() or _entry_is_reparse(entry):
                    raise UnsafeGeneratedOutputError([Path(entry.path)])
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix == ".md":
                    yield path


def _remove_stale_outputs(repo_root: Path, outputs: dict[str, str]) -> None:
    """Remove only Markdown trees owned by this renderer."""
    audit_dir = repo_root / "docs" / "audit"
    legacy_dir = audit_dir / "llm"
    code_index_dir = audit_dir / "code-index"
    unsafe = _unsafe_link_paths(legacy_dir) + _unsafe_link_paths(code_index_dir)
    if unsafe:
        raise UnsafeGeneratedOutputError(unsafe)

    if legacy_dir.exists():
        _remove_tree_without_following_links(legacy_dir)

    expected = {repo_root / rel for rel in outputs}
    if code_index_dir.exists():
        for page in _markdown_pages_without_following_links(code_index_dir):
            if page not in expected:
                page.unlink()


def run(repo_root: Path, options) -> int:
    outputs = render(
        repo_root,
        _artifacts.read_artifact(repo_root, "inventory"),
        _artifacts.read_artifact(repo_root, "graph"),
        _artifacts.read_artifact(repo_root, "metrics"),
        _artifacts.read_artifact(repo_root, "analysis"),
    )
    _remove_stale_outputs(repo_root, outputs)
    for rel, content in outputs.items():
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _artifacts.write_text_lf(target, content)
    print(f"render-code-index: {len(outputs)} files under docs/audit/code-index/")
    return 0
