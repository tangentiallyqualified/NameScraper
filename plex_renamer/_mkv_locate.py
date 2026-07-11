"""Locate the mkvmerge executable (spec §3.1)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_EXE_NAME = "mkvmerge.exe" if os.name == "nt" else "mkvmerge"
_PROPEDIT_NAME = "mkvpropedit.exe" if os.name == "nt" else "mkvpropedit"


def find_mkvmerge(explicit_path: str = "") -> Path | None:
    """Resolve the mkvmerge binary.

    An explicit path (file or containing directory) that fails to resolve
    returns None — a configured-but-wrong setting must surface as
    "not found", never silently fall back to a different binary.
    """
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.is_file():
            return candidate
        exe = candidate / _EXE_NAME
        if exe.is_file():
            return exe
        return None

    which = shutil.which("mkvmerge")
    if which:
        return Path(which)

    for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            exe = Path(base) / "MKVToolNix" / _EXE_NAME
            if exe.is_file():
                return exe
    return None


def find_mkvpropedit(mkvmerge_setting: str = "") -> Path | None:
    """Resolve mkvpropedit — it ships beside mkvmerge in MKVToolNix.

    Prefers the sibling of the resolved mkvmerge (so a custom install
    keeps both tools consistent), then PATH, then the standard install
    folders.
    """
    mkvmerge = find_mkvmerge(mkvmerge_setting)
    if mkvmerge is not None:
        sibling = mkvmerge.parent / _PROPEDIT_NAME
        if sibling.is_file():
            return sibling

    which = shutil.which("mkvpropedit")
    if which:
        return Path(which)

    for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            exe = Path(base) / "MKVToolNix" / _PROPEDIT_NAME
            if exe.is_file():
                return exe
    return None
