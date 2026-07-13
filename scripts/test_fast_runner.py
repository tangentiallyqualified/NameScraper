from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


_COVERAGE_SOURCE = ["plex_renamer"]
_COVERAGE_CONFIG_FILES = (".coveragerc", "setup.cfg", "tox.ini")
_DIAGNOSTIC_LIMIT = 400


class _DiscoveryResult(list[str]):
    def __init__(self, paths: list[str], errors: list[str]) -> None:
        super().__init__(paths)
        self.errors = errors


def _diagnostic_context(value: object) -> str:
    text = " ".join(str(value or "").split())
    return text.encode("ascii", "replace").decode("ascii")[:_DIAGNOSTIC_LIMIT]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the non-Qt (fast) test suite with concise reporting.")
    parser.add_argument("--verbose-pytest", action="store_true", help="Do not pass -q to pytest.")
    parser.add_argument("--coverage", action="store_true",
                        help="Run under coverage; writes .coverage and .coverage.meta.json at repo root.")
    args, args.pytest_args = parser.parse_known_args(argv)
    return args


def _imports_qt_support(test_path: Path) -> bool:
    """Return whether a test imports Qt or the repository's Qt fixture module."""
    tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "PySide6"
                or alias.name.startswith("PySide6.")
                or alias.name == "conftest_qt"
                or alias.name.endswith(".conftest_qt")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if (
                module == "PySide6"
                or module.startswith("PySide6.")
                or module == "conftest_qt"
                or module.endswith(".conftest_qt")
                or any(alias.name == "conftest_qt" for alias in node.names)
            ):
                return True
    return False


def _discover_qt_tests(repo_root: Path) -> list[str]:
    """Discover Qt-dependent test modules in stable repository-relative order."""
    tests_root = repo_root / "tests"
    discovered: list[str] = []
    errors: list[str] = []
    for path in tests_root.rglob("test_*.py"):
        relative = path.relative_to(repo_root).as_posix()
        try:
            imports_qt = _imports_qt_support(path)
        except (OSError, SyntaxError, UnicodeError) as exc:
            line = f":{exc.lineno}" if isinstance(exc, SyntaxError) and exc.lineno else ""
            errors.append(_diagnostic_context(
                f"{relative}{line}: {type(exc).__name__}: {exc}"
            ))
            continue  # Keep the file in pytest collection so pytest can report it.
        if imports_qt:
            discovered.append(relative)
    return _DiscoveryResult(sorted(discovered), errors)


def _build_command(
    repo_root: Path,
    args: argparse.Namespace,
    qt_tests: list[str],
) -> list[str]:
    """Build the pytest command without performing filesystem or process I/O."""
    python = repo_root / ".venv" / "Scripts" / "python.exe"
    junit_log = repo_root / ".pytest_cache" / "fast" / "latest.junit.xml"

    command = [str(python)]
    if args.coverage:
        command += ["-m", "coverage", "run", f"--data-file={repo_root / '.coverage'}",
                    "--source=plex_renamer"]
    command += ["-m", "pytest"]
    command += [f"--ignore={path}" for path in sorted(qt_tests)]
    command += [
        "--ignore=tests/conftest_qt.py",
        "--color=no",
        f"--junitxml={junit_log}",
    ]
    if not args.verbose_pytest:
        command.append("-q")
    command.extend(args.pytest_args)
    return command


def _write_logs(log_dir: Path, stdout: str, stderr: str) -> None:
    (log_dir / "latest.stdout.log").write_text(stdout, encoding="utf-8")
    (log_dir / "latest.stderr.log").write_text(stderr, encoding="utf-8")

    combined_parts = []
    if stdout:
        combined_parts.append(stdout.rstrip())
    if stderr:
        combined_parts.append(stderr.rstrip())
    (log_dir / "latest.log").write_text(
        "\n\n".join(combined_parts).strip() + ("\n" if combined_parts else ""),
        encoding="utf-8",
    )


def _parse_junit_summary(junit_path: Path) -> str | None:
    if not junit_path.exists():
        return None
    try:
        root = ET.fromstring(junit_path.read_text(encoding="utf-8"))
    except ET.ParseError:
        return None

    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        return None

    tests = int(suite.attrib.get("tests", 0))
    failures = int(suite.attrib.get("failures", 0))
    errors = int(suite.attrib.get("errors", 0))
    skipped = int(suite.attrib.get("skipped", 0))
    passed = tests - failures - errors - skipped
    duration = float(suite.attrib.get("time", 0.0))
    return f"{tests} tests: {passed} passed, {failures} failed, {errors} errors, {skipped} skipped in {duration:.2f}s"


def _fallback_summary(stdout: str, stderr: str) -> str | None:
    candidates = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    if not candidates:
        return None
    for line in reversed(candidates):
        lowered = line.lower()
        if any(token in lowered for token in (" passed", " failed", " skipped", " error", " deselected")):
            return line
    return candidates[-1]


