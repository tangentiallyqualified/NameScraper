"""Manual evidence tool: what do mkvmerge -J and ffprobe report per container?

Usage: .venv\\Scripts\\python.exe scripts\\probe_audio_fields.py <video-file> [...]
Run against one MKV (statistics tags), one MKV without stats tags, one MP4.
Not part of the test suite; requires local binaries.

=== Observed Fields (2026-07-20, corrected 2026-07-20) ===

Tested against:
  - Solo Leveling S01E01 (MKV with statistics tags, AAC 2ch + FLAC 2ch tracks)
  - Solo Leveling S01E02 (MKV, Opus codec, 2ch + 6ch tracks)
  - The Simpsons S03E01 (MP4, AAC codec, multiple 2ch tracks)

mkvmerge -J audio track properties observed (non-stats-tagged MKVs):
  - audio_channels
  - audio_sampling_frequency
  - codec_delay
  - codec_id
  - codec_private_data
  - codec_private_length
  - default_track
  - enabled_track
  - forced_track
  - language
  - language_ietf
  - minimum_timestamp
  - num_index_entries
  - number
  - track_name
  - uid

mkvmerge -J statistics tags observed (stats-tagged MKVs):
  - tag__statistics_tags
  - tag__statistics_writing_app
  - tag__statistics_writing_date_utc
  - tag_bps (e.g., 128000 for AAC, 1406546 for FLAC)
  - tag_duration
  - tag_number_of_bytes
  - tag_number_of_frames

DECISION GATE FINDINGS:
  - tag_bps field IS PRESENT in mkvmerge -J output for MKVs with statistics tags
  - ffprobe NOT AVAILABLE on system (no bitrate data from ffprobe for MP4)
  - mkvmerge exposes bitrate information via tag_bps for statistics-tagged files
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plex_renamer._mkv_locate import find_mkvmerge


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: probe_audio_fields.py <video-file> [...]")
        return 2
    mkvmerge = find_mkvmerge("")
    ffprobe = shutil.which("ffprobe")
    if mkvmerge is None:
        print("mkvmerge not found")
        return 2
    for arg in argv:
        path = Path(arg)
        if not path.is_file():
            print(f"missing: {path}")
            return 2
        print(f"=== {path.name} ===")
        raw = subprocess.run(
            [str(mkvmerge), "-J", str(path)], capture_output=True, text=True, check=False
        )
        doc = json.loads(raw.stdout or "{}")
        for track in doc.get("tracks", []):
            if track.get("type") != "audio":
                continue
            props = track.get("properties", {})
            print(f"  mkvmerge track {track.get('id')}: codec={track.get('codec')}")
            for key in sorted(props):
                if "bps" in key.lower() or "channel" in key.lower() or "tag" in key.lower():
                    print(f"    {key} = {props[key]}")
        if ffprobe is None:
            print("  ffprobe not found — skipping")
            continue
        raw = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "a",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        doc = json.loads(raw.stdout or "{}")
        for stream in doc.get("streams", []):
            tags = stream.get("tags", {})
            print(
                f"  ffprobe a-stream {stream.get('index')}: codec={stream.get('codec_name')} "
                f"channels={stream.get('channels')} bit_rate={stream.get('bit_rate')} "
                f"BPS={tags.get('BPS') or tags.get('BPS-eng')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
