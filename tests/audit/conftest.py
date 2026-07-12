from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=audit-test", "-c", "user.email=audit@test", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """Git-initialized mini repo shaped like this project: package named
    plex_renamer with one dead function, one unused import, an import edge,
    a test file, and a doc with one live and one broken source reference."""
    pkg = tmp_path / "plex_renamer"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Mini package."""\n', encoding="utf-8")
    (pkg / "alpha.py").write_text(textwrap.dedent('''\
        """Alpha module: scoring helpers."""
        import json


        def used_function(value: int) -> int:
            """Double a value."""
            return value * 2


        def dead_function() -> None:
            """Never called by anything."""
            print("never runs")
    '''), encoding="utf-8")
    (pkg / "beta.py").write_text(textwrap.dedent('''\
        """Beta module: consumes alpha."""
        from plex_renamer.alpha import used_function


        def run() -> int:
            """Entry point."""
            return used_function(21)
    '''), encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_alpha.py").write_text(textwrap.dedent('''\
        from plex_renamer.alpha import used_function


        def test_used_function():
            assert used_function(2) == 4
    '''), encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text(
        "# Guide\nSee plex_renamer/alpha.py and plex_renamer/gone.py.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Mini\n", encoding="utf-8")
    git(tmp_path, "init")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


@pytest.fixture
def repo_git():
    """Expose the git() helper to tests (tests/ is not a package, so no
    `from tests.audit.conftest import ...` — use this fixture instead)."""
    return git
