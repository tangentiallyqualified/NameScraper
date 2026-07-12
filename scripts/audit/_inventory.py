"""Stage 1: inventory of code, tests, docs, and scripts (ground truth)."""
from __future__ import annotations

import ast
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import _artifacts

EXCLUDED_DIRS = {
    ".venv", ".audit", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".worktrees", ".scan-dumps", ".superpowers", ".vscode",
    ".claude", "plex_renamer.egg-info", ".github",
}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
_SOURCE_REF = re.compile(r"(?:plex_renamer|scripts|tests)[\w\\/.-]*?\.\w{2,4}")


def _iter_files(repo_root: Path):
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            yield path, path.relative_to(repo_root)


def _loc(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _test_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names if a.name.startswith("plex_renamer"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("plex_renamer"):
            mods.add(node.module)
    return sorted(mods)


def _git_last_touched(repo_root: Path, rel: Path) -> str | None:
    return _artifacts._git(repo_root, "log", "-1", "--format=%cI", "--", rel.as_posix()) or None


def _doc_record(repo_root: Path, path: Path, rel: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    refs = sorted({m.group(0).replace("\\", "/") for m in _SOURCE_REF.finditer(text)})
    broken = [r for r in refs if not (repo_root / r).exists()]
    last = _git_last_touched(repo_root, rel)
    if last is None:
        last = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    return {"path": rel.as_posix(), "last_touched": last, "source_refs": refs, "broken_refs": broken}


def build_inventory(repo_root: Path) -> dict:
    python_files: list[dict] = []
    test_files: list[dict] = []
    docs: list[dict] = []
    scripts: list[dict] = []
    for path, rel in _iter_files(repo_root):
        posix = rel.as_posix()
        top = rel.parts[0]
        if rel.suffix == ".py" and top == "plex_renamer":
            python_files.append({
                "path": posix,
                "package": ".".join(rel.parts[:-1]),
                "loc": _loc(path),
                "sha256": _sha(path),
            })
        elif rel.suffix == ".py" and top == "tests":
            test_files.append({"path": posix, "loc": _loc(path), "imports_modules": _test_imports(path)})
        elif rel.suffix in DOC_SUFFIXES and (top == "docs" or len(rel.parts) == 1):
            docs.append(_doc_record(repo_root, path, rel))
        elif top == "scripts":
            scripts.append({"path": posix})
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
