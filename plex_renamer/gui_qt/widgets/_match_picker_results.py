"""Result scoring and display helpers for MatchPickerDialog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...engine import score_results
from ._formatting import percent_text

_AUTO_ACCEPT_THRESHOLD = 0.70


@dataclass(frozen=True)
class MatchPickerResultEntry:
    index: int
    label: str
    overview: str
    highlight: bool = False


def build_match_picker_result_entries(
    results: list[dict],
    *,
    title_key: str,
    raw_name: str,
    year_hint: str | None,
    score_results_callback: Callable[[list[dict]], list[tuple[dict, float]]] | None = None,
) -> list[MatchPickerResultEntry]:
    if score_results_callback is not None:
        scored = score_results_callback(results)
    else:
        scored = score_results(results, raw_name, year_hint, title_key=title_key)
    score_map = {id(result): score for result, score in scored}

    max_score = max((score for score in score_map.values() if score is not None), default=0.0)
    rescale = 1.0 / max_score if max_score > 1.0 else 1.0

    entries: list[MatchPickerResultEntry] = []
    for index, result in enumerate(results):
        raw_score = score_map.get(id(result))
        display_score = raw_score * rescale if raw_score is not None else None
        entries.append(
            MatchPickerResultEntry(
                index=index,
                label=label_for_match_result(result, title_key, display_score),
                overview=result.get("overview", ""),
                highlight=bool(raw_score is not None and raw_score >= _AUTO_ACCEPT_THRESHOLD),
            )
        )
    return entries


def label_for_match_result(result: dict, title_key: str, score: float | None = None) -> str:
    title = result.get(title_key) or result.get("name") or result.get("title") or "Unknown"
    year = result.get("year", "")
    label = f"{title} ({year})" if year else title
    if score is not None:
        label += f" \u2014 {percent_text(score)}"
    return label
