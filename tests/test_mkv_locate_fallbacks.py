"""Hermetic mkvpropedit discovery fallback coverage."""

import os
from pathlib import Path

import pytest

from plex_renamer import _mkv_locate

PROPEDIT_NAME = "mkvpropedit.exe" if os.name == "nt" else "mkvpropedit"


def _no_mkvmerge(setting: str = "") -> None:
    del setting
    return None


def _not_on_path(name: str) -> None:
    del name
    return None


def test_find_mkvpropedit_uses_path_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propedit = tmp_path / PROPEDIT_NAME

    def path_lookup(name: str) -> str | None:
        return str(propedit) if name == "mkvpropedit" else None

    monkeypatch.setattr(_mkv_locate, "find_mkvmerge", _no_mkvmerge)
    monkeypatch.setattr(
        _mkv_locate.shutil,
        "which",
        path_lookup,
    )
    monkeypatch.setattr(_mkv_locate.os, "environ", {})

    assert _mkv_locate.find_mkvpropedit() == propedit


def test_find_mkvpropedit_uses_program_files_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolnix = tmp_path / "MKVToolNix"
    toolnix.mkdir()
    propedit = toolnix / PROPEDIT_NAME
    propedit.write_bytes(b"")
    monkeypatch.setattr(_mkv_locate, "find_mkvmerge", _no_mkvmerge)
    monkeypatch.setattr(_mkv_locate.shutil, "which", _not_on_path)
    monkeypatch.setattr(_mkv_locate.os, "environ", {"ProgramFiles": str(tmp_path)})

    assert _mkv_locate.find_mkvpropedit() == propedit
