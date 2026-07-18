from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts.audit import __main__ as cli, _artifacts, _decisions, _ratchets

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_LINE_LENGTH = 100
EXPECTED_LINT_SELECT = ["E4", "E7", "E9", "F", "I", "UP", "B", "C4", "SIM", "PIE", "RUF"]
EXPECTED_PER_FILE_IGNORES = {
    "plex_renamer/gui_qt/**/*.py": ["B008", "RUF012"],
    "tests/**/*.py": ["RUF012"],
}
EXPECTED_EXCEPTIONS = [
    {
        "target": "plex_renamer/gui_qt/**/*.py",
        "rule": "B008",
        "reason_code": "framework-callback",
        "reason": (
            "Qt override signatures legitimately use QModelIndex() default arguments required "
            "by the framework."
        ),
    },
    {
        "target": "plex_renamer/gui_qt/**/*.py",
        "rule": "RUF012",
        "reason_code": "framework-callback",
        "reason": (
            "Qt signal and model class attributes are framework-managed descriptors, not "
            "mutable instance state."
        ),
    },
    {
        "target": "tests/**/*.py",
        "rule": "RUF012",
        "reason_code": "test-seam",
        "reason": "Test fakes intentionally use concise mutable class attributes as a test seam.",
    },
]


def test_formatter_ratchet_distinguishes_new_changed_and_resolved_debt() -> None:
    baseline = {
        "findings": [],
        "ceilings": {},
        "complexity": {},
        "formatting": {"legacy.py": "sha256:original"},
    }
    unchanged = {"findings": [], "modules": {}, "formatting": {"legacy.py": "sha256:original"}}
    changed = {"findings": [], "modules": {}, "formatting": {"legacy.py": "sha256:changed"}}
    added = {
        "findings": [],
        "modules": {},
        "formatting": {"legacy.py": "sha256:original", "new.py": "sha256:new"},
    }
    resolved = {"findings": [], "modules": {}, "formatting": {}}

    assert _ratchets.evaluate_ratchets(unchanged, baseline) == []
    assert [
        (item["kind"], item["path"]) for item in _ratchets.evaluate_ratchets(changed, baseline)
    ] == [("enlarged-debt", "legacy.py")]
    assert [
        (item["kind"], item["path"]) for item in _ratchets.evaluate_ratchets(added, baseline)
    ] == [("new-debt", "new.py")]
    assert [item["kind"] for item in _ratchets.evaluate_ratchets(resolved, baseline)] == [
        "stale-baseline"
    ]


def test_formatter_evidence_uses_exit_status_and_raw_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    formatted = tmp_path / "formatted.py"
    unformatted = tmp_path / "unformatted.py"
    formatted.write_text("value = 1\n", encoding="utf-8")
    unformatted.write_text("value=1\n", encoding="utf-8")

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1 if command[-1] == "unformatted.py" else 0, stdout="", stderr=""
        )

    monkeypatch.setattr(_ratchets._quality_static.subprocess, "run", run)
    evidence = _ratchets._run_policy_format(tmp_path, ["formatted.py", "unformatted.py"])

    digest = _ratchets._quality_static.hashlib.sha256(unformatted.read_bytes()).hexdigest()
    assert evidence == {"unformatted.py": f"sha256:{digest}"}


def test_complexity_collection_qualifies_scopes_and_accepts_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "scopes.py"
    branches = "\n".join(f"    if value == {number}:\n        value += 1" for number in range(10))
    source.write_text(f"def work(value):\n{branches}\n    return value\n", encoding="utf-8")
    bom = tmp_path / "bom_source.py"
    bom.write_bytes(b"\xef\xbb\xbfdef work():\n    return 1\n")

    complexity = _ratchets._quality_complexity(
        tmp_path, [{"path": "scopes.py", "loc": 22}, {"path": "bom_source.py", "loc": 2}]
    )

    assert complexity == {
        "scopes.py": {"scopes.work": 11},
        "bom_source.py": {"bom_source.work": 1},
    }


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_declares_exact_ruff_policy() -> None:
    ruff = _load_toml(REPO_ROOT / "pyproject.toml")["tool"]["ruff"]

    assert ruff["line-length"] == EXPECTED_LINE_LENGTH
    assert ruff["lint"]["select"] == EXPECTED_LINT_SELECT
    assert ruff["lint"]["per-file-ignores"] == EXPECTED_PER_FILE_IGNORES


def test_audit_policy_mirrors_ruff_policy_with_structured_exceptions() -> None:
    policy = _load_toml(REPO_ROOT / "scripts" / "audit" / "policy.toml")

    assert policy["schema_version"] == 1
    assert policy["format"]["line_length"] == EXPECTED_LINE_LENGTH
    assert policy["lint"]["select"] == EXPECTED_LINT_SELECT
    assert policy["lint"]["exceptions"] == EXPECTED_EXCEPTIONS


