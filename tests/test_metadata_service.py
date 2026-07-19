"""MetadataPlan builder: TMDB-sourced slots baked from job ops."""

from types import SimpleNamespace

from plex_renamer.app.services.metadata_service import (
    build_metadata_plan,
    finalize_plan,
    metadata_active,
)
from plex_renamer.constants import MediaType
from plex_renamer.job_store import RenameJob, RenameOp


def make_settings(**overrides):
    values = {
        "metadata_enabled": True,
        "metadata_prefer_local": False,
        "metadata_write_nfo": True,
        "metadata_write_episode_nfo": True,
        "metadata_write_poster": True,
        "metadata_write_fanart": True,
        "metadata_write_season_posters": True,
        "metadata_write_episode_thumbs": True,
        "metadata_write_clearlogo": True,
        "metadata_plex_naming": False,
        "metadata_embed_title": True,
        "mkvmerge_path": "",
    }
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
        return self.seasons.get(
            season, {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}
        )

    def get_movie_details(self, movie_id):
        return self.movie


def tv_job(ops=None, **overrides):
    defaults = {
        "media_type": MediaType.TV,
        "tmdb_id": 42,
        "media_name": "Show",
        "library_root": "C:/src",
        "output_root": "C:/out",
        "source_folder": "Show",
        "show_folder_rename": "Show (2019)",
        "rename_ops": ops
        or [
            RenameOp(
                original_relative="Show/Show.S01E01.mkv",
                new_name="Show (2019) - S01E01 - Pilot.mkv",
                target_dir_relative="Show (2019)/Season 01",
                status="OK",
                season=1,
                episodes=[1],
            ),
            RenameOp(
                original_relative="Show/Show.S00E01.mkv",
                new_name="Show (2019) - S00E01 - Special.mkv",
                target_dir_relative="Show (2019)/Season 00",
                status="OK",
                season=0,
                episodes=[1],
            ),
        ],
    }
    defaults.update(overrides)
    return RenameJob(**defaults)


TV_DETAILS = {
    "id": 42,
    "name": "Show",
    "overview": "About things.",
    "first_air_date": "2019-01-01",
    "poster_path": "/p.jpg",
    "backdrop_path": "/b.jpg",
    "images": {
        "logos": [{"file_path": "/logo.png", "iso_639_1": "en", "vote_average": 5, "vote_count": 5}]
    },
}

SEASONS = {
    1: {
        "titles": {1: "Pilot"},
        "posters": {1: "/still1.jpg"},
        "episodes": {1: {"name": "Pilot", "overview": "Ep plot", "still_path": "/still1.jpg"}},
        "season_poster_path": "/s1.jpg",
    },
    0: {
        "titles": {1: "Special"},
        "posters": {1: None},
        "episodes": {1: {"name": "Special", "still_path": None}},
        "season_poster_path": "/s0.jpg",
    },
}


def _by_slot(plan, slot):
    for entry in plan["nfo_files"] + plan["artwork"]:
        if entry["slot"] == slot:
            return entry
    return None


def test_metadata_active_gates_on_master_switch():
    assert metadata_active(make_settings()) is True
    assert metadata_active(make_settings(metadata_enabled=False)) is False
    assert metadata_active(None) is False


def test_tv_plan_slots_and_targets():
    plan = build_metadata_plan(
        tv_job(), FakeTMDB(details=TV_DETAILS, seasons=SEASONS), make_settings()
    )

    show_nfo = _by_slot(plan, "nfo:show")
    assert show_nfo["target_relative"] == "Show (2019)/tvshow.nfo"
    assert "<tvshow>" in show_nfo["content"]

    assert _by_slot(plan, "poster")["target_relative"] == "Show (2019)/poster.jpg"
    assert _by_slot(plan, "poster")["tmdb_path"] == "/p.jpg"
    assert _by_slot(plan, "fanart")["target_relative"] == "Show (2019)/fanart.jpg"
    assert _by_slot(plan, "clearlogo")["target_relative"] == "Show (2019)/clearlogo.png"

    assert _by_slot(plan, "season_poster:1")["target_relative"] == "Show (2019)/season01-poster.jpg"
    assert (
        _by_slot(plan, "season_poster:0")["target_relative"]
        == "Show (2019)/season-specials-poster.jpg"
    )

    ep_nfo = _by_slot(plan, "nfo:episode:Show/Show.S01E01.mkv")
    assert ep_nfo["target_relative"] == "Show (2019)/Season 01/Show (2019) - S01E01 - Pilot.nfo"
    thumb = _by_slot(plan, "episode_thumb:Show/Show.S01E01.mkv")
    assert (
        thumb["target_relative"] == "Show (2019)/Season 01/Show (2019) - S01E01 - Pilot-thumb.jpg"
    )
    assert thumb["tmdb_path"] == "/still1.jpg"

    # Specials episode has no still — placeholder entry, filtered later.
    special_thumb = _by_slot(plan, "episode_thumb:Show/Show.S00E01.mkv")
    assert special_thumb["tmdb_path"] is None

    assert plan["embed_title"] is True


