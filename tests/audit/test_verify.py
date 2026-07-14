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


def _require_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "symlink-capability-target"
    target.write_bytes(b"target\n")
    probe = tmp_path / "symlink-capability-probe"
    try:
        probe.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable on this platform: {exc}")
    else:
        probe.unlink()


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


def test_verify_restores_regular_file_replaced_by_directory(tmp_path: Path):
    _seed_generated_tree(tmp_path)
    baseline = tmp_path / "docs" / "audit" / "baseline.json"
    original = baseline.read_bytes()

    def run_pipeline() -> int:
        baseline.unlink()
        baseline.mkdir()
        (baseline / "partial.md").write_bytes(b"partial\n")
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (
        0,
        ["docs/audit/baseline.json", "docs/audit/baseline.json/partial.md"],
    )
    assert baseline.is_file()
    assert baseline.read_bytes() == original


def test_verify_restores_regular_file_replaced_by_symlink_without_touching_target(
    tmp_path: Path,
):
    _require_symlinks(tmp_path)
    _seed_generated_tree(tmp_path)
    baseline = tmp_path / "docs" / "audit" / "baseline.json"
    original = baseline.read_bytes()
    outside = tmp_path / "outside-target.json"
    outside.write_bytes(b"outside stays unchanged\n")

    def run_pipeline() -> int:
        baseline.unlink()
        baseline.symlink_to(outside)
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (0, ["docs/audit/baseline.json"])
    assert not baseline.is_symlink()
    assert baseline.read_bytes() == original
    assert outside.read_bytes() == b"outside stays unchanged\n"


def test_verify_removes_new_broken_symlink_without_following_it(tmp_path: Path):
    _require_symlinks(tmp_path)
    _seed_generated_tree(tmp_path)
    generated_link = tmp_path / "docs" / "audit" / "new-link.md"

    def run_pipeline() -> int:
        generated_link.symlink_to(tmp_path / "missing-outside-target")
        return 0

    _verify.verify(tmp_path, run_pipeline)

    assert not generated_link.is_symlink()
    assert not generated_link.exists()


@pytest.mark.parametrize(
    "relative",
    [
        "docs/audit/../../outside.bin",
        "docs/audit/maps/../baseline.json",
        r"docs/audit/..\..\outside.bin",
        r"docs/audit/nested\..\..\outside.bin",
        "docs\\audit\\baseline.json",
        "docs/not-audit/file.md",
        "docs/audit",
        "docs/audit/doc-ledger.toml",
    ],
)
def test_restore_rejects_non_normalized_or_out_of_scope_snapshot_keys_before_mutation(
    tmp_path: Path, relative: str
):
    _seed_generated_tree(tmp_path)
    baseline = tmp_path / "docs" / "audit" / "baseline.json"
    ledger = tmp_path / "docs" / "audit" / "doc-ledger.toml"
    outside = tmp_path / "outside.bin"
    before = (baseline.read_bytes(), ledger.read_bytes())

    with pytest.raises(ValueError, match="snapshot path"):
        _verify.restore_generated(tmp_path, {relative: b"untrusted\n"})

    assert (baseline.read_bytes(), ledger.read_bytes()) == before
    assert not outside.exists()


def test_verify_removes_generated_root_that_was_initially_absent(tmp_path: Path):
    generated_root = tmp_path / "docs" / "audit"

    def run_pipeline() -> int:
        generated_root.mkdir(parents=True)
        (generated_root / "partial.md").write_bytes(b"partial\n")
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (0, ["docs/audit/partial.md"])
    assert not generated_root.exists()


def test_verify_preserves_generated_root_that_was_initially_empty(tmp_path: Path):
    generated_root = tmp_path / "docs" / "audit"
    generated_root.mkdir(parents=True)

    def run_pipeline() -> int:
        (generated_root / "partial.md").write_bytes(b"partial\n")
        return 0

    result = _verify.verify(tmp_path, run_pipeline)

    assert result == (0, ["docs/audit/partial.md"])
    assert generated_root.is_dir()
    assert not any(generated_root.iterdir())
