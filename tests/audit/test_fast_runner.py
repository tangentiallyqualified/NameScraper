from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from scripts import test_fast_runner

# Pytest imports this file under the top-level ``test_fast_runner`` name because
# ``tests/audit`` is not a package.  Keep the existing coverage tests' top-level
# import compatible while exercising the implementation through its qualified
# namespace here.
_write_coverage_sidecar = test_fast_runner._write_coverage_sidecar


def _make_runner_repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    return tmp_path


def test_discovery_finds_direct_and_nested_qt_imports(tmp_path: Path):
    tests = tmp_path / "tests"
    nested = tests / "nested"
    nested.mkdir(parents=True)
    (tests / "test_direct.py").write_text(
        "from PySide6.QtCore import QObject\n", encoding="utf-8"
    )
    (nested / "test_nested.py").write_text(
        "def fixture():\n    from conftest_qt import QtSmokeBase\n",
        encoding="utf-8",
    )
    (tests / "test_module_import.py").write_text(
        "import PySide6.QtWidgets as widgets\n", encoding="utf-8"
    )
    (tests / "test_plain.py").write_text(
        "VALUE = 'PySide6 and conftest_qt are only text here'\n", encoding="utf-8"
    )
    (tests / "helper.py").write_text("import PySide6\n", encoding="utf-8")

    assert test_fast_runner._discover_qt_tests(tmp_path) == [
        "tests/nested/test_nested.py",
        "tests/test_direct.py",
        "tests/test_module_import.py",
    ]


def test_command_has_no_static_test_filename_manifest(tmp_path: Path):
    args = argparse.Namespace(coverage=False, verbose_pytest=False, pytest_args=[])
    command = test_fast_runner._build_command(
        tmp_path, args, ["tests/test_current_qt.py"]
    )

    ignores = [part for part in command if part.startswith("--ignore=")]
    assert ignores == [
        "--ignore=tests/test_current_qt.py",
        "--ignore=tests/conftest_qt.py",
    ]
    assert not any("test_qt_media_detail_panel.py" in part for part in command)


def test_parse_and_build_preserve_coverage_verbose_and_passthrough(tmp_path: Path):
    args = test_fast_runner._parse_args(
        ["--coverage", "--verbose-pytest", "tests/test_alpha.py", "-k", "focused"]
    )
    command = test_fast_runner._build_command(tmp_path, args, [])

    assert command[:7] == [
        str(tmp_path / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "coverage",
        "run",
        f"--data-file={tmp_path / '.coverage'}",
        "--source=plex_renamer",
        "-m",
    ]
    assert "-q" not in command
    assert command[-3:] == ["tests/test_alpha.py", "-k", "focused"]


def test_build_adds_quiet_by_default_and_sorts_discoveries(tmp_path: Path):
    args = argparse.Namespace(coverage=False, verbose_pytest=False, pytest_args=[])
    command = test_fast_runner._build_command(
        tmp_path, args, ["tests/test_z.py", "tests/test_a.py"]
    )

    assert command[1:3] == ["-m", "pytest"]
    assert command.index("--ignore=tests/test_a.py") < command.index("--ignore=tests/test_z.py")
    assert command[-1] == "-q"


def test_main_success_writes_logs_and_prints_junit_summary(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _make_runner_repo(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, *, cwd, **kwargs):
        calls.append((command, cwd))
        junit_arg = next(part for part in command if part.startswith("--junitxml="))
        junit_path = Path(junit_arg.split("=", 1)[1])
        junit_path.write_text(
            '<testsuite tests="3" failures="0" errors="0" skipped="1" time="1.25"/>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="pytest stdout\n", stderr="warning\n")

    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda root: [])
    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)

    assert test_fast_runner.main(repo_root=repo) == 0
    assert calls[0][1] == repo
    log_dir = repo / ".pytest_cache" / "fast"
    assert (log_dir / "latest.stdout.log").read_text(encoding="utf-8") == "pytest stdout\n"
    assert (log_dir / "latest.stderr.log").read_text(encoding="utf-8") == "warning\n"
    assert (log_dir / "latest.log").read_text(encoding="utf-8") == (
        "pytest stdout\n\nwarning\n"
    )
    output = capsys.readouterr().out
    assert "Fast test suite passed." in output
    assert "3 tests: 2 passed, 0 failed, 0 errors, 1 skipped in 1.25s" in output


def test_main_failure_returns_pytest_code_and_prints_recent_output(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _make_runner_repo(tmp_path)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 5, stdout="collected 0 items\n", stderr="no tests ran\n"
        )

    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda root: [])
    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)

    assert test_fast_runner.main(repo_root=repo) == 5
    output = capsys.readouterr().out
    assert "Fast test suite failed (exit code 5)." in output
    assert "Recent pytest output:" in output
    assert "no tests ran" in output


def test_main_coverage_invokes_sidecar_with_result_and_passthrough(
    tmp_path: Path, monkeypatch
):
    repo = _make_runner_repo(tmp_path)
    sidecars: list[tuple[Path, int, list[str]]] = []

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="1 failed\n", stderr="")

    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda root: [])
    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        test_fast_runner,
        "_write_coverage_sidecar",
        lambda root, code, pytest_args: sidecars.append((root, code, pytest_args)),
    )

    assert test_fast_runner.main(["--coverage", "-k", "focused"], repo) == 1
    assert sidecars == [(repo, 1, ["-k", "focused"])]


def test_main_without_coverage_does_not_write_sidecar(tmp_path: Path, monkeypatch):
    repo = _make_runner_repo(tmp_path)
    sidecar_called = False

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="1 passed\n", stderr="")

    def record_sidecar(*args):
        nonlocal sidecar_called
        sidecar_called = True

    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda root: [])
    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(test_fast_runner, "_write_coverage_sidecar", record_sidecar)

    assert test_fast_runner.main(repo_root=repo) == 0
    assert sidecar_called is False


def test_main_missing_environment_fails_before_discovery(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        test_fast_runner,
        "_discover_qt_tests",
        lambda root: (_ for _ in ()).throw(AssertionError("must not discover")),
    )

    assert test_fast_runner.main(repo_root=tmp_path) == 1
    assert "Python environment not found" in capsys.readouterr().err
