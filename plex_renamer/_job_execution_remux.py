"""mkvmerge execution for REMUX job ops (spec §7).

Write to a temp name → atomic os.replace on success → No Fear deletions
only after the final file exists.  Progress percents are parsed from
mkvmerge stdout ("Progress: NN%", tolerant of \r-separated updates).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

from ._mkv_command import build_mkvmerge_args
from ._mkv_locate import find_mkvmerge
from .engine._mux_planner import MuxPlan
from .engine.models import RenameResult

_log = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(r"[Pp]rogress:?\s*#?\s*(\d{1,3})\s*%")
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run_mkvmerge(
    args: list[str],
    on_percent: Callable[[int], None] | None = None,
) -> tuple[int, str]:
    """Run mkvmerge, streaming progress.  Returns (returncode, output tail)."""
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=0,
        creationflags=_CREATION_FLAGS,
    )
    tail: list[str] = []
    buffer = ""
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        buffer += chunk
        # mkvmerge separates progress updates with \r, other output with \n.
        *lines, buffer = re.split(r"[\r\n]", buffer)
        for line in lines:
            if not line.strip():
                continue
            match = _PROGRESS_RE.search(line)
            if match and on_percent is not None:
                on_percent(min(100, int(match.group(1))))
            else:
                tail.append(line.strip())
                del tail[:-20]
    proc.wait()
    if buffer.strip():
        tail.append(buffer.strip())
    return proc.returncode, "\n".join(tail[-20:])


def execute_remux_op(
    op,
    *,
    source_root: Path,
    output_root: Path,
    result: RenameResult,
    on_percent: Callable[[int], None] | None = None,
    set_active_temp: Callable[[str | None], None] | None = None,
    runner: Callable | None = None,
    title: str | None = None,
) -> bool:
    """Execute one mux op.  Returns True on success; errors go to *result*."""
    # Late-bound default so tests can monkeypatch run_mkvmerge at module level.
    runner = runner or run_mkvmerge
    plan = MuxPlan.from_dict(op.mux)
    src = source_root / op.original_relative
    target_dir = output_root / op.target_dir_relative
    final = target_dir / op.new_name

    source_boundary = source_root.resolve(strict=False)
    output_boundary = output_root.resolve(strict=False)
    try:
        src.resolve().relative_to(source_boundary)
        final.resolve(strict=False).relative_to(output_boundary)
    except (OSError, ValueError):
        result.errors.append(
            f"Remux paths escape their roots: {op.original_relative}")
        return False

    if not src.exists():
        result.errors.append(f"Source not found: {src.name}")
        return False
    if final.exists():
        result.errors.append(f"Target already exists, skipped: {final.name}")
        return False

    mkvmerge = plan.mkvmerge_path
    if not mkvmerge or not Path(mkvmerge).is_file():
        located = find_mkvmerge("")
        if located is None:
            result.errors.append("mkvmerge is not available")
            return False
        mkvmerge = str(located)

    merged_sources = [
        source_root / rel for rel in plan.merged_sub_paths
    ]
    for sub in merged_sources:
        if not sub.exists():
            result.errors.append(f"Subtitle source not found: {sub.name}")
            return False

    temp = target_dir / f"{op.new_name}.tmp-{uuid.uuid4().hex[:8]}.mkv"
    args = build_mkvmerge_args(
        mkvmerge_path=mkvmerge, source=src, output=temp, plan=plan,
        resolve_sub=lambda rel: source_root / rel,
        title=title,
    )

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if set_active_temp is not None:
            set_active_temp(str(temp))
        returncode, output_tail = runner(args, on_percent=on_percent)
    except OSError as e:
        temp.unlink(missing_ok=True)
        result.errors.append(f"mkvmerge failed for {src.name}: {e}")
        return False
    finally:
        if set_active_temp is not None:
            set_active_temp(None)

    if returncode not in (0, 1):      # 1 = completed with warnings
        temp.unlink(missing_ok=True)
        result.errors.append(
            f"mkvmerge exited {returncode} for {src.name}: {output_tail}")
        return False

    os.replace(temp, final)
    result.log_entry.setdefault("remux_outputs", []).append(str(final))
    result.renamed_count += 1

    if plan.no_fear:
        # Source deletion only after the final output exists (spec §7.1).
        for path in [src, *merged_sources]:
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                result.errors.append(f"Could not remove source {path.name}: {e}")
        result.log_entry["irreversible"] = True
    return True
