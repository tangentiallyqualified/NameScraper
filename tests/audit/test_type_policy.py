from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from audit import _artifacts, _ratchets

REPO_ROOT = Path(__file__).resolve().parents[2]
PYRIGHT_VERSION = "1.1.411"
PYTHON_ROOTS = ["plex_renamer", "tests", "scripts"]
PYRIGHT_EXCLUDES = ["**/__pycache__", ".venv", ".worktrees", ".audit"]
STRICT_BOUNDARIES = [
    "plex_renamer/app/models",
    "plex_renamer/engine/_discovery_ports.py",
]


def _project() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyright_dependency_and_configuration_are_exact() -> None:
    dev_dependencies = _project()["project"]["optional-dependencies"]["dev"]
    constraints = {
        line.strip()
        for line in (REPO_ROOT / "scripts" / "audit" / "constraints.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    }
    config = json.loads((REPO_ROOT / "pyrightconfig.json").read_text(encoding="utf-8"))

    assert f"pyright>={PYRIGHT_VERSION}" in dev_dependencies
    assert f"pyright=={PYRIGHT_VERSION}" in constraints
    assert config == {
        "exclude": PYRIGHT_EXCLUDES,
        "extraPaths": ["."],
        "include": PYTHON_ROOTS,
        "pythonVersion": "3.11",
        "strict": STRICT_BOUNDARIES,
        "typeCheckingMode": "basic",
        "venv": ".venv",
        "venvPath": ".",
    }


def test_pyright_config_is_a_deterministic_audit_input(tmp_path: Path) -> None:
    config = tmp_path / "pyrightconfig.json"
    config.write_text("{}\n", encoding="utf-8")
    first = _artifacts.input_digest(tmp_path)

    config.write_text('{"typeCheckingMode":"basic"}\n', encoding="utf-8")

    assert _artifacts.input_digest(tmp_path) != first


def test_ci_runs_baseline_aware_quality_gate_not_raw_pyright() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    audit_job = workflow[workflow.index("  audit-verify:\n") :]

    assert "- name: Enforce quality ratchets" in audit_job
    assert "run: scripts/audit.cmd --quality-check\n" in audit_job
    assert audit_job.index("scripts/audit.cmd --quality-check") < audit_job.index(
        "scripts/audit.cmd --verify --with-coverage"
    )
    assert " -m pyright" not in workflow


def test_effective_pyright_config_is_explicitly_ignored() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".pyrightconfig.effective.json" in ignored


def test_initial_type_baseline_seeds_frozen_legacy_inventory() -> None:
    current = {
        "findings": [],
        "modules": {},
        "python_files": ["tests/test_z.py", r"plex_renamer\a.py"],
    }

    assert hasattr(_ratchets, "_bootstrap_quality_baseline_once")
    baseline = _ratchets._bootstrap_quality_baseline_once(current)

    assert baseline["schema_version"] == 2
    assert baseline["typing"] == {"legacy_python_files": ["plex_renamer/a.py", "tests/test_z.py"]}


def test_routine_baseline_build_requires_existing_baseline() -> None:
    current = {
        "findings": [],
        "modules": {},
        "python_files": ["plex_renamer/new.py"],
    }

    with pytest.raises(TypeError):
        _ratchets.build_baseline(current)


def test_type_baseline_regeneration_prunes_legacy_files_without_enrolling_new_ones() -> None:
    previous = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "typing": {
            "legacy_python_files": [
                "plex_renamer/kept.py",
                "plex_renamer/removed.py",
            ]
        },
    }
    current = {
        "findings": [],
        "modules": {},
        "python_files": ["plex_renamer/kept.py", "plex_renamer/new.py"],
    }

    regenerated = _ratchets.build_baseline(current, previous)

    assert regenerated["typing"] == {"legacy_python_files": ["plex_renamer/kept.py"]}


def test_removed_legacy_file_is_stale_until_baseline_is_pruned() -> None:
    baseline = {
        "schema_version": 2,
        "findings": [],
        "ceilings": {},
        "typing": {"legacy_python_files": ["plex_renamer/removed.py"]},
    }
    current = {"findings": [], "modules": {}, "python_files": []}

    assert _ratchets.evaluate_ratchets(current, baseline) == [
        {
            "analyzer": "pyright",
            "baseline": None,
            "current": None,
            "kind": "stale-baseline",
            "message": "legacy Python file is no longer present",
            "metric": None,
            "path": "plex_renamer/removed.py",
            "rule": "legacy-file",
            "symbol": None,
        }
    ]


def test_policy_pyright_adds_every_nonlegacy_module_to_effective_strict_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "plex_renamer" / "legacy.py"
    new_module = tmp_path / "scripts" / "new_module.py"
    legacy.parent.mkdir()
    new_module.parent.mkdir()
    legacy.write_text("value = 1\n", encoding="utf-8")
    new_module.write_text("def untyped(value):\n    return value\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps(
            {
                "exclude": PYRIGHT_EXCLUDES,
                "extraPaths": ["."],
                "include": PYTHON_ROOTS,
                "pythonVersion": "3.11",
                "strict": STRICT_BOUNDARIES,
                "typeCheckingMode": "basic",
                "venv": ".venv",
                "venvPath": ".",
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def completed(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        effective = json.loads(
            (tmp_path / ".pyrightconfig.effective.json").read_text(encoding="utf-8")
        )
        assert effective["strict"] == [
            "plex_renamer/app/models",
            "plex_renamer/engine/_discovery_ports.py",
            "scripts/new_module.py",
        ]
        assert effective["extraPaths"] == ["."]
        assert effective["venv"] == ".venv"
        assert effective["venvPath"] == "."
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(
                {
                    "generalDiagnostics": [
                        {
                            "file": str(new_module),
                            "severity": "error",
                            "message": "Type annotation is missing for parameter `value`",
                            "range": {
                                "start": {"line": 0, "character": 12},
                                "end": {"line": 0, "character": 17},
                            },
                            "rule": "reportMissingParameterType",
                        }
                    ],
                    "summary": {"errorCount": 1, "warningCount": 0},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(_ratchets.subprocess, "run", completed)

    findings = _ratchets._run_policy_pyright(
        tmp_path,
        ["plex_renamer/legacy.py", "scripts/new_module.py"],
        ["plex_renamer/legacy.py"],
    )

    assert commands == [
        [
            _ratchets.sys.executable,
            "-m",
            "pyright",
            "--outputjson",
            "--project",
            ".pyrightconfig.effective.json",
        ]
    ]
    assert findings == [
        {
            "allowlist_reason": None,
            "allowlisted": False,
            "category": "typing",
            "column": 13,
            "confidence": 100,
            "line": 1,
            "message": "Type annotation is missing for parameter `value`",
            "path": "scripts/new_module.py",
            "rule": "reportMissingParameterType",
            "source": "pyright",
            "symbol": (
                "scripts.new_module.untyped::reportMissingParameterType::"
                "Type annotation is missing for parameter `value`#1"
            ),
        }
    ]


def test_duplicate_pyright_diagnostics_keep_stable_multiplicity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scripts" / "sample.py"
    source.parent.mkdir()
    source.write_text("first = missing\nsecond = missing\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps({"include": ["scripts"], "strict": [], "typeCheckingMode": "basic"}),
        encoding="utf-8",
    )
    diagnostics = [
        {
            "file": str(source),
            "severity": "error",
            "message": '"missing" is not defined',
            "range": {
                "start": {"line": line, "character": 8},
                "end": {"line": line, "character": 15},
            },
            "rule": "reportUndefinedVariable",
        }
        for line in (0, 1)
    ]
    monkeypatch.setattr(
        _ratchets.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps({"generalDiagnostics": diagnostics}),
            stderr="",
        ),
    )

    findings = _ratchets._run_policy_pyright(tmp_path, ["scripts/sample.py"], [])

    assert [finding["symbol"] for finding in findings] == [
        'scripts.sample::reportUndefinedVariable::"missing" is not defined#1',
        'scripts.sample::reportUndefinedVariable::"missing" is not defined#2',
    ]


def test_pyright_json_is_decoded_as_strict_utf8_independent_of_host_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scripts" / "unicode_sample.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps({"include": ["scripts"], "strict": [], "typeCheckingMode": "basic"}),
        encoding="utf-8",
    )
    raw_output = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "error",
                    "message": "Type\u00a0\u00d7 caf\u00e9",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "rule": "reportUnicodeIdentity",
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def completed(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "strict"
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=raw_output.decode(kwargs["encoding"], errors=kwargs["errors"]),
            stderr="",
        )

    monkeypatch.setattr(_ratchets.subprocess, "run", completed)

    findings = _ratchets._run_policy_pyright(tmp_path, ["scripts/unicode_sample.py"], [])

    assert findings[0]["message"] == "Type \u00d7 caf\u00e9"
    assert findings[0]["symbol"] == (
        "scripts.unicode_sample::reportUnicodeIdentity::Type \u00d7 caf\u00e9#1"
    )
    assert "\u00c2" not in findings[0]["symbol"]
