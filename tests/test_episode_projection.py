"""Projection tests: assignment table -> PreviewItem rows."""

from pathlib import Path

from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    REASON_NO_PARSE,
    REASON_NO_TITLE_MATCH,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine._episode_projection import project_preview_items

SHOW_INFO = {"id": 99, "name": "Demo Show", "year": "2020"}
MEDIA_FIELDS = {"media_id": 99, "media_name": "Demo Show"}
ROOT = Path("C:/lib/Demo Show (2020)")


def make_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode, title in [(1, "Pilot"), (2, "The Heist"), (3, "Endgame")]:
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
    table.add_slot(EpisodeSlot(season=0, episode=1, title="Special A"))
    return table


def project(table):
    return project_preview_items(
        table, show_info=SHOW_INFO, root=ROOT, media_fields=MEDIA_FIELDS,
    )


class TestProjection:
    def test_assigned_file_gets_rename(self):
        table = make_table()
        entry = table.add_file(ROOT / "src" / "demo.s01e01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.96)
        items = project(table)
        assert len(items) == 1
        item = items[0]
        assert item.file_id == entry.file_id
        assert item.status == "OK"
        assert item.season == 1 and item.episodes == [1]
        assert item.new_name == "Demo Show (2020) - S01E01 - Pilot.mkv"
        assert item.target_dir == ROOT / "Season 01"
        assert item.episode_confidence == 0.96

    def test_multi_episode_name(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo.s01e01-e03.mkv")
        table.assign(entry.file_id, 1, [1, 2, 3], origin=ORIGIN_MANUAL)
        items = project(table)
        assert items[0].episodes == [1, 2, 3]
        assert "S01E01-E02-E03" in items[0].new_name

    def test_specials_target_dir(self):
        table = make_table()
        entry = table.add_file(ROOT / "Specials" / "special a.mkv")
        table.assign(entry.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        items = project(table)
        assert items[0].target_dir == ROOT / "Season 00"

    def test_low_confidence_is_review(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo 3.mkv")
        table.assign(entry.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=0.5)
        items = project(table)
        assert items[0].is_episode_review

    def test_approved_review_is_ok(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo 3.mkv")
        table.assign(entry.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=0.5)
        table.set_approved(entry.file_id)
        items = project(table)
        assert items[0].status == "OK"

    def test_manual_is_never_review(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo 3.mkv")
        table.assign(entry.file_id, 1, [3], origin=ORIGIN_MANUAL)
        items = project(table)
        assert items[0].status == "OK"
        assert items[0].episode_confidence == 1.0

    def test_conflict_rows(self):
        table = make_table()
        a = table.add_file(ROOT / "Season 1" / "x.mkv")
        b = table.add_file(ROOT / "Season 2" / "x.mkv")
        table.assign(a.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        items = project(table)
        assert all(item.is_conflict for item in items)
        assert "S00E01" in items[0].status

    def test_unassigned_no_parse(self):
        table = make_table()
        entry = table.add_file(ROOT / "junk.mkv")
        table.mark_unassigned(entry.file_id, REASON_NO_PARSE)
        items = project(table)
        assert items[0].new_name is None
        assert items[0].status == "SKIP: could not parse episode number"

    def test_unassigned_special_is_unmatched_not_silent_ok(self):
        table = make_table()
        entry = table.add_file(
            ROOT / "Specials" / "mystery.mkv", folder_season=0,
        )
        table.mark_unassigned(entry.file_id, REASON_NO_TITLE_MATCH)
        items = project(table)
        assert items[0].is_unmatched
        assert not items[0].is_actionable

    def test_unassigned_extras_file_moves_to_unmatched(self):
        table = make_table()
        entry = table.add_file(
            ROOT / "Season 1" / "Extras" / "bts.mkv",
            folder_season=0, from_extras_folder=True,
        )
        table.mark_unassigned(entry.file_id, REASON_NO_TITLE_MATCH)
        items = project(table)
        assert items[0].is_unmatched
        assert items[0].new_name == "bts.mkv"
        assert items[0].target_dir == ROOT / "Unmatched" / "Extras"

    def test_every_file_yields_exactly_one_item(self):
        table = make_table()
        a = table.add_file(ROOT / "a.mkv")
        b = table.add_file(ROOT / "b.mkv")
        table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        table.mark_unassigned(b.file_id, REASON_NO_PARSE)
        items = project(table)
        assert {item.file_id for item in items} == {a.file_id, b.file_id}

    def test_ordering_by_season_episode_then_unassigned(self):
        table = make_table()
        unparsed = table.add_file(ROOT / "zzz.mkv")
        ep2 = table.add_file(ROOT / "e2.mkv")
        ep1 = table.add_file(ROOT / "e1.mkv")
        table.mark_unassigned(unparsed.file_id, REASON_NO_PARSE)
        table.assign(ep2.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(ep1.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        items = project(table)
        assert [item.file_id for item in items] == [
            ep1.file_id, ep2.file_id, unparsed.file_id,
        ]


class TestQueueBoundaryParity:
    def test_projection_feeds_rename_ops(self, tmp_path):
        """scan -> table -> projection -> RenameOps stays well-formed."""
        from plex_renamer.engine._queue_bridge import build_rename_job_from_state
        from plex_renamer.engine.models import ScanState

        root = tmp_path / "Demo Show (2020)"
        season = root / "Season 01"
        season.mkdir(parents=True)
        (season / "Demo Show S01E01.mkv").touch()
        (season / "Demo Show S01E02 - Heist.mkv").touch()

        table = make_table()
        first = table.add_file(
            season / "Demo Show S01E01.mkv", is_season_relative=True,
        )
        second = table.add_file(
            season / "Demo Show S01E02 - Heist.mkv",
            is_season_relative=True, raw_title="Heist",
        )
        table.assign(first.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.96)
        table.assign(second.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.96)

        state = ScanState(folder=root, media_info=SHOW_INFO)
        state.assignments = table
        state.preview_items = project_preview_items(
            table, show_info=SHOW_INFO, root=root, media_fields=MEDIA_FIELDS,
        )
        state.scanned = True
        checked = {0, 1}
        job = build_rename_job_from_state(
            state, tmp_path, tmp_path, checked_indices=checked,
        )
        video_ops = [op for op in job.rename_ops if op.file_type == "video"]
        assert len(video_ops) == 2
        assert all(op.new_name for op in video_ops)
        assert video_ops[0].episodes == [1]
        assert video_ops[1].episodes == [2]
