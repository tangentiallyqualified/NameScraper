"""Unit tests for CommandGatingService — queue eligibility logic."""

from __future__ import annotations

import unittest
from pathlib import Path

from plex_renamer.app.models import QueueCommandState
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.engine import PreviewItem, ScanState, build_rename_job_from_state

_ACTION_PLAN = {
    "track_decisions": [],
    "subtitle_merges": [
        {
            "source_relative": "Show/a.eng.srt",
            "action": "merge",
            "language": "eng",
            "set_default": False,
        }
    ],
}


def _item(status: str = "OK", new_name: str = "New.mkv", original: str = "Old.mkv") -> PreviewItem:
    return PreviewItem(
        original=Path(f"C:/library/tv/Show/{original}"),
        new_name=new_name,
        target_dir=Path("C:/library/tv/Show/Season 01"),
        season=1,
        episodes=[1],
        status=status,
    )


def _state(
    *,
    items: list[PreviewItem] | None = None,
    scanned: bool = True,
    scanning: bool = False,
    queued: bool = False,
    duplicate_of: str | None = None,
    checked: bool = True,
    folder_name: str = "Show (2024)",
    show_name: str = "Show",
    year: str = "2024",
) -> ScanState:
    return ScanState(
        folder=Path(f"C:/library/tv/{folder_name}"),
        media_info={"id": 1, "name": show_name, "year": year},
        preview_items=items if items is not None else [_item()],
        scanned=scanned,
        scanning=scanning,
        queued=queued,
        duplicate_of=duplicate_of,
        checked=checked,
    )


class CommandGatingServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = CommandGatingService()

    # -- is_fully_ready_state -------------------------------------------------

    def test_plex_ready_when_all_ok_and_folder_matches(self):
        # Item must NOT be actionable (same name, same dir) for plex-ready
        item = PreviewItem(
            original=Path("C:/library/tv/Show (2024)/Season 01/Show (2024) - S01E01.mkv"),
            new_name="Show (2024) - S01E01.mkv",
            target_dir=Path("C:/library/tv/Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        state = _state(items=[item], folder_name="Show (2024)")
        self.assertTrue(self.svc.is_fully_ready_state(state))

    def test_not_plex_ready_when_folder_name_mismatches(self):
        state = _state(items=[_item(status="OK")], folder_name="Wrong Name")
        self.assertFalse(self.svc.is_fully_ready_state(state))

    def test_not_plex_ready_when_not_scanned(self):
        state = _state(scanned=False)
        self.assertFalse(self.svc.is_fully_ready_state(state))

    def test_not_plex_ready_when_queued(self):
        state = _state(queued=True)
        self.assertFalse(self.svc.is_fully_ready_state(state))

    def test_not_plex_ready_when_duplicate(self):
        state = _state(duplicate_of="other")
        self.assertFalse(self.svc.is_fully_ready_state(state))

    def test_not_plex_ready_when_review_status(self):
        state = _state(items=[_item(status="REVIEW")])
        self.assertFalse(self.svc.is_fully_ready_state(state))

    def test_not_plex_ready_when_actionable_items_exist(self):
        # An item that would rename the file is actionable
        item = _item(status="OK", new_name="Different.mkv")
        state = _state(items=[item])
        self.assertTrue(item.is_actionable)
        self.assertFalse(self.svc.is_fully_ready_state(state))

    def test_plex_ready_when_no_rename_needed(self):
        item = PreviewItem(
            original=Path("C:/library/tv/Show (2024)/Season 01/Show (2024) - S01E01.mkv"),
            new_name="Show (2024) - S01E01.mkv",
            target_dir=Path("C:/library/tv/Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        state = _state(items=[item], folder_name="Show (2024)")
        self.assertFalse(item.is_actionable)
        self.assertTrue(self.svc.is_fully_ready_state(state))

    def test_plex_ready_without_show_name_skips_folder_check(self):
        item = PreviewItem(
            original=Path("C:/library/tv/Show (2024)/Season 01/Show (2024) - S01E01.mkv"),
            new_name="Show (2024) - S01E01.mkv",
            target_dir=Path("C:/library/tv/Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Whatever Name"),
            media_info={"id": 1},
            preview_items=[item],
            scanned=True,
        )
        self.assertTrue(self.svc.is_fully_ready_state(state))

    # -- evaluate_preview_items ----------------------------------------------

    def test_selected_review_rows_block_queueing(self):
        items = [_item(status="REVIEW: episode confidence below threshold"), _item()]
        result = self.svc.evaluate_preview_items(
            items,
            selected_indices={0, 1},
            require_resolved_review=True,
        )
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_UNRESOLVED_REVIEW)
        self.assertEqual(result.selected_indices, [0])

    def test_disabled_when_scanning(self):
        result = self.svc.evaluate_preview_items([_item()], is_scanning=True)
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_SCANNING)

    def test_disabled_when_already_queued(self):
        result = self.svc.evaluate_preview_items([_item()], is_queued=True)
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_ALREADY_QUEUED)

    def test_disabled_when_unresolved_review(self):
        result = self.svc.evaluate_preview_items(
            [_item()], needs_review=True, require_resolved_review=True
        )
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_UNRESOLVED_REVIEW)

    def test_disabled_when_no_items(self):
        result = self.svc.evaluate_preview_items([])
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_NO_SELECTION)

    def test_enabled_with_selected_actionable_items(self):
        items = [_item(status="OK")]
        result = self.svc.evaluate_preview_items(items, selected_indices={0})
        self.assertTrue(result.enabled)
        self.assertEqual(result.eligible_file_count, 1)

    def test_disabled_no_selection_when_actionable_but_none_selected(self):
        items = [_item(status="OK")]
        result = self.svc.evaluate_preview_items(items, selected_indices=set())
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_NO_SELECTION)

    def test_disabled_conflict_when_only_conflict_items(self):
        items = [_item(status="CONFLICT: duplicate target")]
        result = self.svc.evaluate_preview_items(items, selected_indices={0})
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_CONFLICT)

    def test_blocked_counts_include_skip_without_conflict(self):
        items = [
            _item(status="OK"),
            _item(status="SKIP: no match", original="b.mkv"),
        ]
        result = self.svc.evaluate_preview_items(items, selected_indices={0})
        self.assertTrue(result.enabled)
        self.assertEqual(result.blocked_counts.get("skip"), 1)

    def test_selected_conflicts_block_queueing(self):
        # RC39: a live conflict blocks the whole item from queueing, even
        # when another actionable row is selected — queueing around an
        # unresolved duplicate claim ships the wrong file.
        items = [
            _item(status="OK", original="ep01.mkv", new_name="Show - S01E01.mkv"),
            _item(
                status="CONFLICT: duplicate episode claim S01E01",
                original="ep01-duplicate.mkv",
                new_name="Show - S01E01.mkv",
            ),
        ]

        result = self.svc.evaluate_preview_items(items, selected_indices={0, 1})

        self.assertFalse(result.enabled)
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_CONFLICT)
        self.assertEqual(result.blocked_counts.get("conflict"), 1)

    def test_selected_conflicts_do_not_emit_rename_ops(self):
        class _Binding:
            def __init__(self, value):
                self._value = value

            def get(self):
                return self._value

        state = _state(
            items=[
                _item(status="OK", original="ep01.mkv", new_name="Show - S01E01.mkv"),
                _item(
                    status="CONFLICT: duplicate episode claim S01E01",
                    original="ep01-duplicate.mkv",
                    new_name="Show - S01E01.mkv",
                ),
            ],
            checked=True,
        )
        state.check_vars = {"0": _Binding(True), "1": _Binding(True)}

        job = build_rename_job_from_state(
            state,
            Path("C:/library/tv"),
            Path("C:/library/tv"),
            checked_indices={0, 1},
        )

        self.assertEqual(len(job.video_ops), 1)
        self.assertEqual(
            job.video_ops[0].original_relative.replace("\\", "/"),
            "Show/ep01.mkv",
        )

    def test_no_action_needed_when_items_are_non_actionable(self):
        # Item where new_name == original name and same dir => not actionable
        item = PreviewItem(
            original=Path("C:/library/tv/Show/Season 01/Show - S01E01.mkv"),
            new_name="Show - S01E01.mkv",
            target_dir=Path("C:/library/tv/Show/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        result = self.svc.evaluate_preview_items([item], selected_indices={0})
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_NO_ACTION_NEEDED)

    # -- is_actionable_item --------------------------------------------------

    def test_is_actionable_delegates_to_preview_item(self):
        actionable = _item(status="OK")
        self.assertTrue(self.svc.is_actionable_item(actionable))

        skipped = _item(status="SKIP: no match")
        self.assertFalse(self.svc.is_actionable_item(skipped))

    # -- summarize_scan_states -----------------------------------------------

    def test_summarize_aggregates_eligible_jobs(self):
        states = [_state(), _state()]
        # Give each state checked items
        for s in states:
            s.checked = True
        result = self.svc.summarize_scan_states(states)
        self.assertTrue(result.enabled)
        self.assertEqual(result.eligible_job_count, 2)

    def test_summarize_reports_scanning_priority(self):
        states = [_state(scanning=True), _state()]
        result = self.svc.summarize_scan_states(states)
        # One is scanning, one is eligible — should still be enabled
        self.assertTrue(result.enabled)

    def test_summarize_all_scanning_disables(self):
        states = [_state(scanning=True)]
        result = self.svc.summarize_scan_states(states)
        self.assertEqual(result.command_state, QueueCommandState.DISABLED_SCANNING)

    def test_tv_show_level_queue_uses_all_actionable_files(self):
        class _Binding:
            def __init__(self, value):
                self._value = value

            def get(self):
                return self._value

            def set(self, value):
                self._value = value

        state = _state(
            items=[
                _item(original="ep01.mkv", new_name="Show - S01E01.mkv"),
                _item(original="ep02.mkv", new_name="Show - S01E02.mkv"),
            ],
            checked=True,
        )
        state.check_vars = {"0": _Binding(False), "1": _Binding(False)}

        result = self.svc.evaluate_scan_state(state, allow_show_level_queue=True)

        self.assertTrue(result.enabled)
        self.assertEqual(result.selected_indices, [0, 1])
        self.assertEqual(result.eligible_file_count, 2)

    def test_mux_only_state_is_queueable(self):
        # Round6 §1: a correctly-named item (new_name == original name, no
        # rename needed) with an action-bearing mux plan must still be
        # queueable via the show-level "select all" path.
        item = PreviewItem(
            original=Path("C:/library/tv/Show/Season 01/Show - S01E01.mkv"),
            new_name="Show - S01E01.mkv",
            target_dir=Path("C:/library/tv/Show/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        state = _state(items=[item], checked=True)
        self.assertFalse(item.is_actionable)
        state.mux_plans[0] = dict(_ACTION_PLAN)

        result = self.svc.evaluate_scan_state(state, allow_show_level_queue=True)

        self.assertEqual(result.command_state, QueueCommandState.ENABLED)
        self.assertEqual(result.selected_indices, [0])

    def test_mux_only_state_optout_not_queueable(self):
        item = PreviewItem(
            original=Path("C:/library/tv/Show/Season 01/Show - S01E01.mkv"),
            new_name="Show - S01E01.mkv",
            target_dir=Path("C:/library/tv/Show/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        state = _state(items=[item], checked=True)
        state.mux_plans[0] = dict(_ACTION_PLAN)
        state.mux_opt_outs.add(0)

        result = self.svc.evaluate_scan_state(state, allow_show_level_queue=True)

        self.assertNotEqual(result.command_state, QueueCommandState.ENABLED)

    def test_tv_show_level_queue_blocks_unresolved_episode_review(self):
        state = _state(
            items=[
                _item(original="ep01.mkv", new_name="Show - S01E01.mkv"),
                _item(
                    status="REVIEW: episode confidence below threshold",
                    original="ep02.mkv",
                    new_name="Show - S01E02.mkv",
                ),
            ],
            checked=True,
        )
        state.confidence = 1.0

        result = self.svc.evaluate_scan_state(
            state,
            require_resolved_review=True,
            allow_show_level_queue=True,
        )

        self.assertEqual(result.command_state, QueueCommandState.DISABLED_UNRESOLVED_REVIEW)
        self.assertEqual(result.reason, "Review the episode mappings before queueing.")


if __name__ == "__main__":
    unittest.main()
