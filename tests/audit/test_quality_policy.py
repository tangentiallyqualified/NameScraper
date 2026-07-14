from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_LINE_LENGTH = 100
EXPECTED_LINT_SELECT = ["E4", "E7", "E9", "F", "I", "UP", "B", "C4", "SIM", "PIE", "RUF"]
EXPECTED_PER_FILE_IGNORES = {
    "plex_renamer/gui_qt/**/*.py": ["B008", "RUF012"],
    "tests/**/*.py": ["RUF012"],
}
EXPECTED_PER_FILE_IGNORE_REASONS = {
    "plex_renamer/gui_qt/**/*.py": (
        "Qt override signatures legitimately use QModelIndex() defaults, and Qt model/signal "
        "class attributes trigger RUF012."
    ),
    "tests/**/*.py": "Test fakes intentionally use concise mutable class attributes.",
}


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_declares_exact_ruff_policy() -> None:
    ruff = _load_toml(REPO_ROOT / "pyproject.toml")["tool"]["ruff"]

    assert ruff["line-length"] == EXPECTED_LINE_LENGTH
    assert ruff["lint"]["select"] == EXPECTED_LINT_SELECT
    assert ruff["lint"]["per-file-ignores"] == EXPECTED_PER_FILE_IGNORES


def test_audit_policy_mirrors_ruff_policy_and_documents_exceptions() -> None:
    policy = _load_toml(REPO_ROOT / "scripts" / "audit" / "policy.toml")

    assert policy["schema_version"] == 1
    assert policy["format"]["line_length"] == EXPECTED_LINE_LENGTH
    assert policy["lint"]["select"] == EXPECTED_LINT_SELECT
    assert policy["lint"]["per_file_ignores"] == EXPECTED_PER_FILE_IGNORES
    assert policy["lint"]["per_file_ignore_reasons"] == EXPECTED_PER_FILE_IGNORE_REASONS
