"""Local companion inventory and prefer-local carry ops."""

from pathlib import Path

from plex_renamer.app.services.metadata_service import (
    apply_prefer_local,
    build_metadata_plan,
    inventory_local_metadata,
)
from plex_renamer.constants import MediaType
from tests.test_metadata_service import (
    SEASONS,
    TV_DETAILS,
    FakeTMDB,
    make_settings,
    tv_job,
)


def _make_source_tree(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "Show"
    src.mkdir(parents=True)
    (src / "Show.S01E01.mkv").write_bytes(b"v")
    (src / "Show.S00E01.mkv").write_bytes(b"v")
    (src / "cover.png").write_bytes(b"p")  # → poster slot
    (src / "fanart.jpg").write_bytes(b"f")
    (src / "season01-poster.jpg").write_bytes(b"s")
    (src / "tvshow.nfo").write_text("<tvshow/>", encoding="utf-8")
    (src / "Show.S01E01-thumb.jpg").write_bytes(b"t")
    (src / "banner.jpg").write_bytes(b"b")  # no slot — ignored
    return src


def test_inventory_maps_slots(tmp_path):
    src = _make_source_tree(tmp_path)
    job = tv_job(library_root=str(tmp_path / "src"))
    ops = [op for op in job.rename_ops]
    found = inventory_local_metadata(src, ops, MediaType.TV, tmp_path / "src")
    assert found["poster"].name == "cover.png"
    assert found["fanart"].name == "fanart.jpg"
    assert found["season_poster:1"].name == "season01-poster.jpg"
    assert found["nfo:show"].name == "tvshow.nfo"
    assert found["episode_thumb:Show/Show.S01E01.mkv"].name == "Show.S01E01-thumb.jpg"
    assert "clearlogo" not in found
    assert not any(path.name == "banner.jpg" for path in found.values())


def test_prefer_local_carries_and_removes_plan_entries(tmp_path):
    _make_source_tree(tmp_path)
    job = tv_job(library_root=str(tmp_path / "src"))
    settings = make_settings(metadata_prefer_local=True, metadata_plex_naming=True)
    plan = build_metadata_plan(job, FakeTMDB(details=TV_DETAILS, seasons=SEASONS), settings)

    ops_before = len(job.rename_ops)
    apply_prefer_local(job, plan, tmp_path / "src")

    remaining_slots = {e["slot"] for e in plan["artwork"] + plan["nfo_files"]}
    for fulfilled in (
        "poster",
        "fanart",
        "season_poster:1",
        "nfo:show",
        "episode_thumb:Show/Show.S01E01.mkv",
    ):
        assert fulfilled not in remaining_slots  # plex extras removed too

    carries = job.rename_ops[ops_before:]
    by_name = {op.new_name: op for op in carries}
    # Local extension is preserved; target name follows the convention stem.
    assert by_name["poster.png"].target_dir_relative == "Show (2019)"
    assert by_name["poster.png"].file_type == "artwork"
    assert by_name["tvshow.nfo"].file_type == "nfo"
    thumb_op = by_name["Show (2019) - S01E01 - Pilot-thumb.jpg"]
    assert thumb_op.target_dir_relative == "Show (2019)/Season 01"
    assert thumb_op.original_relative.replace("\\", "/") == "Show/Show.S01E01-thumb.jpg"
    assert all(op.selected and op.status == "OK" for op in carries)


def test_always_tmdb_leaves_plan_untouched(tmp_path):
    _make_source_tree(tmp_path)
    job = tv_job(library_root=str(tmp_path / "src"))
    plan = build_metadata_plan(job, FakeTMDB(details=TV_DETAILS, seasons=SEASONS), make_settings())
    before_ops = len(job.rename_ops)
    before_art = len(plan["artwork"])
    apply_prefer_local(job, plan, tmp_path / "src")
    assert len(job.rename_ops) == before_ops
    assert len(plan["artwork"]) == before_art


def test_local_fulfills_slot_tmdb_lacks(tmp_path):
    # TMDB has no still for the special, but a local thumb exists.
    src = tmp_path / "src" / "Show"
    src.mkdir(parents=True)
    (src / "Show.S00E01.mkv").write_bytes(b"v")
    (src / "Show.S00E01-thumb.jpg").write_bytes(b"t")
    job = tv_job(library_root=str(tmp_path / "src"))
    settings = make_settings(metadata_prefer_local=True)
    plan = build_metadata_plan(job, FakeTMDB(details=TV_DETAILS, seasons=SEASONS), settings)
    apply_prefer_local(job, plan, tmp_path / "src")
    carried = [
        op for op in job.rename_ops if op.new_name == "Show (2019) - S00E01 - Special-thumb.jpg"
    ]
    assert len(carried) == 1
