from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from audit import _diff
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
    (tests / "test_direct.py").write_text("from PySide6.QtCore import QObject\n", encoding="utf-8")
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
    command = test_fast_runner._build_command(tmp_path, args, ["tests/test_current_qt.py"])

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


def test_main_success_writes_logs_and_prints_junit_summary(tmp_path: Path, monkeypatch, capsys):
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
    assert (log_dir / "latest.log").read_text(encoding="utf-8") == ("pytest stdout\n\nwarning\n")
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


def test_main_coverage_invokes_sidecar_with_result_and_passthrough(tmp_path: Path, monkeypatch):
    repo = _make_runner_repo(tmp_path)
    sidecars: list[tuple[Path, int, list[str], list[str]]] = []

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="1 failed\n", stderr="")

    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda root: [])
    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        test_fast_runner,
        "_write_coverage_sidecar",
        lambda root, code, pytest_args, qt_tests: sidecars.append(
            (root, code, pytest_args, qt_tests)
        ),
    )

    assert test_fast_runner.main(["--coverage", "-k", "focused"], repo) == 1
    assert sidecars == [(repo, 1, ["-k", "focused"], [])]


def test_coverage_scope_id_is_stable_and_methodology_sensitive(tmp_path: Path):
    repo = _make_runner_repo(tmp_path)
    qt_tests = ["tests/test_z_qt.py", "tests/test_a_qt.py"]

    test_fast_runner._write_coverage_sidecar(repo, 0, ["-k", "focused"], qt_tests)
    first = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    test_fast_runner._write_coverage_sidecar(repo, 0, ["-k", "focused"], list(reversed(qt_tests)))
    reordered = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    test_fast_runner._write_coverage_sidecar(repo, 0, ["-k", "other"], qt_tests)
    changed_args = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))

    assert first["scope"]["runner"] == "scripts/test_fast_runner.py"
    assert (
        first["scope"]["runner_sha256"]
        == hashlib.sha256(Path(test_fast_runner.__file__).read_bytes()).hexdigest()
    )
    assert first["scope"]["method"] == "ast-qt-exclusion-v1"
    assert first["scope"]["excluded_tests"] == [
        "tests/conftest_qt.py",
        "tests/test_a_qt.py",
        "tests/test_z_qt.py",
    ]
    assert first["scope"]["coverage_source"] == ["plex_renamer"]
    assert first["scope"]["config_files"] == []
    assert first["scope"]["pytest_args"] == ["-k", "focused"]
    assert len(first["scope_id"]) == 64
    assert first["scope_id"] == reordered["scope_id"]
    assert first["scope_id"] != changed_args["scope_id"]


def test_successful_unfiltered_coverage_records_full_suite_provenance(tmp_path: Path) -> None:
    repo = _make_runner_repo(tmp_path)

    test_fast_runner._write_coverage_sidecar(repo, 0, [], [])

    meta = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    assert meta["suite"] == "fast"
    assert meta["full_suite"] is True


def test_filtered_coverage_is_not_full_suite(tmp_path: Path) -> None:
    repo = _make_runner_repo(tmp_path)

    test_fast_runner._write_coverage_sidecar(repo, 0, ["-k", "focused"], [])

    meta = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    assert meta["suite"] == "fast"
    assert meta["full_suite"] is False


@pytest.mark.parametrize(
    ("config_path", "before", "after"),
    [
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\ntestpaths = ["tests/unit"]\n',
            '[tool.pytest.ini_options]\ntestpaths = ["tests/integration"]\n',
        ),
        ("pytest.ini", "[pytest]\naddopts = -k unit\n", "[pytest]\naddopts = -k integration\n"),
        (
            "setup.cfg",
            "[tool:pytest]\ntestpaths = tests/unit\n",
            "[tool:pytest]\ntestpaths = tests/integration\n",
        ),
        ("tox.ini", "[pytest]\naddopts = -k unit\n", "[pytest]\naddopts = -k integration\n"),
    ],
)
def test_automatic_pytest_config_changes_scope_and_suppresses_coverage_diff(
    tmp_path: Path, config_path: str, before: str, after: str
):
    repo = _make_runner_repo(tmp_path)
    config = repo / config_path
    config.write_text(before, encoding="utf-8")
    test_fast_runner._write_coverage_sidecar(repo, 0, [], [])
    first = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))

    config.write_text(after, encoding="utf-8")
    test_fast_runner._write_coverage_sidecar(repo, 0, [], [])
    second = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))

    assert first["scope_id"] != second["scope_id"]
    assert first["scope"]["config_files"][0]["path"] == config_path
    assert second["scope"]["config_files"][0]["path"] == config_path

    module = {
        "sha256": "same",
        "loc": 10,
        "max_complexity": 1,
        "coverage_percent": 10.0,
        "dead_candidates": 0,
    }
    baseline = {
        "modules": {"plex_renamer/alpha.py": module},
        "headline": {},
        "coverage": {"usable": True, "scope_id": first["scope_id"]},
    }
    current = {
        "modules": {
            "plex_renamer/alpha.py": {**module, "coverage_percent": 90.0},
        },
        "headline": {},
        "coverage": {"usable": True, "scope_id": second["scope_id"]},
    }

    movements = _diff.compare(baseline, current)["movements"]
    assert sum("coverage methodology changed" in item for item in movements) == 1
    assert not any("coverage 10.0 -> 90.0" in item for item in movements)


