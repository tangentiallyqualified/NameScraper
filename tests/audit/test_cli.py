from __future__ import annotations

from pathlib import Path

from audit import __main__ as cli


def test_full_run_produces_outputs(synthetic_repo: Path):
    rc = cli.main(["--repo-root", str(synthetic_repo)])
    assert rc in (0, 2)  # 2 allowed: synthetic repo has no coverage data
    audit_docs = synthetic_repo / "docs" / "audit"
    assert (audit_docs / "llm" / "INDEX.md").exists()
    assert (audit_docs / "maps" / "overview.md").exists()
    assert (audit_docs / "doc-status.md").exists()
    assert (audit_docs / "baseline.json").exists()
    assert (audit_docs / "CHANGES.md").exists()


def test_single_stage_requires_inputs(synthetic_repo: Path):
    rc = cli.main(["metrics", "--repo-root", str(synthetic_repo)])
    assert rc == 1  # missing inventory artifact -> hard failure with message


def test_fast_rerenders_without_analyzers(synthetic_repo: Path):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    index = synthetic_repo / "docs" / "audit" / "llm" / "INDEX.md"
    index.unlink()
    rc = cli.main(["--fast", "--repo-root", str(synthetic_repo)])
    assert rc == 0
    assert index.exists()


def test_check_reports_staleness(synthetic_repo: Path, capsys, repo_git):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    capsys.readouterr()
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nZ = 1\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "touch alpha")
    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 commit" in out and "1 mapped module" in out


def test_check_current_baseline(synthetic_repo: Path, capsys):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    capsys.readouterr()
    # regenerated docs/audit outputs are uncommitted, but baseline commit == HEAD
    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])
    assert rc == 0
    assert "current" in capsys.readouterr().out


def test_fast_does_not_restamp_baseline(synthetic_repo: Path, capsys, repo_git):
    import json
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    (synthetic_repo / "plex_renamer" / "alpha.py").write_text(
        (synthetic_repo / "plex_renamer" / "alpha.py").read_text(encoding="utf-8") + "\nZ = 1\n",
        encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "touch alpha")
    assert cli.main(["--fast", "--repo-root", str(synthetic_repo)]) == 0
    capsys.readouterr()
    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "behind" in out  # --fast must NOT have restamped the baseline to current HEAD


def test_render_all_degrades_per_renderer(synthetic_repo: Path, monkeypatch):
    from audit import _render_llm

    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)

    def _boom(repo_root, options):
        raise RuntimeError("llm renderer down")

    monkeypatch.setattr(_render_llm, "run", _boom)
    overview = synthetic_repo / "docs" / "audit" / "maps" / "overview.md"
    overview.unlink()
    rc = cli.main(["--fast", "--repo-root", str(synthetic_repo)])
    assert rc == 2
    assert overview.exists()  # human renderer still ran despite llm failure