def test_policy_ruff_decodes_json_as_strict_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "plex_renamer" / "sample.py"
    source.parent.mkdir()
    multiplication_sign = "\N{MULTIPLICATION SIGN}"
    source.write_text(f"# {multiplication_sign}\n", encoding="utf-8")
    message = f"Comment contains ambiguous {multiplication_sign} (MULTIPLICATION SIGN)."
    payload = [
        {
            "code": "RUF003",
            "filename": str(source),
            "location": {"row": 1, "column": 5},
            "end_location": {"row": 1, "column": 10},
            "message": message,
            "name": "ambiguous-unicode-character-comment",
        }
    ]
    captured: dict = {}

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(_ratchets.subprocess, "run", fake_run)

    findings = _ratchets._run_policy_ruff(tmp_path)

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "strict"
    assert findings[0]["message"] == message
    assert findings[0]["symbol"] == (
        "plex_renamer.sample::ambiguous-unicode-character-comment::"
        f"Comment contains ambiguous {multiplication_sign} (MULTIPLICATION SIGN).#1"
    )


def _decision_policy(**overrides: str) -> str:
    values = {
        "analyzer": "vulture",
        "rule": "unused-method",
        "path": "plex_renamer/gui.py",
        "symbol": "plex_renamer.gui.Window.paintEvent#1",
        "reason_code": "framework-callback",
        "reason": "Qt invokes this QWidget override.",
    }
    values.update(overrides)
    return "[[decision]]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in values.items()
    )


def _write_decisions(repo: Path, text: str) -> None:
    path = repo / "scripts" / "audit" / "decisions.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_quality_collection_excludes_an_exact_decision(
    synthetic_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_decisions(
        synthetic_repo,
        _decision_policy(
            rule="unused-function",
            path="plex_renamer/alpha.py",
            symbol="plex_renamer.alpha.dead_function#1",
            reason_code="accepted-debt",
            reason="Synthetic fixture debt.",
        ),
    )
    monkeypatch.setattr(_ratchets, "_run_policy_ruff", lambda _root: [])
    monkeypatch.setattr(
        _ratchets,
        "_run_policy_pyright",
        lambda _root, _python_files, _legacy_python_files: [],
    )

    current = _ratchets.collect_current(synthetic_repo)

    assert not any(
        finding["symbol"] == "plex_renamer.alpha.dead_function#1" for finding in current["findings"]
    )


def test_quality_collection_rejects_a_stale_repo_decision(
    synthetic_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_decisions(
        synthetic_repo,
        _decision_policy(symbol="plex_renamer.gui.Missing.paintEvent#1"),
    )
    monkeypatch.setattr(_ratchets, "_run_policy_ruff", lambda _root: [])
    monkeypatch.setattr(
        _ratchets,
        "_run_policy_pyright",
        lambda _root, _python_files, _legacy_python_files: [],
    )

    with pytest.raises(_decisions.DecisionPolicyError, match="stale decision"):
        _ratchets.collect_current(synthetic_repo)


def test_repository_python_records_excludes_git_untracked_files(
    synthetic_repo: Path,
) -> None:
    untracked = synthetic_repo / "plex_renamer" / "untracked.py"
    untracked.write_text("VALUE = 1\n", encoding="utf-8")

    records = _ratchets._repository_python_records(synthetic_repo)
    paths = {record["path"] for record in records}

    assert "plex_renamer/alpha.py" in paths
    assert "plex_renamer/untracked.py" not in paths


def test_untracked_python_findings_are_filtered_out() -> None:
    tracked = {"scripts/tracked.py"}

    assert _ratchets._is_untracked_quality_python("scripts/untracked.py", tracked)
    assert not _ratchets._is_untracked_quality_python("scripts/tracked.py", tracked)
    assert not _ratchets._is_untracked_quality_python("scripts\\tracked.py", tracked)
    assert not _ratchets._is_untracked_quality_python("docs/guide.md", tracked)
    assert not _ratchets._is_untracked_quality_python("", tracked)


def test_findings_stage_writes_rich_review_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = [
        {
            "analyzer": "vulture",
            "rule": "unused-method",
            "path": "plex_renamer/gui.py",
            "symbol": "plex_renamer.gui.Window.paintEvent#1",
            "decision": None,
            "allowlisted": False,
        }
    ]
    monkeypatch.setattr(
        cli,
        "_collect_review_findings",
        lambda _root: review,
    )

    assert cli._run_findings(tmp_path, None) == 0
    assert _artifacts.read_artifact(tmp_path, "findings")["findings"] == review
