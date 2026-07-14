"""Shared read/write of .audit/*.json stage artifacts and git helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

AUDIT_DIR_NAME = ".audit"
AUDIT_INPUT_PATTERNS: tuple[str, ...] = (
    "plex_renamer/**/*.py",
    "scripts/audit/**/*",
    "scripts/audit.cmd",
    "scripts/audit.ps1",
    "scripts/test_fast_runner.py",
    "scripts/test-fast.cmd",
    "scripts/test-fast.ps1",
    "tests/**/*.py",
    "docs/**/*.md",
    "docs/**/*.rst",
    "docs/**/*.txt",
    "pyproject.toml",
    "pyrightconfig.json",
    "docs/audit/doc-ledger.toml",
)

_EXCLUDED_INPUT_PARTS = {
    ".git",
    ".venv",
    ".worktrees",
    AUDIT_DIR_NAME,
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".agents",
    ".codex",
    ".claude",
    ".vscode",
    ".scan-dumps",
    ".github",
    "plex_renamer.egg-info",
}
_ROOT_DOC_SUFFIXES = {".md", ".rst", ".txt"}
_DOC_LEDGER = "docs/audit/doc-ledger.toml"
_GENERATED_AUDIT_FILES = {
    "docs/audit/CHANGES.md",
    "docs/audit/doc-status.md",
}
_GENERATED_AUDIT_PREFIXES = (
    "docs/audit/code-index/",
    "docs/audit/llm/",
    "docs/audit/maps/",
)

# artifact name -> CLI stage that produces it
PRODUCERS = {
    "inventory": "inventory",
    "graph": "graph",
    "analysis": "analyze",
    "coverage": "coverage",
    "metrics": "metrics",
}


class MissingArtifactError(RuntimeError):
    def __init__(self, name: str) -> None:
        stage = PRODUCERS.get(name, name)
        super().__init__(
            f"Missing artifact '{name}.json'. Produce it first with: scripts\\audit.cmd {stage}"
        )


def input_files(repo_root: Path) -> list[Path]:
    """Return enrolled audit inputs in stable repository-relative order."""
    files: dict[str, Path] = {}
    candidates = [
        path
        for path in repo_root.iterdir()
        if path.is_file() and path.suffix.lower() in _ROOT_DOC_SUFFIXES
    ]
    for pattern in AUDIT_INPUT_PATTERNS:
        candidates.extend(repo_root.rglob(pattern))
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root)
        if any(part in _EXCLUDED_INPUT_PARTS for part in relative.parts):
            continue
        relative_posix = relative.as_posix()
        if relative_posix in _GENERATED_AUDIT_FILES or relative_posix.startswith(
            _GENERATED_AUDIT_PREFIXES
        ):
            continue
        files[relative_posix] = path
    return [files[relative] for relative in sorted(files)]


def input_digest(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in input_files(repo_root):
        rel = path.relative_to(repo_root).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def write_text_lf(path: Path, content: str) -> int:
    """Write generated text as UTF-8 with platform-independent LF endings."""
    return path.write_text(content, encoding="utf-8", newline="\n")


def audit_dir(repo_root: Path) -> Path:
    d = repo_root / AUDIT_DIR_NAME
    d.mkdir(exist_ok=True)
    return d


def ascii_safe(text: str) -> str:
    """Console-safe text for CLI prints (cp1252 consoles); generated files stay UTF-8."""
    return text.encode("ascii", "replace").decode("ascii")


def package_of(path: str) -> str:
    """Top-level package segment of a repo-relative module path ('root' for top-level files)."""
    parts = Path(path).parts
    return parts[1] if len(parts) > 2 else "root"


def write_artifact(repo_root: Path, name: str, payload: dict) -> Path:
    stamped = {
        **payload,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": current_commit(repo_root),
    }
    path = audit_dir(repo_root) / f"{name}.json"
    write_text_lf(path, json.dumps(stamped, indent=1, sort_keys=True))
    return path


def read_artifact(repo_root: Path, name: str) -> dict:
    path = repo_root / AUDIT_DIR_NAME / f"{name}.json"
    if not path.exists():
        raise MissingArtifactError(name)
    return json.loads(path.read_text(encoding="utf-8"))


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def current_commit(repo_root: Path) -> str | None:
    return _git(repo_root, "rev-parse", "--short", "HEAD")


def commits_between(repo_root: Path, old_commit: str) -> int | None:
    out = _git(repo_root, "rev-list", "--count", f"{old_commit}..HEAD")
    return int(out) if out is not None and out.isdigit() else None


def changed_files_since(repo_root: Path, old_commit: str, *pathspecs: str) -> list[str] | None:
    out = _git(
        repo_root,
        "diff",
        "--no-renames",
        "--name-only",
        f"{old_commit}..HEAD",
        "--",
        *pathspecs,
    )
    if out is None:
        return None
    committed = {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}
    working = working_tree_files(repo_root, *pathspecs)
    if working is None:
        return None
    return sorted(committed | set(working))


def working_tree_files(repo_root: Path, *pathspecs: str) -> list[str] | None:
    """Relevant staged, unstaged, and untracked files, normalized repo-relative."""
    files: set[str] = set()
    commands = (
        ("diff", "--no-renames", "--name-only", "--", *pathspecs),
        ("diff", "--cached", "--no-renames", "--name-only", "--", *pathspecs),
        ("ls-files", "--others", "--exclude-standard", "--", *pathspecs),
    )
    for args in commands:
        out = _git(repo_root, *args)
        if out is None:
            return None
        files.update(line.strip().replace("\\", "/") for line in out.splitlines() if line.strip())
    return sorted(files)
