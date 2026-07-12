"""Stage 4: coverage evidence - import newest .coverage data or run fresh."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import _artifacts


def _read_modules(repo_root: Path, data_file: Path) -> dict[str, dict]:
    import coverage

    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()
    modules: dict[str, dict] = {}
    for measured in cov.get_data().measured_files():
        p = Path(measured)
        try:
            rel = p.resolve().relative_to(repo_root.resolve())
        except ValueError:
            continue
        if rel.parts[0] != "plex_renamer":
            continue
        _, statements, _, missing, _ = cov.analysis2(measured)
        n = len(statements)
        covered = n - len(missing)
        modules[rel.as_posix()] = {
            "statements": n,
            "covered": covered,
            "percent": round(100.0 * covered / n, 1) if n else 100.0,
        }
    return modules


def _run_fresh(repo_root: Path) -> None:
    runner = repo_root / "scripts" / "test_fast_runner.py"
    result = subprocess.run(
        [sys.executable, str(runner), "--coverage"],
        cwd=repo_root, capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fresh coverage run failed (exit {result.returncode})")


def collect_coverage(repo_root: Path, fresh: bool = False, max_age_commits: int = 15) -> dict:
    unavailable = {
        "available": False, "reason": None, "source": None,
        "collected_at_commit": None, "age_commits": None, "stale": False, "modules": {},
    }
    if fresh:
        try:
            _run_fresh(repo_root)
        except Exception as exc:
            return {**unavailable, "reason": str(exc)[:200]}

    data_file = repo_root / ".coverage"
    if not data_file.exists():
        return {**unavailable,
                "reason": "no .coverage data file; run scripts\\test-fast.cmd -Coverage"}

    try:
        modules = _read_modules(repo_root, data_file)
    except Exception as exc:
        return {**unavailable, "reason": f"could not read coverage data: {exc}"[:200]}

    commit = None
    meta_file = repo_root / ".coverage.meta.json"
    if meta_file.exists():
        try:
            commit = json.loads(meta_file.read_text(encoding="utf-8")).get("commit")
        except (json.JSONDecodeError, OSError):
            commit = None
    age = _artifacts.commits_between(repo_root, commit) if commit else None
    stale = age is None or age > max_age_commits
    return {
        "available": True, "reason": None,
        "source": "fresh" if fresh else "imported",
        "collected_at_commit": commit, "age_commits": age,
        "stale": stale, "modules": modules,
    }


def run(repo_root: Path, options) -> int:
    fresh = bool(getattr(options, "with_coverage", False))
    raw_age = getattr(options, "coverage_max_age", None)
    max_age = 15 if raw_age is None else int(raw_age)
    cov = collect_coverage(repo_root, fresh=fresh, max_age_commits=max_age)
    _artifacts.write_artifact(repo_root, "coverage", cov)
    if cov["available"]:
        note = " (stale)" if cov["stale"] else ""
        print(f"coverage: {len(cov['modules'])} modules from {cov['source']} data{note}")
        return 0
    print(f"coverage: unavailable - {cov['reason']}")
    return 2
