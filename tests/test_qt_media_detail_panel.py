from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobStatus
from plex_renamer.engine import CompanionFile, PreviewItem, RenameResult, ScanState
from plex_renamer.job_store import JobStore

from conftest_qt import QtSmokeBase


class QtMediaDetailPanelTests(QtSmokeBase):
    def test_media_detail_panel_caps_metadata_cache_and_can_clear_it(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        max_entries = panel._MAX_METADATA_CACHE_ENTRIES

        for index in range(max_entries + 5):
            panel._apply_payload({"title": f"Item {index}"}, None, f"token-{index}")

        self.assertEqual(len(panel._metadata_cache), max_entries)
        self.assertNotIn("token-0", panel._metadata_cache)
        self.assertIn(f"token-{max_entries + 4}", panel._metadata_cache)

        panel.clear_metadata_cache()

        self.assertEqual(len(panel._metadata_cache), 0)
        self.assertEqual(len(panel._loading_tokens), 0)
        panel.close()

    def test_media_detail_panel_uses_episode_still_and_threshold_match_text(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            settings.auto_accept_threshold = 0.6
            tmdb = MagicMock()
            tmdb.get_tv_details.return_value = {
                "status": "Returning Series",
                "networks": [{"name": "HBO"}],
                "created_by": [{"name": "Creator Name"}],
                "tagline": "Unneeded show tagline",
            }
            tmdb.fetch_poster.return_value = None

            preview = PreviewItem(
                original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
                new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                season=1,
                episodes=[1],
                status="REVIEW",
            )
            state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 102, "name": "Review Show", "year": "2024"},
                preview_items=[preview],
                scanner=type(
                    "Scanner",
                    (),
                    {
                        "episode_meta": {
                            (1, 1): {
                                "still_path": "/episode-still.jpg",
                                "overview": "Episode overview",
                                "air_date": "2024-01-01",
                                "directors": ["Director Name"],
                                "writers": ["Writer Name"],
                                "guest_stars": [{"name": "Guest Name"}],
                            }
                        }
                    },
                )(),
                scanned=True,
                confidence=0.42,
            )

            panel = MediaDetailPanel(tmdb_provider=lambda: tmdb, settings_service=settings)
            payload, _image = panel._build_payload(tmdb, state, preview, "", "", 500)

            tmdb.fetch_poster.assert_called_once_with(
                102,
                media_type="tv",
                target_width=500,
            )
            self.assertEqual(payload["artwork_mode"], "poster")
            self.assertIn(("Source", "TMDB"), payload["rows"])
            self.assertIn(("Match", "Needs Review"), payload["rows"])
            self.assertIn(("Confidence", "42%"), payload["rows"])
            self.assertIn(("Air Date", "2024-01-01"), payload["rows"])
            self.assertNotIn(("Queue", ""), payload["rows"])
            self.assertFalse(any(key in {"File", "Rename"} for key, _value in payload["rows"]))
            self.assertEqual(payload["subtitle"], "")
            self.assertNotIn(("Status", "Returning Series"), payload["rows"])
            self.assertNotIn(("Network", "HBO"), payload["rows"])
            self.assertEqual(payload["extra"], "")

            panel._current_token = "token"
            panel._apply_payload(payload, None, "token")
            rendered_rows = {
                key_label.text(): value_label.text()
                for key_label, value_label in panel._meta_rows
                if key_label.text()
            }
            self.assertEqual(rendered_rows["Source"], "TMDB")
            self.assertEqual(rendered_rows["Match"], "Needs Review")
            self.assertEqual(rendered_rows["Confidence"], "42%")
            self.assertEqual(rendered_rows["Preview"], "REVIEW")
            self.assertEqual(panel._artwork_mode, "poster")
            self.assertEqual(panel._poster.height(), 222)
            panel.close()

    def test_media_detail_panel_uses_series_poster_placeholder_for_episode_selection_without_tmdb(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        preview = PreviewItem(
            original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
            new_name="Review Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Review.Show.2024"),
            media_info={"id": 102, "name": "Review Show", "year": "2024"},
            preview_items=[preview],
            scanned=True,
            confidence=0.42,
        )

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        panel.set_selection(state, preview=preview)

        self.assertEqual(panel._artwork_mode, "poster")
        self.assertEqual(panel._poster.height(), 222)
        self.assertIsNotNone(panel._poster.pixmap())
        self.assertEqual(panel._poster.text(), "")
        panel.close()

    def test_media_detail_panel_places_actions_below_poster_and_facts_card_in_summary_column(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        panel.resize(520, 640)
        panel.show()
        self._app.processEvents()

        body_layout = panel._body.layout()
        summary_row = body_layout.itemAt(3).layout()
        poster_column = summary_row.itemAt(0).layout()
        summary_body = summary_row.itemAt(1).layout()

        self.assertGreater(body_layout.contentsMargins().left(), 0)
        self.assertIs(body_layout.itemAt(0).widget(), panel._title)
        self.assertIs(body_layout.itemAt(1).widget(), panel._queue_preflight)
        self.assertIs(body_layout.itemAt(2).widget(), panel._subtitle)
        self.assertIsNotNone(summary_row)
        self.assertIs(poster_column.itemAt(0).widget(), panel._poster)
        self.assertIs(poster_column.itemAt(1).layout().itemAt(0).widget(), panel._fix_match_button)
        self.assertIs(poster_column.itemAt(1).layout().itemAt(1).widget(), panel._primary_action_button)
        self.assertGreater(
            panel._fix_match_button.mapTo(panel._body, QPoint(0, 0)).y(),
            panel._poster.mapTo(panel._body, QPoint(0, 0)).y(),
        )
        self.assertIs(summary_body.itemAt(0).widget(), panel._facts_card)
        self.assertEqual(panel._facts_card.height(), panel._poster.height())

        panel.close()

    def test_media_detail_panel_preflight_does_not_leave_empty_subtitle_padding(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        panel.resize(520, 640)
        panel.show()
        panel._current_token = "token"
        panel._apply_payload(
            {
                "title": "Bartender (2006)",
                "subtitle": "",
                "rows": [("Confidence", "100%")],
                "overview": "",
                "extra": "",
                "artwork_mode": "poster",
            },
            None,
            "token",
        )
        panel._queue_preflight.setText("Queue preflight: 1 mapped file - 1 companion - 10 review")
        panel._queue_preflight.show()
        self._app.processEvents()

        preflight_bottom = (
            panel._queue_preflight.mapTo(panel._body, QPoint(0, 0)).y()
            + panel._queue_preflight.height()
        )
        poster_top = panel._poster.mapTo(panel._body, QPoint(0, 0)).y()

        self.assertTrue(panel._subtitle.isHidden())
        self.assertLessEqual(poster_top - preflight_bottom, 28)

        panel.close()

    def test_media_detail_panel_facts_values_render_inside_card(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        panel.resize(560, 640)
        panel.show()
        panel._current_token = "token"
        panel._apply_payload(
            {
                "title": "Bartender (2006)",
                "subtitle": "",
                "rows": [
                    ("Source", "TMDB"),
                    ("Match", "Matched"),
                    ("Confidence", "100%"),
                    ("Preview", "Review"),
                    ("Air Date", "2006-10-29"),
                    ("Seasons", "1 season - 11 episodes"),
                ],
                "overview": "",
                "extra": "",
                "artwork_mode": "poster",
            },
            None,
            "token",
        )
        self._app.processEvents()

        for key_label, value_label in panel._meta_rows:
            if not key_label.text():
                continue
            value_pos = value_label.mapTo(panel._facts_card, QPoint(0, 0))
            value_right = value_pos.x() + value_label.width()
            self.assertTrue(value_label.isVisible())
            self.assertTrue(value_label.text())
            self.assertGreater(value_pos.x(), key_label.mapTo(panel._facts_card, QPoint(0, 0)).x())
            self.assertLessEqual(value_right, panel._facts_card.width())
            self.assertGreater(value_label.width(), 24)

        panel.close()

    def test_media_detail_panel_omits_movie_queue_row(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        state = ScanState(
            folder=Path("C:/library/movies/Arrival.2016"),
            media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                    new_name="Arrival (2016).mkv",
                    target_dir=Path("C:/library/movies/Arrival (2016)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=22,
                    media_name="Arrival",
                )
            ],
            scanned=True,
            confidence=0.91,
        )

        rows = panel._fallback_rows(state, state.preview_items[0], "Already queued", "Folder rename plan: Arrival.2016 -> Arrival (2016)")

        self.assertNotIn(("Queue", "Already queued"), rows)
        self.assertNotIn(("Folder", "Folder rename plan: Arrival.2016 -> Arrival (2016)"), rows)
        self.assertNotIn(("File", "Arrival.2016.mkv"), rows)
        self.assertIn(("Confidence", "91%"), rows)

        panel.close()

    def test_media_detail_panel_fallback_rows_hide_unused_fact_slots(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        preview = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
            new_name="Example Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="OK",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[preview],
            scanned=True,
            confidence=1.0,
        )

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        panel.show()
        panel.set_selection(state, preview=preview)
        self._app.processEvents()

        visible_rows = [
            (key_label.text(), value_label.text())
            for key_label, value_label in panel._meta_rows
            if key_label.isVisible() or value_label.isVisible()
        ]

        self.assertEqual(visible_rows, [("Confidence", "100%"), ("Status", "OK")])

        panel.close()

    def test_media_detail_panel_facts_values_add_wrap_padding(self):
        from PySide6.QtWidgets import QLabel
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        _key_label, value_label = panel._meta_rows[0]
        text = "Science Fiction, Adventure, Mystery, Thriller"
        value_label.setText(text)

        base_label = QLabel("")
        base_label.setFont(value_label.font())
        base_label.setWordWrap(True)
        base_label.setMargin(value_label.margin())
        base_label.setText(text)

        self.assertGreater(value_label.heightForWidth(120), base_label.heightForWidth(120))

        panel.close()

    def test_media_detail_panel_long_title_does_not_widen_panel_minimum(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        short_payload = {
            "title": "Arrival (2016)",
            "subtitle": "Movie",
            "overview": "First contact changes everything.",
            "extra": "",
            "rows": [("Confidence", "97%")],
            "artwork_mode": "poster",
        }
        long_payload = {
            **short_payload,
            "title": "Indiana Jones and the Kingdom of the Crystal Skull (2008)",
        }

        panel = MediaDetailPanel(tmdb_provider=lambda: None)
        panel.resize(520, 640)
        panel.show()
        self._app.processEvents()

        panel._current_token = "short"
        panel._apply_payload(short_payload, None, "short")
        self._app.processEvents()
        baseline_width = panel.sizeHint().width()

        panel._current_token = "long"
        panel._apply_payload(long_payload, None, "long")
        self._app.processEvents()

        self.assertLessEqual(panel.sizeHint().width(), baseline_width)
        self.assertLessEqual(panel.minimumSizeHint().width(), 520)
        self.assertEqual(panel._body.width(), panel._scroll.viewport().width())
        self.assertLessEqual(panel._title.geometry().right(), panel._body.contentsRect().right())
        self.assertGreater(panel._title.height(), panel._title.fontMetrics().lineSpacing())

        panel.close()
