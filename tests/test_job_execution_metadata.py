"""Decorate phase: sidecar writes, artwork fetch, title embedding."""

from pathlib import Path

from plex_renamer._job_execution_metadata import execute_metadata_plan
from plex_renamer.constants import MediaType
from plex_renamer.engine.models import RenameResult
from plex_renamer.job_store import RenameJob, RenameOp


def make_job(tmp_path, plan, ops=None) -> RenameJob:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return RenameJob(
        media_type=MediaType.TV, tmdb_id=42, media_name="Show",
        library_root=str(tmp_path / "src"), output_root=str(out),
        source_folder="Show", show_folder_rename="Show (2019)",
        rename_ops=ops or [RenameOp(
            original_relative="Show/a.mkv",
            new_name="Show (2019) - S01E01 - Pilot.mkv",
            target_dir_relative="Show (2019)/Season 01",
            status="OK", season=1, episodes=[1])],
        metadata_plan=plan,
    )


def base_plan(**overrides) -> dict:
    plan = {
        "nfo_files": [{"target_relative": "Show (2019)/tvshow.nfo",
                       "content": "<tvshow/>", "slot": "nfo:show"}],
        "artwork": [{"tmdb_path": "/p.jpg",
                     "target_relative": "Show (2019)/poster.jpg",
                     "kind": "poster", "slot": "poster",
                     "plex_extra": False}],
        "embed_title": False, "prefer_local": False, "plex_naming": False,
        "mkvpropedit_path": "",
    }
    plan.update(overrides)
    return plan


def _result() -> RenameResult:
    result = RenameResult()
    result.log_entry = {}
    return result


def test_writes_nfo_and_artwork_and_records_created(tmp_path):
    job = make_job(tmp_path, base_plan())
    result = _result()
    execute_metadata_plan(
        job, result=result, fetch_image_bytes=lambda p: b"img")

    nfo = Path(job.output_root) / "Show (2019)" / "tvshow.nfo"
    poster = Path(job.output_root) / "Show (2019)" / "poster.jpg"
    assert nfo.read_text(encoding="utf-8") == "<tvshow/>"
    assert poster.read_bytes() == b"img"
    assert set(result.log_entry["created_files"]) == {str(nfo), str(poster)}
    assert result.errors == []


def test_missing_artwork_warns_but_nfo_still_written(tmp_path):
    job = make_job(tmp_path, base_plan())
    result = _result()
    execute_metadata_plan(job, result=result, fetch_image_bytes=lambda p: None)
    assert (Path(job.output_root) / "Show (2019)" / "tvshow.nfo").exists()
    assert not (Path(job.output_root) / "Show (2019)" / "poster.jpg").exists()
    assert any("poster.jpg" in e for e in result.errors)


def test_prefer_local_skips_existing_destination(tmp_path):
    job = make_job(tmp_path, base_plan(prefer_local=True))
    show_dir = Path(job.output_root) / "Show (2019)"
    show_dir.mkdir(parents=True)
    (show_dir / "poster.jpg").write_bytes(b"existing")
    result = _result()
    execute_metadata_plan(job, result=result, fetch_image_bytes=lambda p: b"new")
    assert (show_dir / "poster.jpg").read_bytes() == b"existing"
    assert str(show_dir / "poster.jpg") not in \
        result.log_entry.get("created_files", [])


def test_always_tmdb_overwrites_existing_destination(tmp_path):
    job = make_job(tmp_path, base_plan())
    show_dir = Path(job.output_root) / "Show (2019)"
    show_dir.mkdir(parents=True)
    (show_dir / "poster.jpg").write_bytes(b"old")
    result = _result()
    execute_metadata_plan(job, result=result, fetch_image_bytes=lambda p: b"new")
    assert (show_dir / "poster.jpg").read_bytes() == b"new"


def test_escaping_target_rejected(tmp_path):
    plan = base_plan()
    plan["nfo_files"][0]["target_relative"] = "../outside.nfo"
    job = make_job(tmp_path, plan)
    result = _result()
    execute_metadata_plan(job, result=result, fetch_image_bytes=lambda p: b"x")
    assert not (tmp_path / "outside.nfo").exists()
    assert any("escapes" in e for e in result.errors)


def test_embed_title_runs_propedit_on_renamed_mkvs(tmp_path):
    fake_propedit = tmp_path / "mkvpropedit.exe"
    fake_propedit.write_bytes(b"")
    plan = base_plan(embed_title=True,
                     mkvpropedit_path=str(fake_propedit),
                     nfo_files=[], artwork=[])
    job = make_job(tmp_path, plan)
    target = (Path(job.output_root) / "Show (2019)" / "Season 01" /
              "Show (2019) - S01E01 - Pilot.mkv")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"mkv")

    calls = []

    def fake_runner(args):
        calls.append(args)
        return 0, ""

    result = _result()
    execute_metadata_plan(job, result=result, propedit_runner=fake_runner)
    assert len(calls) == 1
    assert calls[0][1] == str(target)
    assert calls[0][-1] == "title=Show (2019) - S01E01 - Pilot"
    assert result.errors == []


