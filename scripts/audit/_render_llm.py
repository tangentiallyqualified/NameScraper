"""Stage 6a: tiered LLM-consumable markdown index."""
from __future__ import annotations

from pathlib import Path

from . import _artifacts

_package_of = _artifacts.package_of


def _flags_suffix(record: dict) -> str:
    marks = []
    if "complexity" in record["flags"]:
        marks.append("⚠ complexity")
    if "low-coverage" in record["flags"]:
        cov = record["coverage_percent"]
        marks.append(f"◌ cov {cov:.0f}%")
    if "dead-code" in record["flags"]:
        marks.append(f"† dead x{record['dead_candidates']}")
    return f" [{' | '.join(marks)}]" if marks else ""


def _header(repo_root: Path) -> str:
    commit = _artifacts.current_commit(repo_root) or "unknown"
    return (f"<!-- Generated at commit {commit}; do not edit. "
            f"regenerate: scripts\\audit.cmd --fast -->\n\n")


def _tests_by_module(inventory: dict) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for t in inventory["test_files"]:
        for mod in t["imports_modules"]:
            mapping.setdefault(mod, []).append(t["path"])
    return mapping


def render(repo_root: Path, inventory: dict, graph: dict, metrics: dict) -> dict[str, str]:
    by_path = {m["path"]: (name, m) for name, m in graph["modules"].items()}
    tests_map = _tests_by_module(inventory)
    packages: dict[str, list[str]] = {}
    for path in sorted(metrics["modules"]):
        packages.setdefault(_package_of(path), []).append(path)

    outputs: dict[str, str] = {}
    index_lines = [_header(repo_root), "# LLM Code Index\n",
                   "One line per module. Detail tiers: " +
                   ", ".join(f"llm/{p}.md" for p in sorted(packages)) + "\n"]
    for package in sorted(packages):
        index_lines.append(f"\n## {package}\n")
        detail = [_header(repo_root), f"# Package detail: {package}\n"]
        for path in packages[package]:
            record = metrics["modules"][path]
            mod_name, mod = by_path.get(path, (path, {"doc": "", "symbols": []}))
            purpose = mod.get("doc") or "(no docstring)"
            index_lines.append(
                f"- `{path}` — {purpose} "
                f"[pub {record['public_symbols']} | in {record['fan_in']} | out {record['fan_out']}]"
                + _flags_suffix(record)
            )
            detail.append(f"\n### `{path}` — {purpose}")
            for sym in mod.get("symbols", []):
                if not sym["public"]:
                    continue
                line = f"- `{sym['signature']}`"
                if sym["doc"]:
                    line += f" — {sym['doc']}"
                if sym["imported_by"]:
                    line += f" (used by: {', '.join(sym['imported_by'])})"
                detail.append(line)
            tests = tests_map.get(mod_name, [])
            if tests:
                detail.append(f"- Tests: {', '.join(sorted(tests))}")
        outputs[f"docs/audit/llm/{package}.md"] = "\n".join(detail) + "\n"
    outputs["docs/audit/llm/INDEX.md"] = "\n".join(index_lines) + "\n"
    return outputs


def run(repo_root: Path, options) -> int:
    outputs = render(
        repo_root,
        _artifacts.read_artifact(repo_root, "inventory"),
        _artifacts.read_artifact(repo_root, "graph"),
        _artifacts.read_artifact(repo_root, "metrics"),
    )
    for rel, content in outputs.items():
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(f"render-llm: {len(outputs)} files under docs/audit/llm/")
    return 0
