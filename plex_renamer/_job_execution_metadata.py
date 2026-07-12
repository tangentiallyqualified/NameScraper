"""Decorate phase: write metadata sidecars and embed titles after a
successful rename/remux (spec: local-metadata-artwork).

Never fails the job — every problem is appended to result.errors on a
job that still completes. Files are written temp-name-then-os.replace so
a crash never leaves a half-written sidecar.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path, PurePath

from ._job_execution_filesystem import apply_top_dir_remap
from ._mkv_command import build_mkvpropedit_args
from ._mkv_locate import find_mkvpropedit
from .engine.models import RenameResult

_log = logging.getLogger(__name__)
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_PROPEDIT_TIMEOUT_SECONDS = 120


def run_mkvpropedit(args: list[str]) -> tuple[int, str]:
    """Run mkvpropedit. Returns (returncode, output tail)."""
    proc = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=_CREATION_FLAGS, timeout=_PROPEDIT_TIMEOUT_SECONDS,
    )
    return proc.returncode, (proc.stdout or "")[-2000:]


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        temp.write_bytes(data)
        os.replace(temp, target)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _resolve_target(
    output_root: Path,
    output_boundary: Path,
    relative: str,
    top_dir_remap: dict[Path, Path],
    result: RenameResult,
) -> Path | None:
    # The rename phase may have remapped a colliding top-level output dir
    # (e.g. "Show (2019)" -> "Show (2019) (2)"); the plan's target paths
    # are static and pre-date that remap, so route through it here too —
    # otherwise sidecars land in the wrong (pre-existing) folder.
    target = apply_top_dir_remap(output_root / relative, top_dir_remap)
    try:
        target.resolve(strict=False).relative_to(output_boundary)
    except (OSError, ValueError):
        result.errors.append(
            f"Metadata target escapes the output root: {relative}")
        return None
    return target


def _load_top_dir_remap(result: RenameResult) -> dict[Path, Path]:
    raw = result.log_entry.get("top_dir_remap") or {}
    return {Path(old): Path(new) for old, new in raw.items()}


def execute_metadata_plan(
    job,
    *,
    result: RenameResult,
    fetch_image_bytes: Callable[[str], bytes | None] | None = None,
    propedit_runner: Callable[[list[str]], tuple[int, str]] | None = None,
) -> None:
    """Apply job.metadata_plan to the output folder."""
    plan = job.metadata_plan
    if not plan or not job.output_root:
        return

    output_root = Path(job.output_root)
    output_boundary = output_root.resolve(strict=False)
    prefer_local = bool(plan.get("prefer_local"))
    created = result.log_entry.setdefault("created_files", [])
    top_dir_remap = _load_top_dir_remap(result)

    for nfo in plan.get("nfo_files", []):
        target_relative = nfo.get("target_relative")
        content = nfo.get("content")
        if target_relative is None or content is None:
            result.errors.append(
                "Metadata plan entry missing target_relative/content "
                "— nfo skipped")
            continue
        target = _resolve_target(
            output_root, output_boundary, target_relative, top_dir_remap,
            result)
        if target is None:
            continue
        if prefer_local and target.exists():
            continue
        try:
            _write_atomic(target, str(content).encode("utf-8"))
            created.append(str(target))
        except OSError as e:
            result.errors.append(f"Could not write {target.name}: {e}")

    for art in plan.get("artwork", []):
        target_relative = art.get("target_relative")
        tmdb_path = art.get("tmdb_path")
        if target_relative is None or tmdb_path is None:
            result.errors.append(
                "Metadata plan entry missing target_relative/tmdb_path "
                "— artwork skipped")
            continue
        target = _resolve_target(
            output_root, output_boundary, target_relative, top_dir_remap,
            result)
        if target is None:
            continue
        if prefer_local and target.exists():
            continue
        data = fetch_image_bytes(tmdb_path) if fetch_image_bytes else None
        if not data:
            result.errors.append(
                f"Artwork unavailable (offline or uncached): {target.name}")
            continue
        try:
            _write_atomic(target, data)
            created.append(str(target))
        except OSError as e:
            result.errors.append(f"Could not write {target.name}: {e}")

    if plan.get("embed_title"):
        _embed_titles(
            job, plan, result, output_root, output_boundary, top_dir_remap,
            propedit_runner or run_mkvpropedit)


def _embed_titles(
    job,
    plan: dict,
    result: RenameResult,
    output_root: Path,
    output_boundary: Path,
    top_dir_remap: dict[Path, Path],
    runner: Callable[[list[str]], tuple[int, str]],
) -> None:
    """mkvpropedit title pass for plainly-renamed MKVs.

    Mux ops are excluded — REMUX outputs get their title via mkvmerge
    --title during the mux. Non-MKV files are skipped (mkvpropedit is
    MKV-only).
    """
    ops = [
        op for op in job.rename_ops
        if op.selected and op.file_type == "video" and op.new_name
        and op.new_name.lower().endswith(".mkv") and not op.mux
        and (op.status == "OK" or op.status.startswith("REVIEW"))
    ]
    if not ops:
        return

    propedit = plan.get("mkvpropedit_path") or ""
    if not propedit or not Path(propedit).is_file():
        located = find_mkvpropedit("")
        if located is None:
            result.errors.append(
                "mkvpropedit is not available — embedded titles skipped")
            return
        propedit = str(located)

    for op in ops:
        target_dir = apply_top_dir_remap(
            output_root / op.target_dir_relative, top_dir_remap)
        target = target_dir / op.new_name
        try:
            target.resolve(strict=False).relative_to(output_boundary)
        except (OSError, ValueError):
            result.errors.append(
                f"Metadata target escapes the output root: {op.new_name}")
            continue
        if not target.exists():
            continue    # this op's rename failed/was skipped upstream
        title = PurePath(op.new_name).stem
        args = build_mkvpropedit_args(propedit, target, title=title)
        try:
            returncode, tail = runner(args)
        except (OSError, subprocess.SubprocessError) as e:
            result.errors.append(f"mkvpropedit failed for {target.name}: {e}")
            continue
        if returncode not in (0, 1):    # 1 = completed with warnings
            result.errors.append(
                f"mkvpropedit exited {returncode} for {target.name}: {tail}")