def _coverage_config(repo_root: Path) -> list[dict]:
    """Return stable coverage configuration inputs that can affect collection."""
    config: list[dict] = []
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            settings = parsed.get("tool", {}).get("coverage")
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            settings = None
        if isinstance(settings, dict):
            config.append({"path": "pyproject.toml", "settings": settings})
    for relative in _COVERAGE_CONFIG_FILES:
        path = repo_root / relative
        if path.exists():
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = "unreadable"
            config.append({"path": relative, "sha256": digest})
    return config


def _coverage_scope(
    repo_root: Path,
    pytest_args: list[str],
    qt_tests: list[str],
) -> dict:
    return {
        "runner": "scripts/test_fast_runner.py",
        "method": "ast-qt-exclusion-v1",
        "excluded_tests": sorted(set(qt_tests) | {"tests/conftest_qt.py"}),
        "coverage_source": list(_COVERAGE_SOURCE),
        "coverage_config": _coverage_config(repo_root),
        "pytest_args": list(pytest_args),
    }


def _scope_id(scope: dict) -> str:
    canonical = json.dumps(
        scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _write_coverage_sidecar(
    repo_root: Path,
    returncode: int,
    pytest_args: list[str],
    qt_tests: list[str] | None = None,
    failure_reason: str | None = None,
) -> None:
    """Always write the .coverage.meta.json sidecar (never unlink it).

    A failed run's `.coverage` data is never full evidence, so `partial` is
    forced True regardless of pytest_args on failure. `failed` is additive
    honesty about the run outcome.
    """
    meta_path = repo_root / ".coverage.meta.json"
    commit = None
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root,
                              capture_output=True, text=True, timeout=15)
        commit = rev.stdout.strip() or None if rev.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        pass

    failed = returncode != 0
    partial = True if failed else bool(pytest_args)
    scope = _coverage_scope(repo_root, pytest_args, qt_tests) if qt_tests is not None else None

    meta_path.write_text(
        json.dumps({"commit": commit,
                     "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "pytest_args": pytest_args,
                     "scope": scope,
                     "scope_id": _scope_id(scope) if scope is not None else None,
                     "reason": _diagnostic_context(failure_reason) if failure_reason else None,
                     "partial": partial,
                     "failed": failed}),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None, repo_root: Path | None = None) -> int:
    args = _parse_args(argv)

    repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    python = repo_root / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        print(f"Python environment not found at {python}", file=sys.stderr)
        return 1

    log_dir = repo_root / ".pytest_cache" / "fast"
    log_dir.mkdir(parents=True, exist_ok=True)
    junit_log = log_dir / "latest.junit.xml"

    try:
        qt_tests = _discover_qt_tests(repo_root)
    except Exception as exc:
        reason = f"test discovery failed: {_diagnostic_context(exc)}"
        _write_logs(log_dir, "", reason + "\n")
        if args.coverage:
            _write_coverage_sidecar(
                repo_root, 1, args.pytest_args, None, failure_reason=reason
            )
        print(reason, file=sys.stderr)
        print("Log: .pytest_cache/fast/latest.log", file=sys.stderr)
        return 1
    command = _build_command(repo_root, args, qt_tests)

    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        reason = f"could not launch pytest: {_diagnostic_context(exc)}"
        _write_logs(log_dir, "", reason + "\n")
        if args.coverage:
            _write_coverage_sidecar(
                repo_root, 1, args.pytest_args, list(qt_tests), failure_reason=reason
            )
        print(reason, file=sys.stderr)
        print("Log: .pytest_cache/fast/latest.log", file=sys.stderr)
        return 1

    discovery_errors = list(getattr(qt_tests, "errors", []))
    discovery_reason = (
        "test discovery incomplete: " + "; ".join(discovery_errors)
        if discovery_errors else None
    )
    stderr = result.stderr
    if discovery_reason:
        stderr = stderr.rstrip() + ("\n" if stderr else "") + discovery_reason + "\n"
    _write_logs(log_dir, result.stdout, stderr)

    returncode = result.returncode or (1 if discovery_errors else 0)

    if args.coverage:
        if discovery_reason:
            _write_coverage_sidecar(
                repo_root, returncode, args.pytest_args, list(qt_tests),
                failure_reason=discovery_reason,
            )
        else:
            _write_coverage_sidecar(repo_root, returncode, args.pytest_args, qt_tests)

    summary = _parse_junit_summary(junit_log) or _fallback_summary(result.stdout, result.stderr)
    combined_nonempty = [line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()]

    if returncode == 0:
        print("Fast test suite passed.")
        if summary:
            print(summary)
        print("Log: .pytest_cache/fast/latest.log")
        return 0

    print(f"Fast test suite failed (exit code {returncode}).")
    if summary:
        print(summary)
    if combined_nonempty:
        print("Recent pytest output:")
        for line in combined_nonempty[-30:]:
            print(line)
    print("Log: .pytest_cache/fast/latest.log")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
