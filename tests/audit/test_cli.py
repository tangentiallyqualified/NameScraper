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


def test_check_reports_dirty_product_file_at_current_head(synthetic_repo: Path, capsys):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    capsys.readouterr()
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nDIRTY = 1\n", encoding="utf-8")
    assert cli.main(["--check", "--repo-root", str(synthetic_repo)]) == 0
    out = capsys.readouterr().out
    assert "current" in out
    assert "1 mapped module" in out
    assert "uncommitted" in out


def test_check_counts_new_product_module(synthetic_repo: Path, capsys, repo_git):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    capsys.readouterr()
    (synthetic_repo / "plex_renamer" / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "add module")
    assert cli.main(["--check", "--repo-root", str(synthetic_repo)]) == 0
    assert "1 mapped module" in capsys.readouterr().out


def test_check_reports_dirty_harness_file(synthetic_repo: Path, capsys):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    capsys.readouterr()
    harness = synthetic_repo / "scripts" / "audit" / "_new.py"
    harness.parent.mkdir(parents=True)
    harness.write_text("VALUE = 1\n", encoding="utf-8")
    assert cli.main(["--check", "--repo-root", str(synthetic_repo)]) == 0
    out = capsys.readouterr().out
    assert "1 audit harness file" in out


def test_check_ignores_dirty_unenrolled_doc(synthetic_repo: Path, capsys):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    capsys.readouterr()
    (synthetic_repo / "README.md").write_text("# dirty only\n", encoding="utf-8")
    assert cli.main(["--check", "--repo-root", str(synthetic_repo)]) == 0
    assert "baseline current" in capsys.readouterr().out


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


def test_fast_leaves_diff_outputs_byte_for_byte_unchanged(synthetic_repo: Path, repo_git):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    baseline = synthetic_repo / "docs" / "audit" / "baseline.json"
    changes = synthetic_repo / "docs" / "audit" / "CHANGES.md"
    before = (baseline.read_bytes(), changes.read_bytes())
    (synthetic_repo / "README.md").write_text("# new commit\n", encoding="utf-8")
    repo_git(synthetic_repo, "add", "-A")
    repo_git(synthetic_repo, "commit", "-m", "advance head")
    assert cli.main(["--fast", "--repo-root", str(synthetic_repo)]) == 0
    assert (baseline.read_bytes(), changes.read_bytes()) == before


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


def test_render_stage_missing_artifacts_exits_1(synthetic_repo: Path, capsys):
    rc = cli.main(["render", "--repo-root", str(synthetic_repo)])
    assert rc == 1  # MissingArtifactError contract: single message, hard exit
    out = capsys.readouterr().out
    assert "Missing artifact" in out
