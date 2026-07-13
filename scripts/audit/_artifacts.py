"""Shared read/write of .audit/*.json stage artifacts and git helpers."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR_NAME = ".audit"

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
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": current_commit(repo_root),
    }
    path = audit_dir(repo_root) / f"{name}.json"
    path.write_text(json.dumps(stamped, indent=1, sort_keys=True), encoding="utf-8")
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
    out = _git(repo_root, "diff", "--name-only", f"{old_commit}..HEAD", "--", *pathspecs)
    if out is None:
        return None
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def working_tree_files(repo_root: Path, *pathspecs: str) -> list[str] | None:
    """Relevant staged, unstaged, and untracked files, normalized repo-relative."""
    files: set[str] = set()
    commands = (
        ("diff", "--name-only", "--", *pathspecs),
        ("diff", "--cached", "--name-only", "--", *pathspecs),
        ("ls-files", "--others", "--exclude-standard", "--", *pathspecs),
    )
    for args in commands:
        out = _git(repo_root, *args)
        if out is None:
            return None
        files.update(
            line.strip().replace("\\", "/")
            for line in out.splitlines()
            if line.strip()
        )
    return sorted(files)
