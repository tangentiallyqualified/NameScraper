"""Stage 4: coverage evidence - import newest .coverage data or run fresh."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import _artifacts


_FRESH_TIMEOUT_SECONDS = 1800
_DIAGNOSTIC_LIMIT = 400


def _diagnostic_context(value: object) -> str:
    """Return bounded, single-line, console-safe subprocess context."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    text = " ".join(text.split())
    return _artifacts.ascii_safe(text)[:_DIAGNOSTIC_LIMIT]


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


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
    command = [sys.executable, str(runner), "--coverage"]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_FRESH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        context = _diagnostic_context(exc.stderr)
        detail = f": {context}" if context else ""
        raise RuntimeError(
            f"fresh coverage run timed out after {_FRESH_TIMEOUT_SECONDS} seconds{detail}"
        ) from exc
    except OSError as exc:
        context = _diagnostic_context(exc)
        raise RuntimeError(f"could not launch fresh coverage run: {context}") from exc
    if result.returncode != 0:
        context = _diagnostic_context(result.stderr)
        detail = f": {context}" if context else ""
        raise RuntimeError(
            f"fresh coverage run failed (exit {result.returncode}){detail}"
        )


def collect_coverage(repo_root: Path, fresh: bool = False, max_age_commits: int = 15) -> dict:
    unavailable = {
        "available": False, "reason": None, "source": None,
        "collected_at_commit": None, "age_commits": None, "stale": False,
        "modules": {}, "partial": False, "failed": False,
        "scope_id": None, "scope": None,
    }
    if fresh:
        data_file = repo_root / ".coverage"
        meta_file = repo_root / ".coverage.meta.json"
        old_data_signature = _file_signature(data_file)
        old_meta_signature = _file_signature(meta_file)
        try:
            _run_fresh(repo_root)
        except Exception as exc:
            return {
                **unavailable,
                "reason": _diagnostic_context(exc),
                "source": "fresh",
                "stale": True,
                "partial": True,
                "failed": True,
            }
        if _file_signature(data_file) == old_data_signature:
            return {
                **unavailable,
                "reason": "fresh coverage run did not replace .coverage data",
                "source": "fresh",
                "stale": True,
                "partial": True,
                "failed": True,
            }
        if _file_signature(meta_file) == old_meta_signature:
            return {
                **unavailable,
                "reason": "fresh coverage run did not replace coverage metadata",
                "source": "fresh",
                "stale": True,
                "partial": True,
                "failed": True,
            }

    data_file = repo_root / ".coverage"
    if not data_file.exists():
        return {**unavailable,
                "reason": "no .coverage data file; run scripts\\test-fast.cmd -Coverage"}

    try:
        modules = _read_modules(repo_root, data_file)
    except Exception as exc:
        return {**unavailable, "reason": f"could not read coverage data: {exc}"[:200]}

    commit = None
    partial = False
    failed = False
    scope_id = None
    scope = None
    meta_file = repo_root / ".coverage.meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                raise ValueError("coverage metadata must be a JSON object")
            raw_commit = meta.get("commit")
            commit = (
                raw_commit.strip()
                if isinstance(raw_commit, str) and raw_commit.strip()
                else None
            )
            raw_partial = meta.get("partial", False)
            partial = raw_partial if isinstance(raw_partial, bool) else True
            raw_failed = meta.get("failed", False)
            failed = raw_failed if isinstance(raw_failed, bool) else True
            raw_scope_id = meta.get("scope_id")
            scope_id = (
                raw_scope_id.strip()
                if isinstance(raw_scope_id, str) and raw_scope_id.strip() else None
            )
            raw_scope = meta.get("scope")
            scope = raw_scope if isinstance(raw_scope, dict) else None
        except (json.JSONDecodeError, OSError, ValueError):
            commit = None
            partial = True
    age = _artifacts.commits_between(repo_root, commit) if commit else None
    stale = age is None or age > max_age_commits or partial or failed
    return {
        "available": True, "reason": None,
        "source": "fresh" if fresh else "imported",
        "collected_at_commit": commit, "age_commits": age,
        "stale": stale, "modules": modules,
        "partial": partial, "failed": failed,
        "scope_id": scope_id, "scope": scope,
    }


def run(repo_root: Path, options) -> int:
    fresh = bool(getattr(options, "with_coverage", False))
    raw_age = getattr(options, "coverage_max_age", None)
    max_age = 15 if raw_age is None else int(raw_age)
    cov = collect_coverage(repo_root, fresh=fresh, max_age_commits=max_age)
    _artifacts.write_artifact(repo_root, "coverage", cov)
    if cov["available"]:
        notes = [n for n in ("partial run" if cov.get("partial") else None,
                             "failed run" if cov.get("failed") else None,
                             "stale" if cov["stale"] else None) if n]
        note = f" ({'; '.join(notes)})" if notes else ""
        print(f"coverage: {len(cov['modules'])} modules from {cov['source']} data{note}")
        return 0
    print(_artifacts.ascii_safe(f"coverage: unavailable - {cov['reason']}"))
    return 2