def test_plex_naming_adds_duplicate_targets():
    plan = build_metadata_plan(
        tv_job(),
        FakeTMDB(details=TV_DETAILS, seasons=SEASONS),
        make_settings(metadata_plex_naming=True),
    )
    extras = [a for a in plan["artwork"] if a["plex_extra"]]
    targets = {a["target_relative"] for a in extras}
    assert "Show (2019)/Season 01/Season01.jpg" in targets
    assert "Show (2019)/Season 00/Season00.jpg" in targets
    assert "Show (2019)/Season 01/Show (2019) - S01E01 - Pilot.jpg" in targets
    # Plex extras share the primary slot key. (The specials episode also
    # emits a placeholder extra — tmdb_path None — dropped by finalize_plan.)
    assert all(
        a["slot"]
        in (
            "season_poster:1",
            "season_poster:0",
            "episode_thumb:Show/Show.S01E01.mkv",
            "episode_thumb:Show/Show.S00E01.mkv",
        )
        for a in extras
    )


def test_toggles_suppress_slots():
    plan = build_metadata_plan(
        tv_job(),
        FakeTMDB(details=TV_DETAILS, seasons=SEASONS),
        make_settings(
            metadata_write_nfo=False, metadata_write_poster=False, metadata_write_clearlogo=False
        ),
    )
    assert _by_slot(plan, "nfo:show") is None
    assert _by_slot(plan, "poster") is None
    assert _by_slot(plan, "clearlogo") is None
    assert _by_slot(plan, "fanart") is not None


def test_movie_plan():
    op = RenameOp(
        original_relative="Dune.2021.mkv",
        new_name="Dune (2021).mkv",
        target_dir_relative="Dune (2021)",
        status="OK",
    )
    job = tv_job(ops=[op], media_type=MediaType.MOVIE, tmdb_id=7, show_folder_rename="Dune (2021)")
    movie = {
        "id": 7,
        "title": "Dune",
        "overview": "Sand.",
        "release_date": "2021-09-15",
        "poster_path": "/mp.jpg",
        "backdrop_path": "/mb.jpg",
        "images": {"logos": []},
    }
    plan = build_metadata_plan(job, FakeTMDB(movie=movie), make_settings())
    nfo = _by_slot(plan, "nfo:show")
    assert nfo["target_relative"] == "Dune (2021)/Dune (2021).nfo"
    assert "<movie>" in nfo["content"]
    assert _by_slot(plan, "poster")["target_relative"] == "Dune (2021)/poster.jpg"


def test_finalize_drops_placeholders_and_empty_plans():
    plan = {
        "nfo_files": [],
        "artwork": [
            {
                "tmdb_path": None,
                "target_relative": "x/a.jpg",
                "kind": "episode_thumb",
                "slot": "episode_thumb:x",
                "plex_extra": False,
            },
        ],
        "embed_title": False,
        "prefer_local": False,
        "plex_naming": False,
        "mkvpropedit_path": "",
    }
    assert finalize_plan(plan) is None

    plan["embed_title"] = True
    finalized = finalize_plan(plan)
    assert finalized["artwork"] == []
    assert finalized["embed_title"] is True


def test_no_plan_without_master_or_client_or_id():
    assert build_metadata_plan(tv_job(), None, make_settings()) is None
    assert build_metadata_plan(tv_job(), FakeTMDB(), make_settings(metadata_enabled=False)) is None
    assert build_metadata_plan(tv_job(tmdb_id=0), FakeTMDB(), make_settings()) is None
