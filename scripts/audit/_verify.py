"""Run the full audit pipeline without leaving generated-output changes behind."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


GENERATED_ROOT = Path("docs") / "audit"
POLICY_INPUTS = {GENERATED_ROOT / "doc-ledger.toml"}


def snapshot_generated(repo_root: Path) -> dict[str, bytes]:
    """Capture generated-root files, excluding policy inputs."""
    generated_root = repo_root / GENERATED_ROOT
    if not generated_root.exists():
        return {}
    files = (
        path
        for path in generated_root.rglob("*")
        if path.is_file() and path.relative_to(repo_root) not in POLICY_INPUTS
    )
    return {
        path.relative_to(repo_root).as_posix(): path.read_bytes()
        for path in sorted(files, key=lambda item: item.as_posix())
    }


def restore_generated(repo_root: Path, snapshot: dict[str, bytes]) -> None:
    """Restore generated files to a prior byte-for-byte snapshot."""
    current = snapshot_generated(repo_root)
    for relative in current.keys() - snapshot.keys():
        (repo_root / relative).unlink()

    for relative, content in snapshot.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    generated_root = repo_root / GENERATED_ROOT
    if generated_root.exists():
        directories = (path for path in generated_root.rglob("*") if path.is_dir())
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass


def verify(repo_root: Path, run_pipeline: Callable[[], int]) -> tuple[int, list[str]]:
    """Run a pipeline, report generated drift, and always restore original files."""
    before = snapshot_generated(repo_root)
    try:
        pipeline_rc = run_pipeline()
        after = snapshot_generated(repo_root)
        drift = sorted(
            relative
            for relative in before.keys() | after.keys()
            if before.get(relative) != after.get(relative)
        )
        return pipeline_rc, drift
    finally:
        restore_generated(repo_root, before)
