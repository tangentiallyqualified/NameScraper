from __future__ import annotations

import json
from pathlib import Path

import pytest
from audit import __main__ as cli
from audit import _artifacts


def test_quality_check_returns_zero_for_stale_baseline_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    coverage = {
        "input_digest": "a" * 64,
        "suite": "fast",
        "full_suite": True,
        "scope_id": "b" * 64,
        "files": {"plex_renamer/a.py": {"executable_lines": []}},
        "package_floors": {},
    }
    baseline = {
        "schema_version": 2,
        "findings": [{"analyzer": "ruff", "rule": "F401", "path": "old.py", "symbol": "gone"}],
        "ceilings": {},
        "complexity": {},
        "formatting": {},
        "typing": {"legacy_python_files": []},
        "coverage": {
            "changed_line_min_percent": 80.0,
            "executable_lines": {"plex_renamer/a.py": []},
            "full_suite": True,
            "package_floors": {},
            "scope_id": "b" * 64,
            "suite": "fast",
        },
    }
    path = tmp_path / "scripts" / "audit" / "quality-baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(
        "audit._ratchets.collect_current",
        lambda _root, _baseline: {
            "findings": [],
            "modules": {},
            "complexity": {},
            "formatting": {},
        },
    )
    monkeypatch.setattr("audit._coverage.collect_quality_coverage", lambda _root: coverage)

    assert cli.main(["--quality-check", "--repo-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "quality: stale-baseline: old.py: ruff/F401 [gone]" in output
    assert "quality: 0 new/enlarged debt; 1 stale baseline entry" in output


def test_full_run_produces_outputs(synthetic_repo: Path):
    rc = cli.main(["--repo-root", str(synthetic_repo)])
    assert rc in (0, 2)  # 2 allowed: synthetic repo has no coverage data
    audit_docs = synthetic_repo / "docs" / "audit"
    assert (audit_docs / "code-index" / "INDEX.md").exists()
    assert (audit_docs / "maps" / "overview.md").exists()
    assert (audit_docs / "doc-status.md").exists()
    assert (audit_docs / "baseline.json").exists()
    assert (audit_docs / "CHANGES.md").exists()


def test_single_stage_requires_inputs(synthetic_repo: Path):
    rc = cli.main(["metrics", "--repo-root", str(synthetic_repo)])
    assert rc == 1  # missing inventory artifact -> hard failure with message


def test_fast_rerenders_without_analyzers(synthetic_repo: Path):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    index = synthetic_repo / "docs" / "audit" / "code-index" / "INDEX.md"
    index.unlink()
    rc = cli.main(["--fast", "--repo-root", str(synthetic_repo)])
    assert rc == 0
    assert index.exists()


def _write_baseline(repo_root: Path, payload: dict) -> None:
    path = repo_root / "docs" / "audit" / "baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_check_reports_stale_when_input_digest_changes(synthetic_repo: Path, capsys):
    _write_baseline(
        synthetic_repo,
        {
            "input_digest": _artifacts.input_digest(synthetic_repo),
        },
    )
    alpha = synthetic_repo / "plex_renamer" / "alpha.py"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\nZ = 1\n", encoding="utf-8")

    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "stale" in out
    assert "refresh" in out


def test_check_current_baseline(synthetic_repo: Path, capsys):
    _write_baseline(
        synthetic_repo,
        {
            "commit": "deliberately-not-head",
            "input_digest": _artifacts.input_digest(synthetic_repo),
        },
    )

    rc = cli.main(["--check", "--repo-root", str(synthetic_repo)])

    assert rc == 0
    assert "current" in capsys.readouterr().out


def test_check_reports_stale_when_inventoried_doc_changes(synthetic_repo: Path, capsys):
    _write_baseline(
        synthetic_repo,
        {
            "input_digest": _artifacts.input_digest(synthetic_repo),
        },
    )
    (synthetic_repo / "README.md").write_text("# dirty only\n", encoding="utf-8")

    assert cli.main(["--check", "--repo-root", str(synthetic_repo)]) == 0
    assert "baseline stale" in capsys.readouterr().out


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
    from audit import _render_code_index

    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)

    def _boom(repo_root, options):
        raise RuntimeError("code-index renderer down")

    monkeypatch.setattr(_render_code_index, "run", _boom)
    overview = synthetic_repo / "docs" / "audit" / "maps" / "overview.md"
    overview.unlink()
    rc = cli.main(["--fast", "--repo-root", str(synthetic_repo)])
    assert rc == 2
    assert overview.exists()  # human renderer still ran despite code-index failure


def test_render_stage_missing_artifacts_exits_1(synthetic_repo: Path, capsys):
    rc = cli.main(["render", "--repo-root", str(synthetic_repo)])
    assert rc == 1  # MissingArtifactError contract: single message, hard exit
    out = capsys.readouterr().out
    assert "Missing artifact" in out


def test_verify_reports_current_generated_output(synthetic_repo: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "STAGES", [("inventory", lambda _root, _options: 0)])

    rc = cli.main(["--verify", "--repo-root", str(synthetic_repo)])

    assert rc == 0
    assert "audit generated output is current" in capsys.readouterr().out


def test_verify_reports_sorted_drift_and_restores_tree(synthetic_repo: Path, monkeypatch, capsys):
    audit_dir = synthetic_repo / "docs" / "audit"
    audit_dir.mkdir(parents=True)
    original = b"curated bytes\r\n"
    curated = audit_dir / "findings-review.md"
    curated.write_bytes(original)

    def generate(repo_root: Path, _options) -> int:
        (repo_root / "docs" / "audit" / "z.md").write_bytes(b"z\n")
        (repo_root / "docs" / "audit" / "a.md").write_bytes(b"a\n")
        return 0

    monkeypatch.setattr(cli, "STAGES", [("inventory", generate)])

    rc = cli.main(["--verify", "--repo-root", str(synthetic_repo)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "generated drift:\n  docs/audit/a.md\n  docs/audit/z.md" in out
    assert curated.read_bytes() == original
    assert not (audit_dir / "a.md").exists()
    assert not (audit_dir / "z.md").exists()


def test_verify_returns_pipeline_failure_after_restoration(synthetic_repo: Path, monkeypatch):
    audit_dir = synthetic_repo / "docs" / "audit"
    audit_dir.mkdir(parents=True)
    baseline = audit_dir / "baseline.json"
    baseline.write_bytes(b"original\n")

    def fail_after_writing(repo_root: Path, _options) -> int:
        (repo_root / "docs" / "audit" / "baseline.json").write_bytes(b"partial\n")
        return 2

    monkeypatch.setattr(cli, "STAGES", [("inventory", fail_after_writing)])

    assert cli.main(["--verify", "--repo-root", str(synthetic_repo)]) == 2
    assert baseline.read_bytes() == b"original\n"


def test_verify_reports_unsafe_preexisting_generated_link(
    synthetic_repo: Path, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli._verify,
        "verify",
        lambda _repo, _pipeline: (_ for _ in ()).throw(
            cli._verify.UnsafeGeneratedTreeError(["docs/audit/unsafe-link"])
        ),
    )

    assert cli.main(["--verify", "--repo-root", str(synthetic_repo)]) == 1

    output = capsys.readouterr().out
    assert "unsafe generated output tree" in output
    assert "docs/audit/unsafe-link" in output


def test_verify_is_byte_stable_when_default_text_newlines_are_windows_style(
    synthetic_repo: Path, monkeypatch, capsys
):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    generated = synthetic_repo / "docs" / "audit"
    seeded = {
        path.relative_to(synthetic_repo).as_posix(): path.read_bytes()
        for path in generated.rglob("*")
        if path.is_file() and path.name != "doc-ledger.toml"
    }
    assert seeded
    for relative, content in seeded.items():
        normalized = content.replace(b"\r\n", b"\n")
        (synthetic_repo / relative).write_bytes(normalized)
        seeded[relative] = normalized
    assert all(b"\r\n" not in content for content in seeded.values())
    original_write_text = Path.write_text

    def windows_default_write_text(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if newline is None:
            data = data.replace("\r\n", "\n").replace("\n", "\r\n")
        return original_write_text(path, data, encoding=encoding, errors=errors, newline="")

    monkeypatch.setattr(Path, "write_text", windows_default_write_text)

    assert cli.main(["--verify", "--repo-root", str(synthetic_repo)]) in (0, 2)
    assert "audit generated output is current" in capsys.readouterr().out
    assert {
        path.relative_to(synthetic_repo).as_posix(): path.read_bytes()
        for path in generated.rglob("*")
        if path.is_file() and path.name != "doc-ledger.toml"
    } == seeded


def test_one_generation_after_module_rename_is_immediately_verifiable(synthetic_repo: Path, capsys):
    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    (synthetic_repo / "plex_renamer" / "alpha.py").rename(
        synthetic_repo / "plex_renamer" / "renamed.py"
    )

    assert cli.main(["--repo-root", str(synthetic_repo)]) in (0, 2)
    assert cli.main(["--verify", "--repo-root", str(synthetic_repo)]) in (0, 2)

    assert "audit generated output is current" in capsys.readouterr().out


def test_coverage_max_age_help_marks_option_as_legacy(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    assert "legacy compatibility" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("other", ["--fast", "--check", "inventory"])
def test_verify_is_mutually_exclusive_with_other_run_modes(synthetic_repo: Path, other: str):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--verify", other, "--repo-root", str(synthetic_repo)])

    assert exc_info.value.code == 2


def test_findings_stage_precedes_rendering() -> None:
    assert cli.STAGE_NAMES.index("findings") < cli.STAGE_NAMES.index("render")