def test_scope_serialization_failure_overwrites_success_sidecar_and_fails_main(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _make_runner_repo(tmp_path)
    meta_path = repo / ".coverage.meta.json"
    meta_path.write_text(
        json.dumps({"failed": False, "partial": False, "scope_id": "stale-success"}),
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc1234\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="1 passed\n", stderr="")

    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda _root: [])
    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        test_fast_runner,
        "_coverage_scope",
        lambda *args, **kwargs: {"not_json_safe": object()},
    )

    assert test_fast_runner.main(["--coverage"], repo) == 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["failed"] is True
    assert meta["partial"] is True
    assert meta["scope"] is None
    assert meta["scope_id"] is None
    assert "coverage sidecar scope/write failed" in meta["reason"]
    assert meta["reason"].isascii()
    assert "stale-success" not in meta_path.read_text(encoding="utf-8")
    assert capsys.readouterr().err.isascii()


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


def test_syntax_error_is_left_for_pytest_and_invalidates_coverage_sidecar(
    tmp_path: Path, monkeypatch
):
    repo = _make_runner_repo(tmp_path)
    broken = repo / "tests" / "test_broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    pytest_commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc1234\n", stderr="")
        pytest_commands.append(command)
        return subprocess.CompletedProcess(
            command, 2, stdout="", stderr="SyntaxError while collecting test_broken.py"
        )

    monkeypatch.setattr(test_fast_runner.subprocess, "run", fake_run)

    assert test_fast_runner.main(["--coverage"], repo) == 2

    assert not any(part == "--ignore=tests/test_broken.py" for part in pytest_commands[0])
    meta = json.loads((repo / ".coverage.meta.json").read_text(encoding="utf-8"))
    assert meta["failed"] is True
    assert meta["partial"] is True
    assert "SyntaxError" in meta["reason"]
    assert meta["reason"].isascii()


def test_discovery_error_overwrites_successful_coverage_sidecar(
    tmp_path: Path, monkeypatch, capsys
):
    repo = _make_runner_repo(tmp_path)
    meta_path = repo / ".coverage.meta.json"
    meta_path.write_text(
        json.dumps({"failed": False, "partial": False, "scope_id": "stale-success"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        test_fast_runner,
        "_discover_qt_tests",
        lambda _root: (_ for _ in ()).throw(OSError("caf\u00e9 discovery failed")),
    )

    assert test_fast_runner.main(["--coverage"], repo) == 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["failed"] is True
    assert meta["partial"] is True
    assert meta["scope_id"] is None
    assert "caf? discovery failed" in meta["reason"]
    assert capsys.readouterr().err.isascii()


def test_launch_error_overwrites_successful_coverage_sidecar(tmp_path: Path, monkeypatch, capsys):
    repo = _make_runner_repo(tmp_path)
    meta_path = repo / ".coverage.meta.json"
    meta_path.write_text(
        json.dumps({"failed": False, "partial": False, "scope_id": "stale-success"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(test_fast_runner, "_discover_qt_tests", lambda _root: [])
    monkeypatch.setattr(
        test_fast_runner.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("caf\u00e9 executable unavailable")),
    )

    assert test_fast_runner.main(["--coverage"], repo) == 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["failed"] is True
    assert meta["partial"] is True
    assert "could not launch pytest: caf? executable unavailable" == meta["reason"]
    assert capsys.readouterr().err.isascii()
