"""Run the full audit pipeline without leaving generated-output changes behind."""
from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath


GENERATED_ROOT = Path("docs") / "audit"
POLICY_INPUTS = {GENERATED_ROOT / "doc-ledger.toml"}


def _path_kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def _tree_entries(repo_root: Path) -> tuple[list[tuple[Path, str]], list[Path]]:
    """Return descendants without following symlinks or policy-input paths."""
    generated_root = repo_root / GENERATED_ROOT
    if _path_kind(generated_root) != "directory":
        return [], []

    objects: list[tuple[Path, str]] = []
    directories: list[Path] = []
    pending = [generated_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(repo_root)
                if relative in POLICY_INPUTS:
                    continue
                if entry.is_symlink():
                    objects.append((path, "symlink"))
                elif entry.is_dir(follow_symlinks=False):
                    directories.append(path)
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    objects.append((path, "file"))
                else:
                    objects.append((path, "other"))
    return objects, directories


def snapshot_generated(repo_root: Path) -> dict[str, bytes]:
    """Capture generated-root files, excluding policy inputs."""
    objects, _directories = _tree_entries(repo_root)
    return {
        path.relative_to(repo_root).as_posix(): path.read_bytes()
        for path, kind in sorted(objects, key=lambda item: item[0].as_posix())
        if kind == "file"
    }


def _validated_snapshot(
    repo_root: Path, snapshot: dict[str, bytes]
) -> dict[str, tuple[Path, bytes]]:
    validated: dict[str, tuple[Path, bytes]] = {}
    pure_paths: set[PurePosixPath] = set()
    generated_parts = tuple(GENERATED_ROOT.parts)
    policy_parts = {tuple(path.parts) for path in POLICY_INPUTS}
    native_generated_root = Path(os.path.abspath(repo_root / GENERATED_ROOT))

    for relative, content in snapshot.items():
        if (
            not isinstance(relative, str)
            or "\x00" in relative
            or "\\" in relative
        ):
            raise ValueError(f"invalid snapshot path: {relative!r}")
        pure = PurePosixPath(relative)
        parts = pure.parts
        if (
            pure.as_posix() != relative
            or len(parts) <= len(generated_parts)
            or parts[:len(generated_parts)] != generated_parts
            or any(part in {".", ".."} for part in parts)
            or any(":" in part for part in parts)
            or any(parts[:len(policy)] == policy for policy in policy_parts)
        ):
            raise ValueError(f"invalid snapshot path: {relative!r}")
        if not isinstance(content, bytes):
            raise ValueError(f"invalid snapshot content for path: {relative!r}")
        native_target = Path(os.path.abspath(repo_root.joinpath(*parts)))
        try:
            native_target.relative_to(native_generated_root)
        except ValueError as exc:
            raise ValueError(f"invalid snapshot path: {relative!r}") from exc
        pure_paths.add(pure)
        validated[relative] = (native_target, content)

    for pure in pure_paths:
        for length in range(len(generated_parts) + 1, len(pure.parts)):
            if PurePosixPath(*pure.parts[:length]) in pure_paths:
                raise ValueError(f"invalid snapshot path hierarchy: {pure.as_posix()!r}")
    return validated


def restore_generated(repo_root: Path, snapshot: dict[str, bytes]) -> None:
    """Restore generated files to a prior byte-for-byte snapshot."""
    validated = _validated_snapshot(repo_root, snapshot)
    generated_root = repo_root / GENERATED_ROOT
    root_kind = _path_kind(generated_root)
    if root_kind in {"file", "symlink", "other"}:
        generated_root.unlink()

    objects, directories = _tree_entries(repo_root)
    for path, kind in objects:
        relative = path.relative_to(repo_root).as_posix()
        if kind != "file" or relative not in validated:
            path.unlink()

    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    for path, content in validated.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def verify(repo_root: Path, run_pipeline: Callable[[], int]) -> tuple[int, list[str]]:
    """Run a pipeline, report generated drift, and always restore original files."""
    generated_root = repo_root / GENERATED_ROOT
    root_was_directory = _path_kind(generated_root) == "directory"
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
        if root_was_directory:
            generated_root.mkdir(parents=True, exist_ok=True)
        elif _path_kind(generated_root) == "directory":
            generated_root.rmdir()
