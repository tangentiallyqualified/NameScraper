"""Opt-in real-binary smoke for multi-part episode merge.

Generates a 3-part split episode with ffmpeg (2 test tones + testsrc video,
one external .srt for part 2), runs the real probe -> gate -> plan ->
mkvmerge append pipeline, and verifies the merged output's duration and
track layout. Requires ffmpeg/ffprobe and mkvmerge on this machine.

Usage: .venv\\Scripts\\python.exe scripts\\merge_parts_smoke.py
Exit 0 = all checks passed; 2 = required binaries missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plex_renamer._job_execution_remux import execute_remux_op
from plex_renamer._mkv_probe import clear_probe_cache, probe_file
from plex_renamer.engine._merge_gate import check_append_compatibility
from plex_renamer.engine._mux_planner import MuxPlan, SubtitleMergeDecision
from plex_renamer.engine.models import RenameResult
from plex_renamer.job_store import RenameOp


def _need(binary: str) -> str | None:
    found = shutil.which(binary)
    if found is None and binary == "mkvmerge":
        default = Path(r"C:\Program Files\MKVToolNix\mkvmerge.exe")
        return str(default) if default.is_file() else None
    return found


def _gen_part(ffmpeg: str, out: Path, seconds: int, tone: int) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone}:duration={seconds}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-ac",
            "2",
            str(out),
        ],
        check=True,
        timeout=180,
        capture_output=True,
    )


def main() -> int:
    ffmpeg, mkvmerge = _need("ffmpeg"), _need("mkvmerge")
    if not ffmpeg or not mkvmerge:
        print(f"missing binaries: ffmpeg={ffmpeg} mkvmerge={mkvmerge}")
        return 2

    root = Path(tempfile.mkdtemp(prefix="merge_smoke_"))
    src = root / "in"
    src.mkdir()
    durations = [4, 3, 2]
    for index, seconds in enumerate(durations, start=1):
        _gen_part(ffmpeg, src / f"Show S01E05 ({index}).mkv", seconds, 300 + 100 * index)
    (src / "Show S01E05 (2).eng.srt").write_text(
        "1\n00:00:00,500 --> 00:00:01,500\npart two line\n", encoding="utf-8"
    )

    clear_probe_cache()
    parts = [src / f"Show S01E05 ({i}).mkv" for i in (1, 2, 3)]
    probes = [probe_file(Path(mkvmerge), p) for p in parts]
    reason = check_append_compatibility(probes)
    assert reason is None, f"gate unexpectedly failed: {reason}"

    offset_ms = probes[0].duration_ms
    plan = MuxPlan(
        output_name="Show - S01E05.mkv",
        append_sources=["Show S01E05 (2).mkv", "Show S01E05 (3).mkv"],
        subtitle_merges=[
            SubtitleMergeDecision(
                source_relative="Show S01E05 (2).eng.srt",
                action="merge",
                language="eng",
                set_default=False,
                sync_offset_ms=offset_ms,
            )
        ],
        mkvmerge_path=mkvmerge,
    )
    op = RenameOp(
        original_relative="Show S01E05 (1).mkv",
        new_name="Show - S01E05.mkv",
        target_dir_relative="Show/Season 01",
        status="OK",
        season=1,
        episodes=[5],
        mux=plan.to_dict(),
    )
    result = RenameResult()
    out_root = root / "out"
    ok = execute_remux_op(op, source_root=src, output_root=out_root, result=result)
    assert ok, result.errors
    final = out_root / "Show/Season 01/Show - S01E05.mkv"
    assert final.exists()

    clear_probe_cache()
    merged = probe_file(Path(mkvmerge), final)
    expected_ms = sum(d * 1000 for d in durations)
    assert abs(merged.duration_ms - expected_ms) < 1500, (
        f"duration {merged.duration_ms} != ~{expected_ms}"
    )
    assert len(merged.video_tracks) == 1 and len(merged.audio_tracks) == 1
    assert len(merged.subtitle_tracks) == 1  # merged external srt
    print(f"OK: merged {len(parts)} parts -> {final} ({merged.duration_ms} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
