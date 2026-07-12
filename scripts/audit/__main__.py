"""Audit harness CLI. Run via scripts/audit.cmd or `python -m audit`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (_analyze, _artifacts, _coverage, _diff, _docs_ledger, _graph,
               _inventory, _metrics, _render_human, _render_llm)

HARD_STAGES = {"inventory", "graph"}


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _render_all(repo_root: Path, options) -> int:
    rc = 0
    for mod in (_render_llm, _render_human, _docs_ledger):
        try:
            rc = max(rc, mod.run(repo_root, options))
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
FAST_STAGES = {"render", "diff"}


def check_lines(repo_root: Path) -> list[str]:
    baseline_path = repo_root / "docs" / "audit" / "baseline.json"
    if not baseline_path.exists():
        return ["no audit baseline; run scripts\\audit.cmd to create one"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    commit = baseline.get("commit")
    if not commit:
        return ["audit baseline has no commit stamp; rerun scripts\\audit.cmd"]
    behind = _artifacts.commits_between(repo_root, commit)
    if behind is None:
        return ["audit staleness check unavailable (git error)"]
    if behind == 0:
        return [f"audit baseline current ({commit})"]
    changed = _artifacts.changed_files_since(repo_root, commit, "plex_renamer") or []
    mapped = [c for c in changed if c in baseline.get("modules", {})]
    plural = "s" if behind != 1 else ""
    mplural = "s" if len(mapped) != 1 else ""
    return [
        f"audit baseline {commit} is {behind} commit{plural} behind HEAD",
        f"{len(mapped)} mapped module{mplural} changed since baseline",
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
    parser.add_argument("--coverage-max-age", type=int, default=15,
                        help="Commits before imported coverage counts as stale (default 15).")
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[2],
                        help="Repo root override (used by tests).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    repo_root = options.repo_root.resolve()

    if options.check:
        for line in check_lines(repo_root):
            print(line)
        return 0

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


if __name__ == "__main__":
    sys.exit(main())
