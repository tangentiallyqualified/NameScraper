"""Audit harness CLI. Run via scripts/audit.cmd or `python -m audit`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (
    _analyze,
    _artifacts,
    _coverage,
    _decisions,
    _diff,
    _docs_ledger,
    _graph,
    _inventory,
    _metrics,
    _ratchet_identity,
    _ratchets,
    _render_code_index,
    _render_human,
    _render_sarif,
    _toolchain,
    _verify,
)

HARD_STAGES = {"inventory", "graph"}


_ascii = _artifacts.ascii_safe


def _collect_review_findings(repo_root: Path) -> list[dict]:
    baseline_path = repo_root / "scripts" / "audit" / "quality-baseline.json"
    baseline = _ratchets._load_baseline(repo_root) if baseline_path.exists() else {}
    inventory = _inventory.build_inventory(repo_root)
    graph = _graph.build_graph(repo_root, inventory)
    analysis = _analyze.run_analysis(repo_root, inventory, graph)
    policy_ruff = _ratchets._run_policy_ruff(repo_root)
    records = _ratchets._repository_python_records(repo_root)
    python_files = sorted(record["path"] for record in records)
    legacy = _ratchets._normalized_python_files(
        baseline.get("typing", {}).get("legacy_python_files")
    )
    policy_pyright = (
        _ratchets._run_policy_pyright(repo_root, python_files, legacy)
        if (repo_root / "pyrightconfig.json").exists()
        else []
    )
    failed = _ratchets._failed_analyzers(analysis)
    if failed:
        raise _ratchets.QualityEvidenceError(
            "quality evidence unavailable from: " + ", ".join(failed)
        )
    analysis_findings = [
        finding for finding in analysis.get("findings", []) if finding.get("source") != "ruff"
    ]
    raw_findings = (
        [finding for finding in analysis_findings if finding.get("source") != "vulture"]
        + _ratchet_identity.qualify_vulture_findings(
            repo_root,
            [finding for finding in analysis_findings if finding.get("source") == "vulture"],
        )
        + policy_ruff
        + policy_pyright
    )
    findings = [
        {
            **finding,
            "analyzer": finding.get("source"),
            "path": str(finding.get("path") or "").replace("\\", "/"),
        }
        for finding in raw_findings
        if finding.get("category") != "complexity"
    ]
    findings.sort(key=lambda finding: _ratchets._identity_sort_key(_ratchets._identity(finding)))
    return _decisions.apply(
        findings, _decisions.load(repo_root / "scripts" / "audit" / "decisions.toml")
    )


def _run_findings(repo_root: Path, options: object) -> int:
    try:
        findings = _collect_review_findings(repo_root)
        _artifacts.write_artifact(repo_root, "findings", {"findings": findings})
    except (OSError, ValueError, _ratchets.QualityEvidenceError) as exc:
        print(_ascii(f"findings: failed - {exc}"))
        return 1
    print(f"findings: {len(findings)} normalized findings")
    return 0


def _render_all(repo_root: Path, options) -> int:
    rc = 0
    for mod in (_render_code_index, _render_human, _render_sarif, _docs_ledger):
        try:
            rc = max(rc, mod.run(repo_root, options))
        except _artifacts.MissingArtifactError:
            raise
        except Exception as exc:
            print(_ascii(f"render: {mod.__name__} failed - {exc}"))
            rc = max(rc, 2)
    return rc


STAGES: list[tuple[str, object]] = [
    ("inventory", _inventory.run),
    ("graph", _graph.run),
    ("analyze", _analyze.run),
    ("findings", _run_findings),
    ("coverage", _coverage.run),
    ("metrics", _metrics.run),
    ("render", _render_all),
    ("diff", _diff.run),
]
STAGE_NAMES = [name for name, _fn in STAGES]
FAST_STAGES = {"render"}


def check_lines(repo_root: Path) -> list[str]:
    baseline_path = repo_root / "docs" / "audit" / "baseline.json"
    if not baseline_path.exists():
        return ["no audit baseline; run scripts\\audit.cmd to create one"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_digest = baseline.get("input_digest")
    if not baseline_digest:
        return [
            "audit baseline stale (legacy baseline has no input digest); "
            "run scripts\\audit.cmd to regenerate"
        ]
    current_digest = _artifacts.input_digest(repo_root)
    if current_digest == baseline_digest:
        return [f"audit baseline current ({current_digest})"]
    return [
        "audit baseline stale (audit inputs changed)",
        "run scripts\\audit.cmd to refresh",
    ]


def _validate_accept_enlarged(parser: argparse.ArgumentParser, options: argparse.Namespace) -> None:
    if options.accept_enlarged and not options.update_quality_baseline:
        parser.error("--accept-enlarged requires --update-quality-baseline")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="audit", description="Codebase mapping/audit pipeline.")
    parser.add_argument(
        "stage",
        nargs="?",
        choices=STAGE_NAMES,
        help="Run a single stage instead of the full pipeline.",
    )
    parser.add_argument(
        "--fast", action="store_true", help="Only re-render outputs from existing .audit artifacts."
    )
    parser.add_argument(
        "--with-coverage", action="store_true", help="Run the fast test suite fresh under coverage."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only staleness probe against docs/audit/baseline.json.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run the full pipeline and report generated drift without mutation.",
    )
    parser.add_argument(
        "--quality-check",
        action="store_true",
        help="Fail on new/enlarged quality debt; report stale baseline entries.",
    )
    parser.add_argument(
        "--update-quality-baseline",
        action="store_true",
        help="Refresh an existing quality baseline without enrolling new Python files.",
    )
    parser.add_argument(
        "--accept-enlarged",
        action="store_true",
        help="With --update-quality-baseline: accept and report new/enlarged debt entries.",
    )
    parser.add_argument(
        "--coverage-max-age",
        type=int,
        default=15,
        help=("Legacy compatibility option; digest-based coverage freshness ignores this value."),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repo root override (used by tests).",
    )
    options = parser.parse_args(argv)
    if options.verify and (options.fast or options.check or options.stage):
        parser.error("--verify cannot be combined with --fast, --check, or a stage")
    if options.update_quality_baseline and (
        options.fast
        or options.with_coverage
        or options.check
        or options.verify
        or options.quality_check
        or options.stage
    ):
        parser.error(
            "--update-quality-baseline cannot be combined with --fast, --with-coverage, "
            "--check, --verify, --quality-check, or a stage"
        )
    if options.quality_check and (
        options.fast
        or options.with_coverage
        or options.check
        or options.verify
        or options.update_quality_baseline
        or options.stage
    ):
        parser.error(
            "--quality-check cannot be combined with --fast, --with-coverage, "
            "--check, --verify, or a stage"
        )
    _validate_accept_enlarged(parser, options)
    return options


def _run_pipeline(repo_root: Path, options: argparse.Namespace) -> int:
    if not options.fast:
        incompatibilities = _toolchain.validate(repo_root)
        if incompatibilities:
            for issue in incompatibilities:
                print(_ascii(f"audit toolchain incompatible: {issue}"))
            return 1
    if options.stage:
        selected = [(n, fn) for n, fn in STAGES if n == options.stage]
    elif options.fast:
        selected = [(n, fn) for n, fn in STAGES if n in FAST_STAGES]
    else:
        selected = STAGES

    worst = 0
    for name, fn in selected:
        try:
            rc = fn(repo_root, options)
        except _artifacts.MissingArtifactError as exc:
            print(_ascii(f"{name}: {exc}"))
            return 1
        except Exception as exc:
            print(_ascii(f"{name}: failed - {exc}"))
            if name in HARD_STAGES or options.stage:
                return 1
            worst = max(worst, 2)
            continue
        worst = max(worst, rc)

    if not options.stage and not options.fast:
        changes = repo_root / "docs" / "audit" / "CHANGES.md"
        if changes.exists():
            print("")
            for line in changes.read_text(encoding="utf-8").splitlines()[2:10]:
                print(line)
    return worst


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    repo_root = options.repo_root.resolve()

    if options.update_quality_baseline:
        return _ratchets.run_quality_baseline_update(repo_root, options.accept_enlarged)

    if options.quality_check:
        return _ratchets.run_quality_check(repo_root)

    if options.check:
        for line in check_lines(repo_root):
            print(line)
        return 0

    if options.verify:
        try:
            pipeline_rc, drift = _verify.verify(
                repo_root, lambda: _run_pipeline(repo_root, options)
            )
        except _verify.UnsafeGeneratedTreeError as exc:
            print(_ascii(str(exc)))
            return 1
        if drift:
            print("generated drift:")
            for relative in drift:
                print(f"  {relative}")
        else:
            print("audit generated output is current")
        if pipeline_rc:
            return pipeline_rc
        return 1 if drift else 0

    return _run_pipeline(repo_root, options)


if __name__ == "__main__":
    sys.exit(main())
