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
import tempfile
import uuid
from collections.abc import Callable
from contextlib import contextmanager
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


def _write_temp(data: bytes, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix="plexrn-embed-", suffix=suffix)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return Path(name)


@contextmanager
def materialized_extras(entry, fetch_image_bytes, result, display_name):
    """Yield (tags_path, cover_path) temp files for one embed_extras
    entry; both may be None. Files are always deleted on exit. Problems
    are warnings on *result*, never exceptions (metadata never fails a
    job)."""
    tags_path: Path | None = None
    cover_path: Path | None = None
    try:
        xml = (entry or {}).get("tags_xml")
        if xml:
            try:
                tags_path = _write_temp(str(xml).encode("utf-8"), ".xml")
            except OSError as e:
                result.errors.append(
                    f"Could not stage tags for {display_name}: {e}")
        tmdb_path = (entry or {}).get("cover_tmdb_path")
        if tmdb_path:
            data = None
            fetch_failed = False
            if fetch_image_bytes is not None:
                try:
                    data = fetch_image_bytes(tmdb_path)
                except Exception as e:
                    fetch_failed = True
                    result.errors.append(
                        f"Cover fetch failed for {display_name}: {e}")
            if data:
                try:
                    cover_path = _write_temp(data, ".jpg")
                except OSError as e:
                    result.errors.append(
                        f"Could not stage cover for {display_name}: {e}")
            elif not fetch_failed:
                # Only one warning per cover — the except above already
                # recorded the failure when the fetch itself blew up.
                result.errors.append(
                    "Cover art unavailable (offline or uncached): "
                    f"{display_name}")
        yield tags_path, cover_path
    finally:
        for path in (tags_path, cover_path):
            if path is not None:
                path.unlink(missing_ok=True)


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

    if plan.get("embed_title") or plan.get("embed_extras"):
        _embed_metadata(
            job, plan, result, output_root, output_boundary, top_dir_remap,
            propedit_runner or run_mkvpropedit, fetch_image_bytes)


def _embed_metadata(
    job,
    plan: dict,
    result: RenameResult,
    output_root: Path,
    output_boundary: Path,
    top_dir_remap: dict[Path, Path],
    runner: Callable[[list[str]], tuple[int, str]],
    fetch_image_bytes: Callable[[str], bytes | None] | None,
) -> None:
    """mkvpropedit pass (title/tags/cover) for plainly-renamed MKVs.

    Mux ops are excluded — REMUX outputs get their embeds via mkvmerge
    flags during the mux. Non-MKV files are skipped (mkvpropedit is
    MKV-only).
    """
    embed_title = bool(plan.get("embed_title"))
    extras_by_op = {
        e.get("op"): e for e in plan.get("embed_extras") or []
    }
    ops = [
        op for op in job.rename_ops
        if op.selected and op.file_type == "video" and op.new_name
        and op.new_name.lower().endswith(".mkv") and not op.mux
        and (op.status == "OK" or op.status.startswith("REVIEW"))
        and (embed_title or op.original_relative in extras_by_op)
    ]
    if not ops:
        return

    propedit = plan.get("mkvpropedit_path") or ""
    if not propedit or not Path(propedit).is_file():
        located = find_mkvpropedit("")
        if located is None:
            result.errors.append(
                "mkvpropedit is not available — embedded metadata skipped")
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

        title = PurePath(op.new_name).stem if embed_title else None
        entry = extras_by_op.get(op.original_relative)
        with materialized_extras(
                entry, fetch_image_bytes, result, op.new_name) as (
                tags_path, cover_path):
            if title is None and tags_path is None and cover_path is None:
                continue
            args = build_mkvpropedit_args(
                propedit, target,
                title=title, tags_path=tags_path, cover_path=cover_path)
            try:
                returncode, tail = runner(args)
            except (OSError, subprocess.SubprocessError) as e:
                result.errors.append(
                    f"mkvpropedit failed for {target.name}: {e}")
                continue
            if returncode not in (0, 1):    # 1 = completed with warnings
                result.errors.append(
                    f"mkvpropedit exited {returncode} for {target.name}: "
                    f"{tail}")
