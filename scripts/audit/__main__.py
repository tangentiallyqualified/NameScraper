"""Audit harness CLI. Run via scripts/audit.cmd or `python -m audit`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (_analyze, _artifacts, _coverage, _diff, _docs_ledger, _graph,
               _inventory, _metrics, _render_code_index, _render_human,
               _toolchain, _verify)

HARD_STAGES = {"inventory", "graph"}


_ascii = _artifacts.ascii_safe


def _render_all(repo_root: Path, options) -> int:
    rc = 0
    for mod in (_render_code_index, _render_human, _docs_ledger):
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="audit", description="Codebase mapping/audit pipeline.")
    parser.add_argument("stage", nargs="?", choices=STAGE_NAMES,
                        help="Run a single stage instead of the full pipeline.")
    parser.add_argument("--fast", action="store_true",
                        help="Only re-render outputs from existing .audit artifacts.")
    parser.add_argument("--with-coverage", action="store_true",
                        help="Run the fast test suite fresh under coverage.")
    parser.add_argument("--check", action="store_true",
                        help="Read-only staleness probe against docs/audit/baseline.json.")
    parser.add_argument("--verify", action="store_true",
                        help="Run the full pipeline and report generated drift without mutation.")
    parser.add_argument("--coverage-max-age", type=int, default=15,
                        help=("Legacy compatibility option; digest-based coverage freshness "
                              "ignores this value."))
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[2],
                        help="Repo root override (used by tests).")
    options = parser.parse_args(argv)
    if options.verify and (options.fast or options.check or options.stage):
        parser.error("--verify cannot be combined with --fast, --check, or a stage")
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
