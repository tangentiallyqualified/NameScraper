"""Fallback policy for optional TV episode-evidence scoring."""

# pyright: strict

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeAlias

from ..metadata_types import ScoredMediaInfo
from ..providers import MetadataProvider, SeasonMapUnavailableError
from .models import DirectEpisodeEvidence

_log = logging.getLogger(__name__)

EpisodeBoost: TypeAlias = Callable[
    [MetadataProvider, ScoredMediaInfo, list[DirectEpisodeEvidence]],
    ScoredMediaInfo,
]


def boost_tv_scores_or_keep(
    provider: MetadataProvider,
    scored: ScoredMediaInfo,
    evidence: list[DirectEpisodeEvidence],
    boost: EpisodeBoost,
) -> ScoredMediaInfo:
    """Keep title-only scores when optional episode metadata is unavailable."""
    try:
        return boost(provider, scored, evidence)
    except SeasonMapUnavailableError:
        _log.debug(
            "Episode evidence unavailable; keeping title-only TV scores",
            exc_info=True,
        )
        return scored
