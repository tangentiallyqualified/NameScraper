from __future__ import annotations

from pathlib import Path

import pytest

from audit import _verify


def _seed_generated_tree(repo_root: Path) -> None:
    audit_dir = repo_root / "docs" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "baseline.json").write_bytes(b'{"before": true}\n')
    (audit_dir / "findings-review.md").write_bytes(b"curated\r\nbytes\xff")
    (audit_dir / "doc-ledger.toml").write_bytes(b"documents = []\n")


def _tree_bytes(repo_root: Path) -> dict[str, bytes]:
    audit_dir = repo_root / "docs" / "audit"
    return {
        path.relative_to(repo_root).as_posix(): path.read_bytes()
        for path in audit_dir.rglob("*")
        if path.is_file()
    }


def test_snapshot_excludes_policy_input(tmp_path: Path):
    _seed_generated_tree(tmp_path)

    snapshot = _verify.snapshot_generated(tmp_path)

    assert sorted(snapshot) == [
        "docs/audit/baseline.json",
        "docs/audit/findings-review.md",
    ]


def test_verify_reports_unchanged_output_and_restores_original_bytes(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    before = _tree_bytes(tmp_path)

    result = _verify.verify(tmp_path, lambda: 0)

    assert result == (0, [])
    assert _tree_bytes(tmp_path) == before


def test_verify_reports_modified_output_and_restores_original_bytes(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    before = _tree_bytes(tmp_path)

    def run_pipeline() -> int:
        (tmp_path / "docs" / "audit" / "baseline.json").write_bytes(b"changed\n")
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (0, ["docs/audit/baseline.json"])
    assert _tree_bytes(tmp_path) == before


def test_verify_reports_new_output_and_removes_new_empty_directories(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    before = _tree_bytes(tmp_path)

    def run_pipeline() -> int:
        generated = tmp_path / "docs" / "audit" / "new" / "nested" / "map.md"
        generated.parent.mkdir(parents=True)
        generated.write_bytes(b"new\n")
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (0, ["docs/audit/new/nested/map.md"])
    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "docs" / "audit" / "new").exists()


def test_verify_reports_deleted_output_and_recreates_original_bytes(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    before = _tree_bytes(tmp_path)

    def run_pipeline() -> int:
        (tmp_path / "docs" / "audit" / "findings-review.md").unlink()
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (0, ["docs/audit/findings-review.md"])
    assert _tree_bytes(tmp_path) == before


def test_verify_restores_original_tree_when_pipeline_raises(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    before = _tree_bytes(tmp_path)

    def run_pipeline() -> int:
        audit_dir = tmp_path / "docs" / "audit"
        (audit_dir / "baseline.json").write_bytes(b"changed before failure\n")
        (audit_dir / "findings-review.md").unlink()
        new_file = audit_dir / "temporary" / "partial.md"
        new_file.parent.mkdir()
        new_file.write_bytes(b"partial\n")
        raise RuntimeError("pipeline exploded")

    with pytest.raises(RuntimeError, match="pipeline exploded"):
        _verify.verify(tmp_path, run_pipeline)

    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "docs" / "audit" / "temporary").exists()


def test_verify_restores_original_tree_after_nonzero_pipeline_return(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    before = _tree_bytes(tmp_path)

    def run_pipeline() -> int:
        (tmp_path / "docs" / "audit" / "baseline.json").write_bytes(b"partial\n")
        return 2

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (2, ["docs/audit/baseline.json"])
    assert _tree_bytes(tmp_path) == before
