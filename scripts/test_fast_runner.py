from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the non-Qt (fast) test suite with concise reporting.")
    parser.add_argument("--verbose-pytest", action="store_true", help="Do not pass -q to pytest.")
    parser.add_argument("pytest_args", nargs="*", help="Additional arguments forwarded to pytest.")
    return parser.parse_args()


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


def main() -> int:
    args = _parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    python = repo_root / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        print(f"Python environment not found at {python}", file=sys.stderr)
        return 1

    log_dir = repo_root / ".pytest_cache" / "fast"
    log_dir.mkdir(parents=True, exist_ok=True)
    junit_log = log_dir / "latest.junit.xml"

    command = [
        str(python),
        "-m",
        "pytest",
        "--ignore=tests/test_qt_main_window.py",
        "--ignore=tests/test_qt_job_detail_panel.py",
        "--ignore=tests/test_qt_media_detail_panel.py",
        "--ignore=tests/test_qt_media_workspace.py",
        "--ignore=tests/test_qt_queue_history.py",
        "--ignore=tests/conftest_qt.py",
        "--color=no",
        f"--junitxml={junit_log}",
    ]
    if not args.verbose_pytest:
        command.append("-q")
    command.extend(args.pytest_args)

    result = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    _write_logs(log_dir, result.stdout, result.stderr)

    summary = _parse_junit_summary(junit_log) or _fallback_summary(result.stdout, result.stderr)
    combined_nonempty = [line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()]

    if result.returncode == 0:
        print("Fast test suite passed.")
        if summary:
            print(summary)
        print("Log: .pytest_cache/fast/latest.log")
        return 0

    print(f"Fast test suite failed (exit code {result.returncode}).")
    if summary:
        print(summary)
    if combined_nonempty:
        print("Recent pytest output:")
        for line in combined_nonempty[-30:]:
            print(line)
    print("Log: .pytest_cache/fast/latest.log")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
