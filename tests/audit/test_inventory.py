from __future__ import annotations

from pathlib import Path

from audit import _artifacts, _inventory


def test_python_files_have_loc_and_hash(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    paths = {f["path"] for f in inv["python_files"]}
    assert paths == {"plex_renamer/__init__.py", "plex_renamer/alpha.py", "plex_renamer/beta.py"}
    alpha = next(f for f in inv["python_files"] if f["path"] == "plex_renamer/alpha.py")
    assert alpha["loc"] > 5
    assert len(alpha["sha256"]) == 16
    assert alpha["package"] == "plex_renamer"


def test_test_files_map_to_imported_modules(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    t = next(f for f in inv["test_files"] if f["path"] == "tests/test_alpha.py")
    assert t["imports_modules"] == ["plex_renamer.alpha"]


def test_docs_flag_broken_refs(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    guide = next(d for d in inv["docs"] if d["path"] == "docs/guide.md")
    assert "plex_renamer/alpha.py" in guide["source_refs"]
    assert guide["broken_refs"] == ["plex_renamer/gone.py"]
    assert guide["last_touched"]  # git commit date


def test_excluded_dirs_skipped(synthetic_repo: Path):
    (synthetic_repo / ".venv").mkdir()
    (synthetic_repo / ".venv" / "junk.py").write_text("x = 1\n", encoding="utf-8")
    inv = _inventory.build_inventory(synthetic_repo)
    assert all(".venv" not in f["path"] for f in inv["python_files"])


def test_run_writes_artifact(synthetic_repo: Path):
    assert _inventory.run(synthetic_repo, None) == 0
    data = _artifacts.read_artifact(synthetic_repo, "inventory")
    assert data["python_files"]


def test_git_timeout_falls_back_to_mtime(synthetic_repo: Path, monkeypatch):
    import subprocess as sp

    def _raise_timeout(*args, **kwargs):
        raise sp.TimeoutExpired(cmd="git", timeout=15)

    monkeypatch.setattr(sp, "run", _raise_timeout)
    inv = _inventory.build_inventory(synthetic_repo)
    guide = next(d for d in inv["docs"] if d["path"] == "docs/guide.md")
    assert guide["last_touched"]  # mtime fallback, no crash
