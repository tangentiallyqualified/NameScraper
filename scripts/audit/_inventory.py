"""Stage 1: inventory of code, tests, docs, and scripts (ground truth)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from . import _artifacts

EXCLUDED_DIRS = {
    ".venv",
    ".audit",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".worktrees",
    ".scan-dumps",
    ".superpowers",
    ".vscode",
    ".claude",
    "plex_renamer.egg-info",
    ".github",
}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
_GENERATED_AUDIT_DOCS = {
    Path("docs/audit/CHANGES.md"),
    Path("docs/audit/doc-status.md"),
    Path("docs/audit/findings-live.md"),
}
_GENERATED_AUDIT_DIRS = {
    Path("docs/audit/code-index"),
    Path("docs/audit/llm"),
    Path("docs/audit/maps"),
}
_SOURCE_REF = re.compile(r"(?:plex_renamer|scripts|tests)[\w\\/.-]*?\.\w{2,4}")


def _enrolled_set(repo_root: Path) -> set[str] | None:
    enrolled = _artifacts.enrolled_files(repo_root)
    return set(enrolled) if enrolled is not None else None


def _iter_files(repo_root: Path):
    # Enrollment (tracked + untracked-not-ignored) keeps gitignored local-only
    # docs out of the inventory so CI reproduces it byte-for-byte; when git is
    # unavailable (non-git dirs) the walk stands alone.
    enrolled_set = _enrolled_set(repo_root)
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for filename in sorted(filenames):
            if filename in EXCLUDED_DIRS:
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(repo_root)
            if enrolled_set is not None and rel.as_posix() not in enrolled_set:
                continue
            yield path, rel


def _loc(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _test_import_evidence(path: Path) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return [], []
    mods: set[str] = set()
    symbols: set[str] = set()
    imported_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("plex_renamer"):
                    continue
                mods.add(alias.name)
                if alias.asname:
                    imported_names[alias.asname] = alias.name
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("plex_renamer")
        ):
            mods.add(node.module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                target = f"{node.module}.{alias.name}"
                symbols.add(target)
                imported_names[alias.asname or alias.name] = target
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        target = imported_names.get(node.value.id)
        if target is not None:
            symbols.add(f"{target}.{node.attr}")
    return sorted(mods), sorted(symbols)


def _test_imports(path: Path) -> list[str]:
    """Return imported product modules (legacy helper kept for callers)."""
    return _test_import_evidence(path)[0]


def _git_last_touched(repo_root: Path, rel: Path) -> str | None:
    return _artifacts._git(repo_root, "log", "-1", "--format=%cI", "--", rel.as_posix()) or None


def _is_generated_audit_doc(rel: Path) -> bool:
    return rel in _GENERATED_AUDIT_DOCS or any(
        rel.is_relative_to(directory) for directory in _GENERATED_AUDIT_DIRS
    )


def _ref_exists(repo_root: Path, ref: str, enrolled_set: set[str] | None) -> bool:
    # Enrollment membership, not the filesystem: a gitignored file exists on
    # this machine but not in a clean CI checkout, and broken_refs must render
    # identically on both.
    if enrolled_set is not None:
        return ref in enrolled_set
    return (repo_root / ref).exists()


def _doc_record(repo_root: Path, path: Path, rel: Path, enrolled_set: set[str] | None) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    refs = sorted({m.group(0).replace("\\", "/") for m in _SOURCE_REF.finditer(text)})
    broken = [r for r in refs if not _ref_exists(repo_root, r, enrolled_set)]
    last = "generated" if _is_generated_audit_doc(rel) else _git_last_touched(repo_root, rel)
    if last is None:
        last = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
    return {
        "path": rel.as_posix(),
        "last_touched": last,
        "source_refs": refs,
        "broken_refs": broken,
    }


def build_inventory(repo_root: Path) -> dict:
    python_files: list[dict] = []
    test_files: list[dict] = []
    docs: list[dict] = []
    scripts: list[dict] = []
    enrolled_set = _enrolled_set(repo_root)
    for path, rel in _iter_files(repo_root):
        posix = rel.as_posix()
        top = rel.parts[0]
        try:
            if rel.suffix == ".py" and top == "plex_renamer":
                python_files.append(
                    {
                        "path": posix,
                        "package": ".".join(rel.parts[:-1]),
                        "loc": _loc(path),
                        "sha256": _sha(path),
                    }
                )
            elif rel.suffix == ".py" and top == "tests":
                imports_modules, imports_symbols = _test_import_evidence(path)
                test_files.append(
                    {
                        "path": posix,
                        "loc": _loc(path),
                        "imports_modules": imports_modules,
                        "imports_symbols": imports_symbols,
                    }
                )
            elif rel.suffix in DOC_SUFFIXES and (top == "docs" or len(rel.parts) == 1):
                if not _is_generated_audit_doc(rel):
                    docs.append(_doc_record(repo_root, path, rel, enrolled_set))
            elif top == "scripts":
                scripts.append({"path": posix})
        except OSError:
            continue  # unreadable entry (broken symlink, permission hole) - skip, don't abort
    return {
        "python_files": python_files,
        "test_files": test_files,
        "docs": docs,
        "scripts": scripts,
    }


def run(repo_root: Path, options) -> int:
    inventory = build_inventory(repo_root)
    _artifacts.write_artifact(repo_root, "inventory", inventory)
    print(f"inventory: {len(inventory['python_files'])} package files indexed")
    return 0
