"""Characterize direct rollback handlers against the public revert contract."""

from pathlib import Path
from typing import Any, cast

import pytest

import plex_renamer._job_revert as job_revert
from plex_renamer._job_revert import RevertContext
from plex_renamer.constants import JobKind
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob


def _job(root: Path, *, undo: dict[str, object]) -> RenameJob:
    library_root = root / "library"
    library_root.mkdir(exist_ok=True)
    return RenameJob(
        media_type="tv",
        tmdb_id=1,
        media_name="Show",
        library_root=str(library_root),
        source_folder="Show",
        job_kind=JobKind.RENAME,
        undo_data=undo,
    )


def test_output_and_directory_handlers_match_public_revert_order_and_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(job_revert, "remove_generated_outputs")
    assert hasattr(job_revert, "restore_directories")
    remove_generated_outputs = job_revert.remove_generated_outputs
    restore_directories = job_revert.restore_directories

    def setup_tree(root: Path) -> RenameJob:
        original_root = root / "library" / "Show"
        renamed_root = root / "library" / "Renamed Show"
        renamed_season = renamed_root / "Season 01"
        renamed_season.mkdir(parents=True)
        (renamed_season / "keep.txt").write_text("keep", encoding="utf-8")
        remux = renamed_season / "remuxed.mkv"
        sidecar = renamed_season / "renamed.nfo"
        remux.write_bytes(b"remux")
        sidecar.write_text("metadata", encoding="utf-8")
        undo: dict[str, object] = {
            "remux_outputs": [str(remux)],
            "created_files": [str(sidecar)],
            "renamed_dirs": [
                {"new": str(renamed_root), "old": str(original_root)},
                {"new": str(renamed_season), "old": str(renamed_root / "S1")},
            ],
        }
        return _job(root, undo=undo)

    def tree_snapshot(root: Path) -> list[tuple[str, bytes | None]]:
        return [
            (path.relative_to(root).as_posix(), path.read_bytes() if path.is_file() else None)
            for path in sorted(root.rglob("*"))
        ]

    events: list[str] = []
    original_unlink = Path.unlink
    original_rename = Path.rename

    def recording_unlink(path: Path, missing_ok: bool = False) -> None:
        if path.is_relative_to(tmp_path):
            events.append(f"unlink:{path.name}")
        original_unlink(path, missing_ok=missing_ok)

    def recording_rename(path: Path, target: Path) -> Path:
        if path.is_relative_to(tmp_path):
            events.append(f"rename:{path.name}")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "unlink", recording_unlink)
    monkeypatch.setattr(Path, "rename", recording_rename)

    direct_job = setup_tree(tmp_path / "direct")
    direct_library = Path(direct_job.library_root)
    direct_boundary = direct_library.resolve(strict=False)
    assert cast(Any, direct_job).undo_data is not None
    direct_undo = cast(dict[str, Any], cast(Any, direct_job).undo_data)
    context = RevertContext(
        job=direct_job,
        undo=direct_undo,
        library_root=direct_library,
        source_boundary=direct_boundary,
        output_boundary=direct_boundary,
        cleanup_boundary=direct_boundary,
    )

    remove_generated_outputs(context)
    restore_directories(context)

    direct_result = (not context.errors, context.errors)
    direct_events = events.copy()
    events.clear()

    public_job = setup_tree(tmp_path / "public")
    public_result = revert_job(public_job)

    expected_events = [
        "unlink:remuxed.mkv",
        "unlink:renamed.nfo",
        "rename:Season 01",
        "rename:Renamed Show",
    ]
    assert direct_events == expected_events
    assert events == expected_events
    assert direct_result == public_result == (True, [])
    assert tree_snapshot(direct_library) == tree_snapshot(Path(public_job.library_root))