def test_embed_title_skips_mux_ops_and_missing_targets(tmp_path):
    fake_propedit = tmp_path / "mkvpropedit.exe"
    fake_propedit.write_bytes(b"")
    mux_op = RenameOp(
        original_relative="Show/a.mkv",
        new_name="Show (2019) - S01E01 - Pilot.mkv",
        target_dir_relative="Show (2019)/Season 01",
        status="OK", season=1, episodes=[1],
        mux={"anything": True})
    plan = base_plan(embed_title=True,
                     mkvpropedit_path=str(fake_propedit),
                     nfo_files=[], artwork=[])
    job = make_job(tmp_path, plan, ops=[mux_op])
    calls = []
    result = _result()
    execute_metadata_plan(
        job, result=result, propedit_runner=lambda a: calls.append(a) or (0, ""))
    assert calls == []      # mux ops were titled during the mux itself


def test_propedit_unavailable_is_single_warning(tmp_path, monkeypatch):
    import plex_renamer._job_execution_metadata as mod

    monkeypatch.setattr(mod, "find_mkvpropedit", lambda setting="": None)
    plan = base_plan(embed_title=True, mkvpropedit_path="",
                     nfo_files=[], artwork=[])
    job = make_job(tmp_path, plan)
    target = (Path(job.output_root) / "Show (2019)" / "Season 01" /
              "Show (2019) - S01E01 - Pilot.mkv")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"mkv")
    result = _result()
    execute_metadata_plan(job, result=result)
    assert sum("mkvpropedit" in e for e in result.errors) == 1


def test_top_dir_remap_applied_to_nfo_and_artwork(tmp_path):
    out = tmp_path / "out"
    plan = base_plan()
    job = make_job(tmp_path, plan)
    result = _result()
    result.log_entry["top_dir_remap"] = {
        str(out / "Show (2019)"): str(out / "Show (2019) (2)"),
    }
    execute_metadata_plan(
        job, result=result, fetch_image_bytes=lambda p: b"img")

    nfo = out / "Show (2019) (2)" / "tvshow.nfo"
    poster = out / "Show (2019) (2)" / "poster.jpg"
    assert nfo.read_text(encoding="utf-8") == "<tvshow/>"
    assert poster.read_bytes() == b"img"
    assert not (out / "Show (2019)").exists()
    assert set(result.log_entry["created_files"]) == {str(nfo), str(poster)}
    assert result.errors == []


def test_top_dir_remap_applied_to_embed_title_target(tmp_path):
    out = tmp_path / "out"
    fake_propedit = tmp_path / "mkvpropedit.exe"
    fake_propedit.write_bytes(b"")
    plan = base_plan(embed_title=True, mkvpropedit_path=str(fake_propedit),
                      nfo_files=[], artwork=[])
    job = make_job(tmp_path, plan)
    remapped_target = (out / "Show (2019) (2)" / "Season 01" /
                        "Show (2019) - S01E01 - Pilot.mkv")
    remapped_target.parent.mkdir(parents=True)
    remapped_target.write_bytes(b"mkv")

    result = _result()
    result.log_entry["top_dir_remap"] = {
        str(out / "Show (2019)"): str(out / "Show (2019) (2)"),
    }
    calls = []
    execute_metadata_plan(
        job, result=result,
        propedit_runner=lambda a: calls.append(a) or (0, ""))

    assert len(calls) == 1
    assert calls[0][1] == str(remapped_target)
    assert result.errors == []


def test_missing_target_relative_skips_with_warning_nfo_and_artwork(tmp_path):
    plan = base_plan()
    del plan["nfo_files"][0]["target_relative"]
    del plan["artwork"][0]["target_relative"]
    job = make_job(tmp_path, plan)
    result = _result()
    execute_metadata_plan(job, result=result, fetch_image_bytes=lambda p: b"img")

    assert result.log_entry.get("created_files", []) == []
    assert any("nfo skipped" in e for e in result.errors)
    assert any("artwork skipped" in e for e in result.errors)


def test_missing_content_and_tmdb_path_skip_with_warning(tmp_path):
    plan = base_plan()
    del plan["nfo_files"][0]["content"]
    del plan["artwork"][0]["tmdb_path"]
    job = make_job(tmp_path, plan)
    result = _result()
    execute_metadata_plan(job, result=result, fetch_image_bytes=lambda p: b"img")

    assert result.log_entry.get("created_files", []) == []
    assert any("nfo skipped" in e for e in result.errors)
    assert any("artwork skipped" in e for e in result.errors)


