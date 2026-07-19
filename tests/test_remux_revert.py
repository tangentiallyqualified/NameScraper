"""Reverting remux jobs: delete outputs; No Fear is irreversible."""

from plex_renamer.constants import JobKind
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob


def _job(tmp_path, undo):
    return RenameJob(
        media_type="tv",
        tmdb_id=1,
        media_name="Show",
        library_root=str(tmp_path / "lib"),
        output_root=str(tmp_path / "out"),
        source_folder="Show",
        job_kind=JobKind.REMUX,
        undo_data=undo,
    )


def test_revert_deletes_remux_outputs(tmp_path):
    (tmp_path / "lib").mkdir()
    season = tmp_path / "out" / "Show (2020)" / "Season 01"
    season.mkdir(parents=True)
    final = season / "X.mkv"
    final.write_bytes(b"muxed")
    job = _job(
        tmp_path,
        {
            "renames": [],
            "created_dirs": [],
            "removed_dirs": [],
            "renamed_dirs": [],
            "remux_outputs": [str(final)],
        },
    )
    ok, errors = revert_job(job)
    assert ok, errors
    assert not final.exists()
    assert not season.exists()  # empty output dirs cleaned


def test_no_fear_job_is_irreversible(tmp_path):
    final = tmp_path / "out" / "X.mkv"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"muxed")
    job = _job(tmp_path, {"renames": [], "remux_outputs": [str(final)], "irreversible": True})
    ok, errors = revert_job(job)
    assert not ok
    assert "cannot be reverted" in errors[0]
    assert final.exists()  # nothing touched


def test_missing_output_is_not_fatal(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "out").mkdir()
    job = _job(
        tmp_path,
        {
            "renames": [],
            "created_dirs": [],
            "removed_dirs": [],
            "renamed_dirs": [],
            "remux_outputs": [str(tmp_path / "out" / "gone.mkv")],
        },
    )
    ok, _errors = revert_job(job)
    assert ok  # nothing else failed; the missing file is just noted
