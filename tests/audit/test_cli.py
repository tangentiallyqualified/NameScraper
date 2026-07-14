from __future__ import annotations

import json
from pathlib import Path

from audit import _artifacts
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


def _write_baseline(repo_root: Path, payload: dict) -> None:
    path = repo_root / "docs" / "audit" / "baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_check_reports_stale_when_input_digest_changes(synthetic_repo: Path, capsys):
    _write_baseline(synthetic_repo, {
        "input_digest": _artifacts.input_digest(synthetic_repo),
    })
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nZ = 1\n", encoding="utf-8")

    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "stale" in out
    assert "refresh" in out


def test_check_current_baseline(synthetic_repo: Path, capsys):
    _write_baseline(synthetic_repo, {
        "commit": "deliberately-not-head",
        "input_digest": _artifacts.input_digest(synthetic_repo),
    })

    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])

    assert rc == 0
    assert "current" in capsys.readouterr().out


def test_check_ignores_dirty_unenrolled_doc(synthetic_repo: Path, capsys):
    _write_baseline(synthetic_repo, {
        "input_digest": _artifacts.input_digest(synthetic_repo),
    })
    (synthetic_repo / "README.md").write_text("# dirty only\n", encoding="utf-8")

    assert cli.main(["--check", "--repo-root", str(synthetic_repo)]) == 0
    assert "baseline current" in capsys.readouterr().out


def test_check_legacy_baseline_requests_regeneration(synthetic_repo: Path, capsys):
    _write_baseline(synthetic_repo, {"commit": "abc1234"})

    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "stale" in out
    assert "regenerate" in out


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