def test_no_plan_is_noop(tmp_path):
    job = make_job(tmp_path, None)
    result = _result()
    execute_metadata_plan(job, result=result)
    assert result.errors == []
    assert "created_files" not in result.log_entry


def _extras_plan(tmp_path, *, embed_title=True, tags_xml="<Tags/>",
                 cover="/p.jpg"):
    fake_propedit = tmp_path / "mkvpropedit.exe"
    fake_propedit.write_bytes(b"")
    return base_plan(
        embed_title=embed_title, mkvpropedit_path=str(fake_propedit),
        nfo_files=[], artwork=[],
        embed_extras=[{"op": "Show/a.mkv", "tags_xml": tags_xml,
                       "cover_tmdb_path": cover}])


def _make_target(job) -> Path:
    target = (Path(job.output_root) / "Show (2019)" / "Season 01" /
              "Show (2019) - S01E01 - Pilot.mkv")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"mkv")
    return target


def test_embed_extras_tags_and_cover_in_propedit_args(tmp_path):
    job = make_job(tmp_path, _extras_plan(tmp_path))
    _make_target(job)
    seen = {}

    def fake_runner(args):
        seen["args"] = list(args)
        tags_arg = args[args.index("--tags") + 1]     # "global:<path>"
        seen["tags_content"] = Path(
            tags_arg.split(":", 1)[1]).read_text(encoding="utf-8")
        seen["cover_exists_at_run"] = Path(
            args[args.index("--add-attachment") + 1]).exists()
        return 0, ""

    result = _result()
    execute_metadata_plan(
        job, result=result, fetch_image_bytes=lambda p: b"jpgbytes",
        propedit_runner=fake_runner)

    args = seen["args"]
    assert "--set" in args                      # title still embedded
    tags_value = args[args.index("--tags") + 1]
    assert tags_value.startswith("global:")
    assert seen["tags_content"] == "<Tags/>"
    assert seen["cover_exists_at_run"] is True
    assert args[args.index("--attachment-name") + 1] == "cover.jpg"
    # Temp files removed after the run.
    assert not Path(tags_value.split(":", 1)[1]).exists()
    assert not Path(args[args.index("--add-attachment") + 1]).exists()
    assert result.errors == []


def test_embed_extras_run_without_title(tmp_path):
    job = make_job(tmp_path, _extras_plan(tmp_path, embed_title=False))
    _make_target(job)
    calls = []
    result = _result()
    execute_metadata_plan(
        job, result=result, fetch_image_bytes=lambda p: b"jpg",
        propedit_runner=lambda a: calls.append(list(a)) or (0, ""))
    assert len(calls) == 1
    assert "--edit" not in calls[0]
    assert "--tags" in calls[0]


def test_cover_fetch_failure_warns_but_tags_still_embed(tmp_path):
    job = make_job(tmp_path, _extras_plan(tmp_path))
    _make_target(job)
    calls = []
    result = _result()
    execute_metadata_plan(
        job, result=result, fetch_image_bytes=lambda p: None,
        propedit_runner=lambda a: calls.append(list(a)) or (0, ""))
    assert len(calls) == 1
    assert "--tags" in calls[0]
    assert "--add-attachment" not in calls[0]
    assert any("Cover art unavailable" in e for e in result.errors)


def test_cover_fetch_raises_warns_but_tags_still_embed(tmp_path):
    # A fetcher that raises (not just returns None) must not escape
    # execute_metadata_plan — the remux/rename path has no outer
    # containment around this call, so an uncaught exception here would
    # fail the whole job.
    job = make_job(tmp_path, _extras_plan(tmp_path))
    _make_target(job)
    calls = []
    result = _result()

    def raising_fetch(path):
        raise RuntimeError("boom")

    execute_metadata_plan(
        job, result=result, fetch_image_bytes=raising_fetch,
        propedit_runner=lambda a: calls.append(list(a)) or (0, ""))

    assert len(calls) == 1
    assert "--tags" in calls[0]
    assert "--add-attachment" not in calls[0]
    assert sum("Cover fetch failed" in e for e in result.errors) == 1
    assert not any("Cover art unavailable" in e for e in result.errors)


def test_embed_extras_mux_ops_skipped_by_propedit_pass(tmp_path):
    mux_op = RenameOp(
        original_relative="Show/a.mkv",
        new_name="Show (2019) - S01E01 - Pilot.mkv",
        target_dir_relative="Show (2019)/Season 01",
        status="OK", season=1, episodes=[1],
        mux={"anything": True})
    job = make_job(tmp_path, _extras_plan(tmp_path, embed_title=False),
                   ops=[mux_op])
    calls = []
    result = _result()
    execute_metadata_plan(
        job, result=result, fetch_image_bytes=lambda p: b"jpg",
        propedit_runner=lambda a: calls.append(a) or (0, ""))
    assert calls == []      # mux ops embed during the mux itself
