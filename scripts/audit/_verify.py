"""Run the full audit pipeline without leaving generated-output changes behind."""
from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath


GENERATED_ROOT = Path("docs") / "audit"
POLICY_INPUTS = {GENERATED_ROOT / "doc-ledger.toml"}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafeGeneratedTreeError(RuntimeError):
    def __init__(self, paths: list[str]) -> None:
        self.paths = sorted(paths)
        super().__init__(
            "unsafe generated output tree contains link-like objects: "
            + ", ".join(self.paths)
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
    return {
        path.relative_to(repo_root).as_posix(): path.read_bytes()
        for path, kind in sorted(objects, key=lambda item: item[0].as_posix())
        if kind == "file"
    }


def _unsafe_preexisting_links(repo_root: Path) -> list[str]:
    generated_root = repo_root / GENERATED_ROOT
    root_kind = _path_kind(generated_root)
    if root_kind in {"symlink", "reparse"}:
        return [GENERATED_ROOT.as_posix()]
    if root_kind != "directory":
        return []
    objects, _directories = _tree_entries(repo_root)
    return sorted(
        path.relative_to(repo_root).as_posix()
        for path, kind in objects
        if kind in {"symlink", "reparse"}
    )


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
