"""Run the full audit pipeline without leaving generated-output changes behind."""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath

GENERATED_ROOT = Path("docs") / "audit"
GENERATED_FILES = {Path("audit.sarif")}
POLICY_INPUTS = {
    GENERATED_ROOT / "doc-ledger.toml",
    GENERATED_ROOT / "engine-cycle-edges.toml",
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafeGeneratedTreeError(RuntimeError):
    def __init__(self, paths: list[str]) -> None:
        self.paths = sorted(paths)
        super().__init__(
            "unsafe generated output tree contains link-like objects: " + ", ".join(self.paths)
        )


def _path_is_reparse(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & _REPARSE_POINT)


def _entry_is_reparse(entry: os.DirEntry) -> bool:
    is_junction = getattr(entry, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & _REPARSE_POINT)


def _remove_link_like(path: Path) -> None:
    try:
        path.unlink()
    except (IsADirectoryError, PermissionError):
        path.rmdir()


def _path_kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if _path_is_reparse(path):
        return "reparse"
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
                if entry.is_symlink():
                    objects.append((path, "symlink"))
                elif _entry_is_reparse(entry):
                    objects.append((path, "reparse"))
                elif relative in POLICY_INPUTS:
                    continue
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
    snapshot = {
        path.relative_to(repo_root).as_posix(): path.read_bytes()
        for path, kind in sorted(objects, key=lambda item: item[0].as_posix())
        if kind == "file"
    }
    for relative in GENERATED_FILES:
        path = repo_root / relative
        if _path_kind(path) == "file":
            snapshot[relative.as_posix()] = path.read_bytes()
    return snapshot


def _unsafe_preexisting_links(repo_root: Path) -> list[str]:
    unsafe_files = [
        relative.as_posix()
        for relative in GENERATED_FILES
        if _path_kind(repo_root / relative) in {"symlink", "reparse"}
    ]
    generated_root = repo_root / GENERATED_ROOT
    root_kind = _path_kind(generated_root)
    if root_kind in {"symlink", "reparse"}:
        return sorted([GENERATED_ROOT.as_posix(), *unsafe_files])
    if root_kind != "directory":
        return sorted(unsafe_files)
    objects, _directories = _tree_entries(repo_root)
    return sorted(
        unsafe_files
        + [
            path.relative_to(repo_root).as_posix()
            for path, kind in objects
            if kind in {"symlink", "reparse"}
        ]
    )


def _validated_snapshot_entry(
    repo_root: Path, relative: str, content: bytes
) -> tuple[PurePosixPath, Path, bytes]:
    generated_parts = tuple(GENERATED_ROOT.parts)
    policy_parts = {tuple(path.parts) for path in POLICY_INPUTS}
    generated_files = {PurePosixPath(path.as_posix()) for path in GENERATED_FILES}
    if not isinstance(relative, str) or "\x00" in relative or "\\" in relative:
        raise ValueError(f"invalid snapshot path: {relative!r}")
    pure = PurePosixPath(relative)
    parts = pure.parts
    is_generated_file = pure in generated_files
    if not is_generated_file and (
        len(parts) <= len(generated_parts) or parts[: len(generated_parts)] != generated_parts
    ):
        raise ValueError(f"invalid snapshot path: {relative!r}")
    if (
        pure.as_posix() != relative
        or any(part in {".", ".."} for part in parts)
        or any(":" in part for part in parts)
        or any(parts[: len(policy)] == policy for policy in policy_parts)
    ):
        raise ValueError(f"invalid snapshot path: {relative!r}")
    if not isinstance(content, bytes):
        raise ValueError(f"invalid snapshot content for path: {relative!r}")
    native_target = Path(os.path.abspath(repo_root.joinpath(*parts)))
    native_root = repo_root if is_generated_file else repo_root / GENERATED_ROOT
    try:
        native_target.relative_to(Path(os.path.abspath(native_root)))
    except ValueError as exc:
        raise ValueError(f"invalid snapshot path: {relative!r}") from exc
    return pure, native_target, content


def _validated_snapshot(
    repo_root: Path, snapshot: dict[str, bytes]
) -> dict[str, tuple[Path, bytes]]:
    validated: dict[str, tuple[Path, bytes]] = {}
    pure_paths: set[PurePosixPath] = set()
    generated_parts = tuple(GENERATED_ROOT.parts)
    generated_files = {PurePosixPath(path.as_posix()) for path in GENERATED_FILES}
    for relative, content in snapshot.items():
        pure, native_target, validated_content = _validated_snapshot_entry(
            repo_root, relative, content
        )
        pure_paths.add(pure)
        validated[relative] = (native_target, validated_content)

    for pure in pure_paths:
        if pure in generated_files:
            continue
        for length in range(len(generated_parts) + 1, len(pure.parts)):
            if PurePosixPath(*pure.parts[:length]) in pure_paths:
                raise ValueError(f"invalid snapshot path hierarchy: {pure.as_posix()!r}")
    return validated


def restore_generated(repo_root: Path, snapshot: dict[str, bytes]) -> None:
    """Restore generated files to a prior byte-for-byte snapshot."""
    validated = _validated_snapshot(repo_root, snapshot)
    generated_root = repo_root / GENERATED_ROOT
    root_kind = _path_kind(generated_root)
    if root_kind in {"file", "symlink", "reparse", "other"}:
        _remove_link_like(generated_root)

    objects, directories = _tree_entries(repo_root)
    for path, kind in objects:
        relative = path.relative_to(repo_root).as_posix()
        if kind != "file" or relative not in validated:
            if kind in {"symlink", "reparse"}:
                _remove_link_like(path)
            else:
                path.unlink()

    for relative in GENERATED_FILES:
        path = repo_root / relative
        kind = _path_kind(path)
        if kind != "missing" and relative.as_posix() not in validated:
            _remove_link_like(path)

    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        with contextlib.suppress(OSError):
            directory.rmdir()

    for path, content in validated.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def verify(repo_root: Path, run_pipeline: Callable[[], int]) -> tuple[int, list[str]]:
    """Run a pipeline, report generated drift, and always restore original files."""
    unsafe = _unsafe_preexisting_links(repo_root)
    if unsafe:
        raise UnsafeGeneratedTreeError(unsafe)
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
