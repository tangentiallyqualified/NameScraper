# tests/test_episode_table_delegate.py
"""EpisodeTableDelegate/View painting smoke, size hints, hit-testing."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state

# A rename preview whose rendered width exceeds the 700px test view under any
# font, so truncation checks don't depend on platform font metrics.
_UNFITTABLE_RENAME = (
    "Show - S01E02 - "
    + "A Very Long Episode Title That Cannot Possibly Fit " * 20
    + ".mkv"
)


class EpisodeTableDelegateTests(QtSmokeBase):
    def _view(self, state, guide):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(700, 500)
        return view, model, delegate

    def test_size_hints_by_kind(self):
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets import _episode_table_delegate as d

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        self.assertEqual(view.sizeHintForRow(0), _scale.px(30))     # section label
        self.assertEqual(view.sizeHintForRow(2), _scale.px(30))     # season header
        self.assertEqual(view.sizeHintForRow(3), _scale.px(68))     # episode w/ filename + subtitle line
        # row 4 ("Two") is Review and adjacent to row 5's Missing File slot
        # (E02/E03) -> its strip carries FOUR actions (approve, reassign,
        # assign_to_more, unassign) stacked in a column below the pill
        # (geometry contract v2) -- height is whichever is taller, the
        # double-line text block or the pill + 4-button column.
        gap = _scale.px(4)
        pill_h = _scale.px(d._PILL_H_U)
        column_height = gap + pill_h + 4 * (pill_h + gap) + gap
        self.assertEqual(view.sizeHintForRow(4), max(_scale.px(52), column_height))
        self.assertEqual(view.sizeHintForRow(5), _scale.px(34))     # ghost (no filename)

    def test_subtitle_row_is_taller_than_plain_row(self):
        from plex_renamer.gui_qt import _scale

        state, guide = _guide_state()
        # Neutralize the Task 6 action strip so this stays the original
        # triple-line vs double-line comparison: make "Two" Mapped (Review
        # rows always carry a strip) and drop the season's Missing File
        # slot (a Mapped row adjacent to one would get assign_to_more).
        guide.rows[1].status = "Mapped"
        guide.rows[2].status = "Mapped"
        view, model, delegate = self._view(state, guide)
        # row 3 ("One") has a subtitle companion -> triple-line height;
        # row 4 ("Two") has none -> plain double-line height.
        self.assertEqual(view.sizeHintForRow(3), _scale.px(68))
        self.assertEqual(view.sizeHintForRow(4), _scale.px(52))
        self.assertGreater(view.sizeHintForRow(3), view.sizeHintForRow(4))

    def test_render_grab(self):
        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        self.assertFalse(view.grab().toImage().isNull())
        view.close()

    def test_persistent_editor_parents_into_viewport(self):
        """An unparented editor is a detached top-level window: the row paints
        as a blank gap while the card floats at desktop coordinates."""
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()

        def provider(index):
            card = EpisodeExpansionCard()
            card.show_episode(state, model.guide_row_at(index.row()))
            return card

        delegate.expansion_card_provider = provider
        model.set_expanded_row(3)
        view.openPersistentEditor(model.index(3, 0))
        card = view.indexWidget(model.index(3, 0))
        self.assertIsNotNone(card)
        self.assertFalse(card.isWindow())
        self.assertIs(card.window(), view.window())
        view.close()

    def test_chevron_click_emits_without_selection(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        hits: list[int] = []
        view.chevron_clicked.connect(lambda index: hits.append(index.row()))
        rect = view.visualRect(model.index(3, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, delegate.chevron_rect(rect).center())
        self.assertEqual(hits, [3])
        self.assertNotEqual(view.currentIndex().row(), 3)
        view.close()

    def test_header_click_emits_section_key(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        keys: list[str] = []
        view.header_clicked.connect(keys.append)
        rect = view.visualRect(model.index(2, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(keys, ["episode-guide-season:1"])
        view.close()

    def test_enter_emits_expand_on_current_row(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        expanded: list[int] = []
        view.expand_key_pressed.connect(lambda index: expanded.append(index.row()))
        view.setCurrentIndex(model.index(3, 0))
        QTest.keyClick(view, Qt.Key.Key_Return)
        self.assertEqual(expanded, [3])
        view.close()

    def test_bulk_hint_click_emits_signal(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        guide.rows[1].status = "Mapped"
        view, model, delegate = self._view(state, guide)
        model.set_filter_mode("problems")
        view.show()
        fired: list[bool] = []
        view.bulk_hint_clicked.connect(lambda: fired.append(True))
        rect = view.visualRect(model.index(0, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(fired, [True])
        view.close()


class ActionStripTests(QtSmokeBase):
    """Task 6: collapsed-row action-strip buttons on Review/Mapped rows."""

    def _view_with_rows(self, statuses):
        from plex_renamer.app.models.state_models import (
            EpisodeGuide, EpisodeGuideRow, EpisodeGuideSummary,
        )
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 7, "name": "Show", "year": "2020"})
        state.scanned = True
        rows = [
            EpisodeGuideRow(season=1, episode=i, title=f"Ep{i}", status=status)
            for i, status in enumerate(statuses, start=1)
        ]
        guide = EpisodeGuide(rows=rows, summary=EpisodeGuideSummary())
        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(700, 500)
        return view, model, delegate

    def _index_for_status(self, model, status):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        for row in range(model.rowCount()):
            if model.row_kind_at(row) != "episode":
                continue
            if model.index(row, 0).data(ROW_DATA_ROLE).status_text == status:
                return model.index(row, 0)
        raise AssertionError(f"no episode row with status {status!r}")

    def _option(self):
        from PySide6.QtWidgets import QStyleOptionViewItem

        return QStyleOptionViewItem()

    def _click(self, view, pos):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)

    def test_actionable_row_is_taller_and_buttons_hit(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        view, model, delegate = self._view_with_rows(statuses=["Review", "Mapped"])
        view.show()
        review_index = self._index_for_status(model, "Review")
        mapped_index = self._index_for_status(model, "Mapped")
        self.assertGreater(
            delegate.sizeHint(self._option(), review_index).height(),
            delegate.sizeHint(self._option(), mapped_index).height(),
        )
        rects = delegate.inline_action_rects(view.visualRect(review_index),
                                             review_index.data(ROW_DATA_ROLE))
        self.assertEqual([a for a, _r in rects], ["approve", "reassign", "unassign"])
        fired = []
        view.inline_action_clicked.connect(lambda idx, aid: fired.append(aid))
        self._click(view, rects[0][1].center())
        self.assertEqual(fired, ["approve"])
        view.close()

    def test_mapped_row_adjacent_to_missing_gets_assign_to_more_strip(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        view, model, delegate = self._view_with_rows(statuses=["Mapped", "Missing File"])
        view.show()
        mapped_index = self._index_for_status(model, "Mapped")
        rects = delegate.inline_action_rects(view.visualRect(mapped_index),
                                              mapped_index.data(ROW_DATA_ROLE))
        self.assertEqual([a for a, _r in rects], ["assign_to_more"])
        view.close()

    def test_non_actionable_row_height_unchanged(self):
        from plex_renamer.gui_qt import _scale

        view, model, delegate = self._view_with_rows(statuses=["Conflict"])
        view.show()
        conflict_index = self._index_for_status(model, "Conflict")
        self.assertEqual(delegate.sizeHint(self._option(), conflict_index).height(), _scale.px(34))
        view.close()

    def test_approve_button_uses_accent_others_neutral(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        row_data = EpisodeRowData(
            kind="episode", title="S01E01", status_text="Review", status_tone="warning",
            inline_actions=(("approve", "Approve"), ("reassign", "Reassign…"), ("unassign", "Unassign")),
        )
        rects = delegate.inline_action_rects(view.visualRect(model.index(0, 0)), row_data)
        ids = [a for a, _r in rects]
        self.assertEqual(ids, ["approve", "reassign", "unassign"])
        view.close()

    def test_action_column_only_squeezes_text_when_wider_than_pill(self):
        """Geometry contract v2 (Task 5): the button column stacks *below*
        the pill now, not beside it, so its mere presence must not squeeze
        the title the way the old (round5) inline strip did -- only a
        column genuinely wider than the pill cluster should narrow
        text_right_edge. This directly protects the fix for the reported
        bug (buttons squeezing the title at narrow widths)."""
        from PySide6.QtCore import QRect
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        base = dict(kind="episode", title="S01E01 · Pilot", status_text="Review",
                    status_tone="warning", confidence_pct=61, filename="s01e01.mkv")
        without_strip = EpisodeRowData(**base)
        narrow_strip = EpisodeRowData(
            **base,
            inline_actions=(("approve", "Approve"), ("reassign", "Reassign…"), ("unassign", "Unassign")),
        )
        wide_strip = EpisodeRowData(
            **base,
            inline_actions=(("wide", "A Very Long Action Label That Dwarfs The Pill"),),
        )
        rect = QRect(0, 0, 600, 96)
        metrics = view.fontMetrics()
        baseline_edge = delegate.text_right_edge(rect, without_strip, metrics)
        # Buttons narrower than the pill: stacking them below it must not
        # cost the title any horizontal width.
        self.assertEqual(delegate.text_right_edge(rect, narrow_strip, metrics), baseline_edge)
        # A button wider than the pill DOES need to squeeze the title,
        # since the (right-aligned) column then extends further left.
        self.assertLess(delegate.text_right_edge(rect, wide_strip, metrics), baseline_edge)
        # And the strip really is present for the actionable variant.
        self.assertEqual(len(delegate.inline_action_rects(rect, narrow_strip)), 3)
        view.close()

    def test_pill_and_inline_actions_top_aligned_share_baseline(self):
        """Geometry contract v2 (Task 5): the pill stays top-anchored (not
        vertically centered), but the action buttons no longer share its
        baseline -- they stack in a column strictly below it instead."""
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        row_data = EpisodeRowData(
            kind="episode", title="S01E01 · Pilot", status_text="Review",
            status_tone="warning", confidence_pct=61, filename="s01e01.mkv",
            inline_actions=(("approve", "Approve"), ("reassign", "Reassign"), ("unassign", "Unassign")),
        )
        option_rect = QRect(0, 0, 600, 96)
        metrics = view.fontMetrics()
        pill = delegate._pill_rect(option_rect, row_data, metrics)
        self.assertEqual(pill.y(), option_rect.y() + _scale.px(4))
        rects = delegate.inline_action_rects(option_rect, row_data)
        self.assertTrue(rects, "review rows must expose inline actions")
        for _aid, rect in rects:
            self.assertGreaterEqual(rect.y(), pill.bottom() + _scale.px(4) - 1)
            self.assertNotEqual(rect.y(), pill.y())
            self.assertEqual(rect.height(), pill.height())
        view.close()

    def test_no_overlap_between_buttons_and_pill(self):
        """Geometry contract v2 (Task 5): the button column sits entirely
        below the pill (never beside it and never overlapping it), and the
        title's right edge stops before whichever control -- pill or
        column -- sits leftmost."""
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        row_data = EpisodeRowData(
            kind="episode", title="S01E01 · Pilot", status_text="Review",
            status_tone="warning", confidence_pct=61, filename="s01e01.mkv",
            inline_actions=(("approve", "Approve"), ("reassign", "Reassign"), ("unassign", "Unassign")),
        )
        option_rect = QRect(0, 0, 600, 96)
        metrics = view.fontMetrics()
        pill = delegate._pill_rect(option_rect, row_data, metrics)
        rects = [r for _aid, r in delegate.inline_action_rects(option_rect, row_data)]
        prev_bottom = pill.bottom()
        for rect in rects:
            self.assertGreater(rect.y(), prev_bottom, f"{rect} overlaps/precedes {prev_bottom=}")
            prev_bottom = rect.bottom()
        leftmost = min([pill.x()] + [r.x() for r in rects])
        self.assertLessEqual(
            delegate.text_right_edge(option_rect, row_data, metrics), leftmost,
        )
        view.close()

    def test_action_buttons_stack_vertically_under_pill(self):
        """Geometry contract v2 (Task 5): buttons stack one per line under
        the pill, right-aligned to it, uniform width, px(4) gaps."""
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        row_data = EpisodeRowData(
            kind="episode", title="S01E01 · Pilot", status_text="Review",
            status_tone="warning", confidence_pct=61, filename="s01e01.mkv",
            inline_actions=(("approve", "Approve"), ("reassign", "Reassign"), ("unassign", "Unassign")),
            mux_active=True,
        )
        option_rect = QRect(0, 0, 600, 96)
        metrics = view.fontMetrics()
        pill = delegate._pill_rect(option_rect, row_data, metrics)
        rects = [r for _aid, r in delegate.inline_action_rects(option_rect, row_data)]
        self.assertEqual(len(rects), 3)
        prev_bottom = pill.bottom()
        for rect in rects:
            self.assertGreaterEqual(rect.y(), prev_bottom + _scale.px(4) - 1)  # below the previous element
            self.assertEqual(rect.right(), pill.right())                       # right-aligned column
            prev_bottom = rect.bottom()
        widths = {r.width() for r in rects}
        self.assertEqual(len(widths), 1)                                       # uniform width
        view.close()

    def test_text_right_edge_clears_the_column(self):
        """Geometry contract v2 (Task 5): text_right_edge clears the pill,
        the MUX chip, and the button column -- whichever sits leftmost."""
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        row_data = EpisodeRowData(
            kind="episode", title="S01E01 · Pilot", status_text="Review",
            status_tone="warning", confidence_pct=61, filename="s01e01.mkv",
            inline_actions=(("approve", "Approve"), ("reassign", "Reassign"), ("unassign", "Unassign")),
            mux_active=True,
        )
        option_rect = QRect(0, 0, 600, 96)
        metrics = view.fontMetrics()
        pill = delegate._pill_rect(option_rect, row_data, metrics)
        chip = delegate.mux_chip_rect(option_rect, row_data, metrics)
        rects = [r for _aid, r in delegate.inline_action_rects(option_rect, row_data)]
        edge = delegate.text_right_edge(option_rect, row_data, metrics)
        leftmost = min([pill.x()] + [r.x() for r in rects] + ([chip.x()] if chip.isValid() else []))
        self.assertLessEqual(edge, leftmost)
        view.close()

    def test_size_hint_fits_the_column(self):
        """Geometry contract v2 (Task 5): sizeHint grows to fit the pill +
        n-button column when that's taller than the text block, with no
        leftover flat _ACTION_STRIP_U reservation."""
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets import _episode_table_delegate as d
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        view, model, delegate = self._view_with_rows(statuses=["Review"])
        index = self._index_for_status(model, "Review")
        n = len(index.data(ROW_DATA_ROLE).inline_actions)
        self.assertGreater(n, 0)
        hint = delegate.sizeHint(self._option(), index)
        gap = _scale.px(4)
        pill_h = _scale.px(d._PILL_H_U)
        expected_min = gap + pill_h + n * (pill_h + gap) + gap
        self.assertGreaterEqual(hint.height(), expected_min)
        view.close()


class MovieRowFlatTests(QtSmokeBase):
    def test_movie_file_not_a_chevron_kind(self):
        from plex_renamer.gui_qt.widgets import _episode_table_delegate as d
        self.assertNotIn("movie-file", d._CHEVRON_KINDS)

    def _movie_view(self, previews):
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        state = ScanState(folder=Path("C:/lib/Movie"),
                           media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        state.preview_items = previews
        model = EpisodeTableModel(media_type="movie")
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="movie")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(700, 500)
        return view, model, delegate

    def test_movie_file_rows_are_double_line_with_target(self):
        """Round5 spec 2b regression: movie-file rows set title+target (no
        filename) but "movie-file" was never a double-line kind, so the
        rename-preview second line never painted. A row with a rename
        target must be taller than one without (e.g. an unrenamed
        duplicate)."""
        from PySide6.QtWidgets import QStyleOptionViewItem
        from plex_renamer.engine.models import PreviewItem

        with_target = PreviewItem(
            original=Path("C:/lib/Movie/dune.mkv"), new_name="Dune (2021).mkv",
            target_dir=None, season=None, episodes=[], status="OK", media_type="movie",
        )
        without_target = PreviewItem(
            original=Path("C:/lib/Movie/dune copy.mkv"), new_name=None,
            target_dir=None, season=None, episodes=[],
            status="DUPLICATE: copy of dune.mkv", media_type="movie",
        )
        view, model, delegate = self._movie_view([with_target, without_target])
        option = QStyleOptionViewItem()
        hint = delegate.sizeHint(option, model.index(0, 0))
        single = delegate.sizeHint(option, model.index(1, 0))
        self.assertGreater(hint.height(), single.height())
        view.close()


class ChevronGlyphTests(QtSmokeBase):
    def test_row_chevron_matches_expansion_collapse_glyph_family(self):
        # Task 5: the row chevron and the expansion card's collapse button
        # must share the same triangular glyph family (solid, not angle-bracket).
        import inspect
        from plex_renamer.gui_qt.widgets import _episode_table_delegate as d

        source = inspect.getsource(d.EpisodeTableDelegate._paint_chevron)
        self.assertIn('"▸"', source)
        self.assertNotIn('"›"', source)


class PillConfidenceTests(QtSmokeBase):
    def _delegate(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        view = EpisodeTableView()
        return EpisodeTableDelegate(view, media_type="tv")

    def _row(self, **kw):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        base = dict(kind="episode", title="S01E01 · Pilot", status_text="Review",
                    status_tone="warning", confidence_pct=72)
        base.update(kw)
        return EpisodeRowData(**base)

    def test_review_pill_text_includes_percent(self):
        d = self._delegate()
        self.assertEqual(d.pill_text(self._row(confidence_pct=72)), "Review 72%")

    def test_matched_pill_text_includes_percent(self):
        d = self._delegate()
        self.assertEqual(
            d.pill_text(self._row(status_text="Matched", status_tone="success", confidence_pct=96)),
            "Matched 96%")

    def test_review_pill_tone_follows_band(self):
        d = self._delegate()
        self.assertEqual(d.pill_tone(self._row(confidence_pct=90)), "success")
        self.assertEqual(d.pill_tone(self._row(confidence_pct=60)), "warning")
        self.assertEqual(d.pill_tone(self._row(confidence_pct=30)), "error")

    def test_missing_file_pill_text_unchanged(self):
        d = self._delegate()
        r = self._row(status_text="Missing File", status_tone="muted", confidence_pct=None)
        self.assertEqual(d.pill_text(r), "Missing File")
        self.assertEqual(d.pill_tone(r), "muted")

    def test_mapped_pill_text_includes_percent(self):
        d = self._delegate()
        r = self._row(status_text="Mapped", status_tone="success", confidence_pct=93)
        self.assertEqual(d.pill_text(r), "Mapped 93%")


class MuxChipTests(QtSmokeBase):
    """Round5 spec 1b: collapsed-row MUX chip painted left of the pill."""

    def _delegate(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        view = EpisodeTableView()
        return EpisodeTableDelegate(view, media_type="tv")

    def _row(self, **kw):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        base = dict(kind="episode", title="S01E01 · Pilot", status_text="Mapped",
                    status_tone="success", confidence_pct=93, mux_active=True)
        base.update(kw)
        return EpisodeRowData(**base)

    def test_mux_chip_painted_left_of_pill_when_active(self):
        from PySide6.QtCore import QRect

        d = self._delegate()
        option_rect = QRect(0, 0, 600, 52)
        metrics = d._view.fontMetrics()
        row_data = self._row(mux_active=True)
        chip = d.mux_chip_rect(option_rect, row_data, metrics)
        pill = d._pill_rect(option_rect, row_data, metrics)
        self.assertTrue(chip.isValid())
        self.assertLess(chip.right(), pill.x())
        # Round5 §3: chip shares the pill's top-anchored baseline.
        self.assertEqual(chip.y(), pill.y())
        self.assertEqual(chip.height(), pill.height())

        inactive = self._row(mux_active=False)
        self.assertFalse(d.mux_chip_rect(option_rect, inactive, metrics).isValid())

    def test_mux_chip_sits_left_of_legacy_inline_action(self):
        """Missing File rows keep their legacy inline-action button left of
        the pill; the chip must sit further left of that button, not just
        the pill (brief: reuse inline_action_rects' left-anchor logic)."""
        from PySide6.QtCore import QRect

        d = self._delegate()
        option_rect = QRect(0, 0, 600, 52)
        metrics = d._view.fontMetrics()
        row_data = self._row(status_text="Missing File", status_tone="muted",
                              confidence_pct=None, mux_active=True)
        chip = d.mux_chip_rect(option_rect, row_data, metrics)
        action_rect = d.inline_action_rects(option_rect, row_data)[0][1]
        self.assertTrue(chip.isValid())
        self.assertLess(chip.right(), action_rect.x())

    def test_text_right_edge_stops_before_mux_chip(self):
        from PySide6.QtCore import QRect

        d = self._delegate()
        option_rect = QRect(0, 0, 600, 52)
        metrics = d._view.fontMetrics()
        active = self._row(mux_active=True)
        inactive = self._row(mux_active=False)
        chip = d.mux_chip_rect(option_rect, active, metrics)
        self.assertLess(d.text_right_edge(option_rect, active, metrics), chip.x())
        self.assertGreater(
            d.text_right_edge(option_rect, inactive, metrics),
            d.text_right_edge(option_rect, active, metrics),
        )


class StatusWashTests(QtSmokeBase):
    def test_status_wash_tokens_cover_review_and_conflict(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import _STATUS_WASH
        self.assertEqual(_STATUS_WASH["Review"], ("warning", 0.05))
        self.assertEqual(_STATUS_WASH["Conflict"], ("error", 0.06))
        self.assertEqual(_STATUS_WASH["CONFLICT"], ("error", 0.06))


class HelpEventTests(QtSmokeBase):
    def test_tooltip_only_when_elided(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
        view = EpisodeTableView()
        d = EpisodeTableDelegate(view, media_type="tv")
        # narrow width -> elided -> tooltip; wide width -> not elided -> no tooltip
        self.assertTrue(d._preview_is_truncated("A very long rename preview.mkv", width=20))
        self.assertFalse(d._preview_is_truncated("x.mkv", width=100000))

    def _view(self, state, guide, *, width=700):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(width, 500)
        return view, model, delegate

    def _help_event_result(self, view, delegate, index):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtWidgets import QStyleOptionViewItem

        rect = view.visualRect(index)
        option = QStyleOptionViewItem()
        option.rect = rect
        pos = rect.center()
        event = QHelpEvent(QEvent.Type.ToolTip, pos, view.viewport().mapToGlobal(pos))
        return delegate.helpEvent(event, view, option, index)

    def test_help_event_suppressed_when_row_expanded(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EXPANDED_ROLE

        # Same long tooltip + squeezed-width view as the "shown when
        # truncated" case below: without the EXPANDED_ROLE guard this would
        # also be truncated and helpEvent would return True, so expansion is
        # the only thing this test can be asserting on.
        state, guide = _guide_state()
        guide.rows[1].target_rename = _UNFITTABLE_RENAME
        view, model, delegate = self._view(state, guide, width=700)
        view.show()
        index = model.index(4, 0)
        model.set_expanded_row(4)
        self.assertTrue(index.data(EXPANDED_ROLE))
        handled = self._help_event_result(view, delegate, index)
        self.assertFalse(handled)
        view.close()

    def test_help_event_shown_when_collapsed_and_truncated(self):
        # Row 4 ("Two") carries a four-button action strip (round5 Task 4:
        # the strip now shares the pill's top-anchored row and reserves
        # horizontal text width), so the available title width is well under
        # the 700px view -- give it a rename preview that cannot fit ->
        # helpEvent must show it.
        state, guide = _guide_state()
        guide.rows[1].target_rename = _UNFITTABLE_RENAME
        view, model, delegate = self._view(state, guide, width=700)
        view.show()
        index = model.index(4, 0)
        handled = self._help_event_result(view, delegate, index)
        self.assertTrue(handled)
        view.close()

    def test_help_event_hidden_when_collapsed_and_fitting(self):
        # Row 3 ("One") keeps its short default target_rename and the view
        # is wide, so the preview fits -> helpEvent must not show a tooltip.
        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide, width=700)
        view.show()
        index = model.index(3, 0)
        handled = self._help_event_result(view, delegate, index)
        self.assertFalse(handled)


class InlineMissingActionTests(QtSmokeBase):
    def test_missing_row_reports_inline_action_rect(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        view = EpisodeTableView()
        d = EpisodeTableDelegate(view, media_type="tv")
        row = EpisodeRowData(kind="episode", title="S01E03", status_text="Missing File", status_tone="muted")
        rects = d.inline_action_rects(QRect(0, 0, 400, 34), row)
        self.assertEqual(len(rects), 1)
        rect = rects[0][1]
        self.assertTrue(rect.isValid() and rect.width() > 0)

    def test_non_missing_row_has_no_inline_action(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        view = EpisodeTableView()
        d = EpisodeTableDelegate(view, media_type="tv")
        row = EpisodeRowData(kind="episode", title="S01E01", status_text="Review", status_tone="warning")
        self.assertEqual(d.inline_action_rects(QRect(0, 0, 400, 34), row), [])
        view.close()


class InlineAssignUnmappedActionTests(QtSmokeBase):
    def _delegate(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        view = EpisodeTableView()
        return EpisodeTableDelegate(view, media_type="tv")

    def test_unmapped_row_has_inline_assign_rect(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        d = self._delegate()
        row = EpisodeRowData(kind="unmapped", title="a.mkv", status_text="Unassigned",
                             status_tone="warning", filename="a.mkv", detail="reason")
        rects = d.inline_action_rects(QRect(0, 0, 600, 52), row)
        self.assertEqual(len(rects), 1)
        self.assertTrue(rects[0][1].isValid())

    def test_duplicate_row_has_inline_assign_rect(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        d = self._delegate()
        row = EpisodeRowData(kind="duplicate", title="b.mkv", status_text="Duplicate",
                             status_tone="muted", filename="b.mkv", detail="reason")
        rects = d.inline_action_rects(QRect(0, 0, 600, 52), row)
        self.assertEqual(len(rects), 1)
        self.assertTrue(rects[0][1].isValid())

    def test_mapped_row_has_no_inline_assign_rect(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        d = self._delegate()
        row = EpisodeRowData(kind="episode", title="S01E01", status_text="Mapped",
                             status_tone="success", confidence_pct=90)
        self.assertEqual(d.inline_action_rects(QRect(0, 0, 600, 52), row), [])

    def test_unmapped_action_label_differs_from_missing_file(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import _row_inline_actions
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        unmapped_row = EpisodeRowData(kind="unmapped", title="a.mkv", status_text="Unassigned",
                                      status_tone="warning", filename="a.mkv", detail="reason")
        missing_row = EpisodeRowData(kind="episode", title="S01E03", status_text="Missing File",
                                     status_tone="muted")
        self.assertEqual(_row_inline_actions(unmapped_row), (("assign_unmapped", "Assign…"),))
        self.assertEqual(_row_inline_actions(missing_row), (("assign_file", "Assign file…"),))

    def test_unmapped_row_inline_action_click_emits_assign_unmapped(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        view, model, delegate = EpisodeTableDelegateTests()._view(state, guide)
        view.show()
        hits: list[tuple[int, str]] = []
        view.inline_action_clicked.connect(lambda index, action_id: hits.append((index.row(), action_id)))
        unmapped_row = next(
            row for row in range(model.rowCount())
            if model.row_kind_at(row) == "unmapped"
        )
        row_data = model.index(unmapped_row, 0).data(ROW_DATA_ROLE)
        rect = view.visualRect(model.index(unmapped_row, 0))
        action_rect = delegate.inline_action_rects(rect, row_data)[0][1]
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, action_rect.center())
        self.assertEqual(hits, [(unmapped_row, "assign_unmapped")])
        view.close()


class InlineActionTextWidthTest(QtSmokeBase):
    def test_text_right_edge_stops_before_inline_action(self):
        from PySide6.QtCore import QRect
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData

        view = EpisodeTableView()
        self.addCleanup(view.deleteLater)
        delegate = EpisodeTableDelegate(view, media_type="tv")
        row_data = EpisodeRowData(
            kind="unmapped", title="X" * 300, status_text="Unassigned",
            status_tone="warning", filename="x.mkv", detail="reason",
        )
        rect = QRect(0, 0, 600, 52)
        action_rect = delegate.inline_action_rects(rect, row_data)[0][1]
        text_right = delegate.text_right_edge(rect, row_data, view.fontMetrics())
        self.assertLessEqual(text_right, action_rect.x())
