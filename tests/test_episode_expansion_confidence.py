from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from conftest_qt import QtSmokeBase

from plex_renamer.app.models import EpisodeGuideRow
from plex_renamer.engine import ScanState
from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard


class _EpisodeCardView(Protocol):
    def show_episode(self, state: ScanState, row: EpisodeGuideRow) -> None: ...

    def status_pill_text(self) -> str: ...


class EpisodeExpansionConfidenceTests(QtSmokeBase):
    def test_card_handles_non_percent_and_invalid_confidence_labels(self) -> None:
        card = EpisodeExpansionCard()
        self.addCleanup(card.close)
        card_view = cast(_EpisodeCardView, card)
        state = ScanState(folder=Path("C:/library/tv/Example"), media_info={})

        card_view.show_episode(
            state,
            EpisodeGuideRow(season=1, episode=1, status="Review", confidence_label="unknown"),
        )
        self.assertEqual(card_view.status_pill_text(), "REVIEW")

        card_view.show_episode(
            state,
            EpisodeGuideRow(season=1, episode=1, status="Review", confidence_label="invalid%"),
        )
        self.assertEqual(card_view.status_pill_text(), "REVIEW invalid%")
