"""mkvmerge -J parsing and probe caching."""

import json
import threading
import time
from pathlib import Path

from plex_renamer import _mkv_probe
from plex_renamer._mkv_probe import (
    clear_probe_cache,
    parse_identify_json,
    probe_file,
)

IDENTIFY_PAYLOAD = {
    "container": {"recognized": True, "supported": True, "type": "Matroska"},
    "tracks": [
        {"id": 0, "type": "video", "codec": "HEVC", "properties": {"language": "und"}},
        {
            "id": 1,
            "type": "audio",
            "codec": "AC-3",
            "properties": {
                "language": "eng",
                "track_name": "Surround 5.1",
                "default_track": True,
                "forced_track": False,
            },
        },
        {
            "id": 2,
            "type": "audio",
            "codec": "AAC",
            "properties": {"language": "jpn", "default_track": False},
        },
        {
            "id": 3,
            "type": "subtitles",
            "codec": "SubRip/SRT",
            "properties": {"language": "deu", "track_name": "German"},
        },
        {
            "id": 4,
            "type": "subtitles",
            "codec": "HDMV PGS",
            "properties": {},
        },  # no language at all → und
    ],
    "errors": [],
    "warnings": [],
}


def test_parse_identify_json_tracks():
    result = parse_identify_json("X.mkv", IDENTIFY_PAYLOAD)
    assert result.ok
    assert result.container_type == "Matroska"
    assert [t.track_id for t in result.audio_tracks] == [1, 2]
    eng = result.audio_tracks[0]
    assert (eng.language, eng.name, eng.is_default) == ("eng", "Surround 5.1", True)
    # 639-2/T from mkvmerge normalizes to /B; missing language → "und".
    assert result.subtitle_tracks[0].language == "ger"
    assert result.subtitle_tracks[1].language == "und"
    assert result.video_tracks[0].track_type == "video"


def test_parse_unrecognized_container():
    payload = {
        "container": {"recognized": False, "supported": False},
        "tracks": [],
        "errors": ["unsupported"],
    }
    result = parse_identify_json("X.bin", payload)
    assert not result.ok
    assert result.error


def _fake_run_factory(calls, payload):
    class _Proc:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    def _fake_run(args, **kwargs):
        calls.append(args)
        return _Proc()

    return _fake_run


def test_probe_file_caches_by_stat(tmp_path, monkeypatch):
    clear_probe_cache()
    video = tmp_path / "a.mkv"
    video.write_bytes(b"0" * 64)
    calls: list = []
    monkeypatch.setattr(_mkv_probe.subprocess, "run", _fake_run_factory(calls, IDENTIFY_PAYLOAD))

    first = probe_file(Path("mkvmerge"), video)
    second = probe_file(Path("mkvmerge"), video)
    assert first.ok and second.ok
    assert len(calls) == 1  # second hit served from cache

    video.write_bytes(b"0" * 128)  # size change invalidates
    probe_file(Path("mkvmerge"), video)
    assert len(calls) == 2


def test_probe_file_missing_file(tmp_path):
    clear_probe_cache()
    result = probe_file(Path("mkvmerge"), tmp_path / "missing.mkv")
    assert not result.ok
    assert "not found" in result.error.lower()


def test_concurrent_probes_of_same_file_share_one_subprocess(tmp_path, monkeypatch):
    """Two threads probing the same file at once must spawn one mkvmerge,
    not two (observed live: the warm sweep and queue submission racing)."""
    clear_probe_cache()
    video = tmp_path / "a.mkv"
    video.write_bytes(b"0" * 64)

    start_barrier = threading.Barrier(3)
    release = threading.Event()
    calls: list = []

    class _Proc:
        returncode = 0
        stdout = json.dumps(IDENTIFY_PAYLOAD)
        stderr = ""

    def _slow_run(args, **kwargs):
        calls.append(args)
        release.wait(timeout=10)
        return _Proc()

    monkeypatch.setattr(_mkv_probe.subprocess, "run", _slow_run)

    results: list = []

    def _probe():
        start_barrier.wait(timeout=10)
        results.append(probe_file(Path("mkvmerge"), video))

    threads = [threading.Thread(target=_probe) for _ in range(2)]
    for t in threads:
        t.start()
    start_barrier.wait(timeout=10)  # both threads poised to probe
    time.sleep(0.2)  # let both reach the subprocess layer
    release.set()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert all(r.ok for r in results)
    assert len(calls) == 1  # the second caller waited for the first's result
