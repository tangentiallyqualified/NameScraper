"""Stage 4: coverage evidence - import newest .coverage data or run fresh."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import _artifacts


_FRESH_TIMEOUT_SECONDS = 1800
_DIAGNOSTIC_LIMIT = 400


class CoverageEvidenceError(RuntimeError):
    """Raised when coverage data cannot support a quality decision."""


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
        statement_lines = sorted(statements)
        missing_lines = set(missing)
        n = len(statements)
        covered = n - len(missing)
        modules[rel.as_posix()] = {
            "statements": n,
            "covered": covered,
            "percent": round(100.0 * covered / n, 1) if n else 100.0,
            "executable_lines": statement_lines,
            "covered_lines": [line for line in statement_lines if line not in missing_lines],
        }
    return modules


def _source_paths(repo_root: Path) -> list[Path]:
    source_root = repo_root / "plex_renamer"
    if not source_root.is_dir():
        return []
    return sorted(path for path in source_root.rglob("*.py") if path.is_file())


def _complete_source_modules(
    repo_root: Path, data_file: Path, modules: dict[str, dict]
) -> tuple[dict[str, dict], list[str], list[str]]:
    """Require measured data for executable source; synthesize only 0-line files."""
    import coverage

    completed = dict(modules)
    incomplete = []
    source_packages = set()
    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()
    for path in _source_paths(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        source_packages.add(_package_name(relative))
        if relative in completed:
            continue
        _, statements, _, _, _ = cov.analysis2(str(path))
        if statements:
            incomplete.append(relative)
            continue
        completed[relative] = {
            "statements": 0,
            "covered": 0,
            "percent": 100.0,
            "executable_lines": [],
            "covered_lines": [],
        }
    return (
        {path: completed[path] for path in sorted(completed)},
        sorted(incomplete),
        sorted(source_packages),
    )


def _canonical_scope_id(scope: dict) -> str:
    canonical = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    return hashlib.sha256(canonical).hexdigest()


def _expected_fast_scope(repo_root: Path) -> dict:
    from scripts import test_fast_runner

    qt_tests = test_fast_runner._discover_qt_tests(repo_root)
    errors = list(getattr(qt_tests, "errors", []))
    if errors:
        raise CoverageEvidenceError(
            "coverage-scope-incomplete: test discovery errors: " + "; ".join(errors)
        )
    return test_fast_runner._coverage_scope(repo_root, [], list(qt_tests))


def _validate_full_suite_scope(repo_root: Path, evidence: dict) -> None:
    scope = evidence.get("scope")
    scope_id = evidence.get("scope_id")
    if evidence.get("suite") != "fast":
        raise CoverageEvidenceError("coverage-scope-incomplete: expected suite 'fast'")
    if not isinstance(scope, dict):
        raise CoverageEvidenceError("coverage-scope-incomplete: scope object missing")
    if not isinstance(scope_id, str) or scope_id != _canonical_scope_id(scope):
        raise CoverageEvidenceError("coverage-scope-incomplete: scope_id mismatch")
    expected = _expected_fast_scope(repo_root)
    if scope != expected:
        raise CoverageEvidenceError(
            "coverage-scope-incomplete: scope does not match the unfiltered fast suite"
        )


def _fingerprinted_executable_lines(
    repo_root: Path, path: str, module: dict
) -> list[dict[str, object]]:
    source_lines = (repo_root / path).read_text(encoding="utf-8").splitlines()
    covered_lines = set(module.get("covered_lines", []))
    occurrences: dict[str, int] = {}
    result = []
    for line_number in module.get("executable_lines", []):
        line_text = source_lines[line_number - 1]
        digest = hashlib.sha256(line_text.encode("utf-8")).hexdigest()
        occurrence = occurrences.get(digest, 0) + 1
        occurrences[digest] = occurrence
        result.append(
            {
                "fingerprint": f"sha256:{digest}#{occurrence}",
                "covered": line_number in covered_lines,
            }
        )
    return result


def _package_name(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return parent if parent != "." else Path(path).stem


def _package_floors(modules: dict[str, dict]) -> dict[str, dict[str, int | float]]:
    totals: dict[str, dict[str, int]] = {}
    for path, module in sorted(modules.items()):
        package = _package_name(path)
        aggregate = totals.setdefault(package, {"covered": 0, "statements": 0})
        aggregate["covered"] += int(module.get("covered", 0))
        aggregate["statements"] += int(module.get("statements", 0))
    return {
        package: {
            **counts,
            "percent": round(100.0 * counts["covered"] / counts["statements"], 1)
            if counts["statements"]
            else 100.0,
        }
        for package, counts in sorted(totals.items())
    }


def collect_quality_coverage(repo_root: Path) -> dict:
    """Return digest-matched, full-suite statement evidence for quality gates."""
    evidence = collect_coverage(repo_root)
    if not evidence["available"]:
        raise CoverageEvidenceError(f"missing coverage evidence: {evidence['reason']}")
    if evidence.get("failed"):
        raise CoverageEvidenceError("failed coverage evidence")
    if evidence.get("partial"):
        raise CoverageEvidenceError("partial coverage evidence")
    if evidence.get("input_digest") != _artifacts.input_digest(repo_root):
        raise CoverageEvidenceError("coverage evidence input digest mismatch")
    if evidence.get("full_suite") is not True:
        raise CoverageEvidenceError("coverage evidence is not a full-suite run")
    _validate_full_suite_scope(repo_root, evidence)
    incomplete = evidence.get("scope_incomplete")
    if not isinstance(incomplete, list) or incomplete:
        paths = ", ".join(str(path) for path in incomplete or [])
        detail = f": executable source not measured: {paths}" if paths else ""
        raise CoverageEvidenceError(f"coverage-scope-incomplete{detail}")
    modules = evidence["modules"]
    return {
        "input_digest": evidence["input_digest"],
        "suite": evidence.get("suite"),
        "full_suite": True,
        "scope_id": evidence.get("scope_id"),
        "scope": evidence.get("scope"),
        "modules": modules,
        "source_packages": evidence["source_packages"],
        "files": {
            path: {"executable_lines": _fingerprinted_executable_lines(repo_root, path, module)}
            for path, module in sorted(modules.items())
        },
        "package_floors": _package_floors(modules),
    }


def _percent(covered: int, statements: int) -> float:
    return round(100.0 * covered / statements, 1) if statements else 100.0


def evaluate_quality_coverage(
    current: dict, baseline: dict, changed_line_min_percent: float
) -> dict:
    """Compare current full-suite line evidence with a path-local snapshot."""
    baseline_lines = baseline.get("executable_lines", {})
    changed = []
    for path, file_evidence in sorted(current.get("files", {}).items()):
        known = set(baseline_lines.get(path, []))
        changed.extend(
            line
            for line in file_evidence.get("executable_lines", [])
            if line.get("fingerprint") not in known
        )
    changed_statements = len(changed)
    changed_covered = sum(line.get("covered") is True for line in changed)
    changed_percent = _percent(changed_covered, changed_statements)
    violations = []
    if changed_statements and changed_covered * 100 < changed_line_min_percent * changed_statements:
        violations.append(
            {
                "baseline": changed_line_min_percent,
                "current": changed_percent,
                "kind": "changed-line-coverage",
                "path": "plex_renamer",
            }
        )

    current_floors = current.get("package_floors", {})
    raw_source_packages = current.get("source_packages")
    source_packages = set(raw_source_packages) if isinstance(raw_source_packages, list) else None
    for package, baseline_floor in sorted(baseline.get("package_floors", {}).items()):
        current_floor = current_floors.get(package)
        if not isinstance(current_floor, dict):
            if source_packages is None or package in source_packages:
                violations.append(
                    {
                        "baseline": _percent(
                            int(baseline_floor.get("covered", 0)),
                            int(baseline_floor.get("statements", 0)),
                        ),
                        "current": None,
                        "kind": "coverage-scope-incomplete",
                        "path": package,
                    }
                )
            continue
        baseline_covered = int(baseline_floor.get("covered", 0))
        baseline_statements = int(baseline_floor.get("statements", 0))
        current_covered = int(current_floor.get("covered", 0))
        current_statements = int(current_floor.get("statements", 0))
        if current_covered * baseline_statements < baseline_covered * current_statements:
            violations.append(
                {
                    "baseline": _percent(baseline_covered, baseline_statements),
                    "current": _percent(current_covered, current_statements),
                    "kind": "package-floor-decrease",
                    "path": package,
                }
            )
    return {
        "changed_lines": {
            "covered": changed_covered,
            "statements": changed_statements,
            "percent": changed_percent,
        },
        "violations": violations,
    }


def build_quality_baseline(current: dict, changed_line_min_percent: float) -> dict:
    """Strip run-specific line results into deterministic committed coverage policy."""
    return {
        "changed_line_min_percent": changed_line_min_percent,
        "executable_lines": {
            path: [str(line["fingerprint"]) for line in file_evidence.get("executable_lines", [])]
            for path, file_evidence in sorted(current.get("files", {}).items())
        },
        "full_suite": True,
        "package_floors": {
            package: dict(floor)
            for package, floor in sorted(current.get("package_floors", {}).items())
        },
        "scope_id": current.get("scope_id"),
        "suite": current.get("suite"),
    }


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
        raise RuntimeError(f"fresh coverage run failed (exit {result.returncode}){detail}")


def collect_coverage(repo_root: Path, fresh: bool = False, max_age_commits: int = 15) -> dict:
    unavailable = {
        "available": False,
        "reason": None,
        "source": None,
        "input_digest": None,
        "collected_at_commit": None,
        "age_commits": None,
        "stale": False,
        "modules": {},
        "partial": False,
        "failed": False,
        "scope_id": None,
        "scope": None,
        "suite": None,
        "full_suite": False,
        "scope_incomplete": [],
        "source_packages": [],
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
        return {
            **unavailable,
            "reason": "no .coverage data file; run scripts\\test-fast.cmd -Coverage",
        }

    try:
        modules = _read_modules(repo_root, data_file)
        modules, scope_incomplete, source_packages = _complete_source_modules(
            repo_root, data_file, modules
        )
    except Exception as exc:
        return {**unavailable, "reason": f"could not read coverage data: {exc}"[:200]}

    commit = None
    collected_input_digest = None
    partial = False
    failed = False
    scope_id = None
    scope = None
    suite = None
    full_suite = False
    meta_file = repo_root / ".coverage.meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                raise ValueError("coverage metadata must be a JSON object")
            raw_commit = meta.get("commit")
            commit = (
                raw_commit.strip() if isinstance(raw_commit, str) and raw_commit.strip() else None
            )
            raw_input_digest = meta.get("input_digest")
            collected_input_digest = (
                raw_input_digest.strip()
                if isinstance(raw_input_digest, str) and raw_input_digest.strip()
                else None
            )
            raw_partial = meta.get("partial", False)
            partial = raw_partial if isinstance(raw_partial, bool) else True
            raw_failed = meta.get("failed", False)
            failed = raw_failed if isinstance(raw_failed, bool) else True
            raw_scope_id = meta.get("scope_id")
            scope_id = (
                raw_scope_id.strip()
                if isinstance(raw_scope_id, str) and raw_scope_id.strip()
                else None
            )
            raw_scope = meta.get("scope")
            scope = raw_scope if isinstance(raw_scope, dict) else None
            raw_suite = meta.get("suite")
            suite = raw_suite.strip() if isinstance(raw_suite, str) else None
            raw_full_suite = meta.get("full_suite", False)
            full_suite = raw_full_suite if isinstance(raw_full_suite, bool) else False
        except (json.JSONDecodeError, OSError, ValueError):
            commit = None
            collected_input_digest = None
            partial = True
    age = _artifacts.commits_between(repo_root, commit) if commit else None
    current_input_digest = _artifacts.input_digest(repo_root)
    stale = collected_input_digest != current_input_digest or partial or failed
    return {
        "available": True,
        "reason": None,
        "source": "fresh" if fresh else "imported",
        "input_digest": collected_input_digest,
        "collected_at_commit": commit,
        "age_commits": age,
        "stale": stale,
        "modules": modules,
        "partial": partial,
        "failed": failed,
        "scope_id": scope_id,
        "scope": scope,
        "suite": suite,
        "full_suite": full_suite,
        "scope_incomplete": scope_incomplete,
        "source_packages": source_packages,
    }


def run(repo_root: Path, options) -> int:
    fresh = bool(getattr(options, "with_coverage", False))
    raw_age = getattr(options, "coverage_max_age", None)
    max_age = 15 if raw_age is None else int(raw_age)
    cov = collect_coverage(repo_root, fresh=fresh, max_age_commits=max_age)
    _artifacts.write_artifact(repo_root, "coverage", cov)
    if cov["available"]:
        notes = [
            n
            for n in (
                "partial run" if cov.get("partial") else None,
                "failed run" if cov.get("failed") else None,
                "stale" if cov["stale"] else None,
            )
            if n
        ]
        note = f" ({'; '.join(notes)})" if notes else ""
        print(f"coverage: {len(cov['modules'])} modules from {cov['source']} data{note}")
        return 0
    print(_artifacts.ascii_safe(f"coverage: unavailable - {cov['reason']}"))
    return 2
