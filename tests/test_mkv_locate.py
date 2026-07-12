"""mkvmerge binary discovery."""
from pathlib import Path

from plex_renamer import _mkv_locate
from plex_renamer._mkv_locate import find_mkvmerge


def _no_which(monkeypatch):
    monkeypatch.setattr(_mkv_locate.shutil, "which", lambda name: None)


def test_explicit_file_wins(tmp_path, monkeypatch):
    _no_which(monkeypatch)
    exe = tmp_path / "mkvmerge.exe"
    exe.write_bytes(b"")
    assert find_mkvmerge(str(exe)) == exe


def test_explicit_directory_resolves_exe(tmp_path, monkeypatch):
    _no_which(monkeypatch)
    # Directory resolution appends the platform-specific binary name.
    exe = tmp_path / _mkv_locate._EXE_NAME
    exe.write_bytes(b"")
    assert find_mkvmerge(str(tmp_path)) == exe


def test_bad_explicit_path_returns_none_without_fallback(tmp_path, monkeypatch):
    # An explicit setting that doesn't resolve is an error, not a fallback.
    monkeypatch.setattr(
        _mkv_locate.shutil, "which", lambda name: str(tmp_path / "other.exe"))
    assert find_mkvmerge(str(tmp_path / "missing.exe")) is None


def test_which_fallback(tmp_path, monkeypatch):
    exe = tmp_path / "mkvmerge.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(_mkv_locate.shutil, "which", lambda name: str(exe))
    assert find_mkvmerge("") == exe


def test_program_files_fallback(tmp_path, monkeypatch):
    _no_which(monkeypatch)
    toolnix = tmp_path / "MKVToolNix"
    toolnix.mkdir()
    exe = toolnix / _mkv_locate._EXE_NAME
    exe.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert find_mkvmerge("") == exe


def test_nothing_found(monkeypatch, tmp_path):
    _no_which(monkeypatch)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert find_mkvmerge("") is None
