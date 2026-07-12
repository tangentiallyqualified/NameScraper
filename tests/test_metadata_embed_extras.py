"""embed_extras entries baked into MetadataPlans (spec: mkv-embedded-metadata)."""

from types import SimpleNamespace

from plex_renamer.app.services.metadata_service import (
    build_metadata_plan,
    finalize_plan,
)
from plex_renamer.constants import MediaType
from plex_renamer.job_store import RenameJob, RenameOp


def make_settings(**overrides):
    values = dict(
        metadata_enabled=True, metadata_prefer_local=False,
        metadata_write_nfo=True, metadata_write_episode_nfo=True,
        metadata_write_poster=True, metadata_write_fanart=True,
        metadata_write_season_posters=True,
        metadata_write_episode_thumbs=True,
        metadata_write_clearlogo=True, metadata_plex_naming=False,
        metadata_embed_title=True, metadata_embed_cover=True,
        metadata_embed_tags=True, mkvmerge_path="",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeTMDB:
    language = "en-US"

    def __init__(self, details=None, seasons=None, movie=None):
        self.details = details or {}
        self.seasons = seasons or {}
        self.movie = movie or {}

    def get_tv_details(self, show_id):
        return self.details

    def get_season(self, show_id, season):
        return self.seasons.get(season, {
            "titles": {}, "posters": {}, "episodes": {},
            "season_poster_path": None})

    def get_movie_details(self, movie_id):
        return self.movie


TV_DETAILS = {
    "id": 42, "name": "Show", "overview": "About things.",
    "first_air_date": "2019-01-01", "poster_path": "/show-p.jpg",
    "backdrop_path": "/b.jpg", "genres": [{"name": "Drama"}],
}

SEASONS = {
    1: {"titles": {1: "Pilot"}, "posters": {1: "/still1.jpg"},
        "episodes": {1: {"name": "Pilot", "overview": "Ep plot",
                         "air_date": "2019-01-05", "still_path": "/still1.jpg"}},
        "season_poster_path": "/s1.jpg"},
    2: {"titles": {}, "posters": {}, "episodes": {},
        "season_poster_path": None},
}

MOVIE_DETAILS = {
    "id": 7, "title": "Dune", "overview": "Sand.",
    "release_date": "2021-09-15", "poster_path": "/m-p.jpg",
    "genres": [{"name": "Science Fiction"}],
}


def tv_job(ops=None, **overrides):
    defaults = dict(
        media_type=MediaType.TV, tmdb_id=42, media_name="Show",
        library_root="C:/src", output_root="C:/out", source_folder="Show",
        show_folder_rename="Show (2019)",
        rename_ops=ops or [
            RenameOp(
                original_relative="Show/Show.S01E01.mkv",
                new_name="Show (2019) - S01E01 - Pilot.mkv",
                target_dir_relative="Show (2019)/Season 01",
                status="OK", season=1, episodes=[1]),
            RenameOp(
                original_relative="Show/Show.S02E01.mp4",
                new_name="Show (2019) - S02E01 - Later.mp4",
                target_dir_relative="Show (2019)/Season 02",
                status="OK", season=2, episodes=[1]),
        ],
    )
    defaults.update(overrides)
    return RenameJob(**defaults)


def movie_job():
    return RenameJob(
        media_type=MediaType.MOVIE, tmdb_id=7, media_name="Dune",
        library_root="C:/src", output_root="C:/out", source_folder="Dune",
        rename_ops=[RenameOp(
            original_relative="Dune/dune.mkv",
            new_name="Dune (2021).mkv",
            target_dir_relative="Dune (2021)",
            status="OK")],
    )


def _extras(plan):
    return {e["op"]: e for e in plan["embed_extras"]}


def test_tv_entries_only_for_mkv_ops_with_season_cover():
    plan = build_metadata_plan(
        tv_job(), FakeTMDB(details=TV_DETAILS, seasons=SEASONS),
        make_settings())
    extras = _extras(plan)

    assert set(extras) == {"Show/Show.S01E01.mkv"}   # the mp4 op gets none
    entry = extras["Show/Show.S01E01.mkv"]
    assert entry["cover_tmdb_path"] == "/s1.jpg"      # season poster wins
    assert "<Tags>" in entry["tags_xml"]
    assert "Pilot" in entry["tags_xml"]
    assert "Drama" in entry["tags_xml"]


def test_tv_cover_falls_back_to_show_poster():
    ops = [RenameOp(
        original_relative="Show/Show.S02E01.mkv",
        new_name="Show (2019) - S02E01 - Later.mkv",
        target_dir_relative="Show (2019)/Season 02",
        status="OK", season=2, episodes=[1])]
    plan = build_metadata_plan(
        tv_job(ops=ops), FakeTMDB(details=TV_DETAILS, seasons=SEASONS),
        make_settings())
    entry = _extras(plan)["Show/Show.S02E01.mkv"]
    assert entry["cover_tmdb_path"] == "/show-p.jpg"


def test_movie_entry_uses_movie_poster_and_tags():
    plan = build_metadata_plan(
        movie_job(), FakeTMDB(movie=MOVIE_DETAILS), make_settings())
    entry = _extras(plan)["Dune/dune.mkv"]
    assert entry["cover_tmdb_path"] == "/m-p.jpg"
    assert "Dune" in entry["tags_xml"]
    assert "DATE_RELEASED" in entry["tags_xml"]


def test_toggles_gate_fields_independently():
    tmdb = FakeTMDB(details=TV_DETAILS, seasons=SEASONS)

    cover_only = build_metadata_plan(
        tv_job(), tmdb, make_settings(metadata_embed_tags=False))
    entry = _extras(cover_only)["Show/Show.S01E01.mkv"]
    assert entry["tags_xml"] is None
    assert entry["cover_tmdb_path"] == "/s1.jpg"

    tags_only = build_metadata_plan(
        tv_job(), tmdb, make_settings(metadata_embed_cover=False))
    entry = _extras(tags_only)["Show/Show.S01E01.mkv"]
    assert entry["cover_tmdb_path"] is None
    assert "Pilot" in entry["tags_xml"]

    neither = build_metadata_plan(
        tv_job(), tmdb, make_settings(metadata_embed_cover=False,
                                      metadata_embed_tags=False))
    assert neither["embed_extras"] == []


def test_finalize_plan_survives_on_extras_alone():
    plan = build_metadata_plan(
        movie_job(), FakeTMDB(movie=MOVIE_DETAILS),
        make_settings(metadata_write_nfo=False, metadata_write_poster=False,
                      metadata_write_fanart=False,
                      metadata_write_clearlogo=False,
                      metadata_embed_title=False))
    finalized = finalize_plan(plan)
    assert finalized is not None
    assert finalized["embed_extras"]

    empty = build_metadata_plan(
        movie_job(), FakeTMDB(movie=MOVIE_DETAILS),
        make_settings(metadata_write_nfo=False, metadata_write_poster=False,
                      metadata_write_fanart=False,
                      metadata_write_clearlogo=False,
                      metadata_embed_title=False,
                      metadata_embed_cover=False,
                      metadata_embed_tags=False))
    assert finalize_plan(empty) is None
