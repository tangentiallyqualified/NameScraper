"""Characterize the public ``revert_job`` contract before seam extraction."""

import shutil
from pathlib import Path

import pytest

from plex_renamer.constants import JobKind
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob


def _job(
    tmp_path: Path,
    *,
    undo: dict[str, object] | None,
    output: bool = True,
    kind: str = JobKind.RENAME,
) -> RenameJob:
    library_root = tmp_path / "library"
    library_root.mkdir(exist_ok=True)
    output_root = tmp_path / "output"
    if output:
        output_root.mkdir(exist_ok=True)
    return RenameJob(
        media_type="tv",
        tmdb_id=1,
        media_name="Show",
        library_root=str(library_root),
        output_root=str(output_root) if output else None,
        source_folder="Show",
        job_kind=kind,
        undo_data=undo,
    )


def test_no_undo_data_is_rejected_without_touching_files(tmp_path: Path) -> None:
    marker = tmp_path / "out" / "marker.mkv"
    marker.parent.mkdir()
    marker.write_bytes(b"keep")
    job = _job(tmp_path, undo=None)
    library_marker = Path(job.library_root) / "library-marker.mkv"
    assert job.output_root is not None
    output_marker = Path(job.output_root) / "output-marker.mkv"
    library_marker.write_bytes(b"keep-library")
    output_marker.write_bytes(b"keep-output")

    ok, errors = revert_job(job)

    assert ok is False
    assert errors == ["No undo data stored for this job."]
    assert marker.read_bytes() == b"keep"
    assert library_marker.read_bytes() == b"keep-library"
    assert output_marker.read_bytes() == b"keep-output"


def test_created_sidecars_and_remux_outputs_are_removed_before_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    source = tmp_path / "library" / "Show" / "episode.mkv"
    destination = tmp_path / "output" / "Show" / "renamed.mkv"
    sidecar = destination.with_suffix(".nfo")
    remux = destination.with_name("remuxed.mkv")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"video")
    sidecar.write_text("metadata", encoding="utf-8")
    remux.write_bytes(b"remux")

    original_unlink = Path.unlink
    original_move = shutil.move

    def recording_unlink(path: Path, missing_ok: bool = False) -> None:
        if path.is_relative_to(tmp_path):
            events.append(f"unlink:{path.name}")
        original_unlink(path, missing_ok=missing_ok)

    def recording_move(src: str, dst: str, copy_function=shutil.copy2) -> str:
        src_path = Path(src)
        if src_path.is_relative_to(tmp_path):
            events.append(f"move:{src_path.name}")
        return original_move(src, dst, copy_function=copy_function)

    monkeypatch.setattr(Path, "unlink", recording_unlink)
    monkeypatch.setattr(shutil, "move", recording_move)
    undo = {
        "remux_outputs": [str(remux)],
        "created_files": [str(sidecar)],
        "renames": [{"new": str(destination), "old": str(source)}],
    }
    ok, errors = revert_job(_job(tmp_path, undo=undo, output=True))

    assert ok, errors
    assert events == ["unlink:remuxed.mkv", "unlink:renamed.nfo", "move:renamed.mkv"]
    assert source.read_bytes() == b"video"
    assert not sidecar.exists()
    assert not remux.exists()


@pytest.mark.parametrize("irreversible", [True, 1])
def test_irreversible_undo_never_mutates_tree(tmp_path: Path, irreversible: object) -> None:
    output = tmp_path / "out" / "result.mkv"
    output.parent.mkdir()
    output.write_bytes(b"muxed")
    ok, errors = revert_job(
        _job(tmp_path, undo={"irreversible": irreversible, "remux_outputs": [str(output)]})
    )
    assert not ok
    assert "cannot be reverted" in errors[0]
    assert output.exists()
