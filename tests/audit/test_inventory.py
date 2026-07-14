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
    assert t["imports_symbols"] == ["plex_renamer.alpha.used_function"]


def test_test_files_map_direct_aliases_and_module_alias_attributes(synthetic_repo: Path):
    (synthetic_repo / "tests" / "test_symbol_imports.py").write_text(
        "from plex_renamer.alpha import dead_function as renamed\n"
        "from plex_renamer import alpha as alpha_module\n\n"
        "import plex_renamer.beta as beta_module\n"
        "renamed()\n"
        "alpha_module.used_function(2)\n"
        "beta_module.run()\n",
        encoding="utf-8",
    )

    inv = _inventory.build_inventory(synthetic_repo)
    record = next(
        f for f in inv["test_files"] if f["path"] == "tests/test_symbol_imports.py"
    )

    assert record["imports_modules"] == ["plex_renamer", "plex_renamer.alpha", "plex_renamer.beta"]
    assert "plex_renamer.alpha.dead_function" in record["imports_symbols"]
    assert "plex_renamer.alpha.used_function" in record["imports_symbols"]
    assert "plex_renamer.beta.run" in record["imports_symbols"]


def test_docs_flag_broken_refs(synthetic_repo: Path):
    inv = _inventory.build_inventory(synthetic_repo)
    guide = next(d for d in inv["docs"] if d["path"] == "docs/guide.md")
    assert "plex_renamer/alpha.py" in guide["source_refs"]
    assert guide["broken_refs"] == ["plex_renamer/gone.py"]
    assert guide["last_touched"]  # git commit date


def test_generated_audit_docs_are_excluded_from_content_inventory(
        synthetic_repo: Path, repo_git):
    generated_paths = (
        "docs/audit/CHANGES.md",
        "docs/audit/code-index/INDEX.md",
        "docs/audit/doc-status.md",
        "docs/audit/llm/INDEX.md",
        "docs/audit/maps/overview.md",
    )
    for relative in generated_paths:
        path = synthetic_repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated audit output\n", encoding="utf-8")

    before = {record["path"] for record in _inventory.build_inventory(synthetic_repo)["docs"]}
    repo_git(synthetic_repo, "add", "docs/audit")
    repo_git(synthetic_repo, "commit", "-m", "track generated audit docs")
    after = {record["path"] for record in _inventory.build_inventory(synthetic_repo)["docs"]}

    assert before == after
    assert not set(generated_paths).intersection(after)


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


def test_scripts_inventoried(synthetic_repo: Path):
    (synthetic_repo / "scripts").mkdir(exist_ok=True)
    (synthetic_repo / "scripts" / "tool.ps1").write_text("Write-Host hi\n", encoding="utf-8")
    inv = _inventory.build_inventory(synthetic_repo)
    assert {"path": "scripts/tool.ps1"} in inv["scripts"]


def test_run_prints_count_from_inventory(synthetic_repo: Path, capsys):
    assert _inventory.run(synthetic_repo, None) == 0
    out = capsys.readouterr().out
    assert "inventory: 3 package files indexed" in out


def test_excluded_name_as_file_is_skipped(synthetic_repo: Path):
    (synthetic_repo / "scripts").mkdir(exist_ok=True)
    (synthetic_repo / "scripts" / ".venv").write_text("not a dir\n", encoding="utf-8")
    inv = _inventory.build_inventory(synthetic_repo)
    assert {"path": "scripts/.venv"} not in inv["scripts"]


def test_unreadable_file_skipped_not_fatal(synthetic_repo: Path, monkeypatch):
    (synthetic_repo / "plex_renamer" / "gamma.py").write_text('"""Gamma."""\n', encoding="utf-8")
    real_sha = _inventory._sha

    def _flaky(path: Path) -> str:
        if path.name == "gamma.py":
            raise OSError("unreadable entry (simulated broken symlink)")
        return real_sha(path)

    monkeypatch.setattr(_inventory, "_sha", _flaky)
    inv = _inventory.build_inventory(synthetic_repo)
    paths = {r["path"] for r in inv["python_files"]}
    assert "plex_renamer/gamma.py" not in paths
    assert "plex_renamer/alpha.py" in paths
