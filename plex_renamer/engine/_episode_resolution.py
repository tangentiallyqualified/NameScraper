"""Shared episode resolution policy and confidence calibration.

ALL episode-level confidence constants live here. Tweak values in one
place; see docs/superpowers/specs/2026-06-11-episode-assignment-redesign-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..parsing import (
    build_tv_name,
    extract_source_title_prefix,
    normalize_for_match,
    normalize_for_specials,
)
from .episode_assignments import (
    ORIGIN_MANUAL,
    REASON_NO_PARSE,
    REASON_NO_TITLE_MATCH,
    REASON_NOT_IN_SEASON,
    EpisodeAssignmentTable,
    EpisodeSlot,
)

# ── calibration constants ───────────────────────────────────────────
STRONG_TITLE_STRENGTH = 0.85
CONF_AGREE = 0.96            # rule 1: number and title agree
CONF_TITLE_WINS = 0.90       # rule 2: strong title overrides number
CONF_WEAK_TITLE_NUMBER_CAP = 0.60   # rule 3: weak title disagreement caps number
CONF_NUMBER_RELATIVE = 0.86  # rule 4: S##E## number only
CONF_NUMBER_INFERRED = 0.50  # rule 4: bare/absolute number only
CONF_TITLE_ONLY = 0.88       # rule 5: strong title, no usable number

_TITLE_EXACT = 1.0
_TITLE_SUBSTRING = 0.90
_TITLE_PART_NUMBER = 0.80
_MIN_SUBSTRING_LEN = 6       # minimum length of the INPUT to enter substring matching
_MIN_KEY_SUBSTRING_LEN = 4   # minimum length of a KEY to participate as a candidate


@dataclass(frozen=True, slots=True)
class TitleMatch:
    episode: int
    title: str
    strength: float


@dataclass(frozen=True, slots=True)
class Resolution:
    """Outcome of resolving one file against one season's titles.

    ``episodes`` empty means unassigned; ``reason`` says why.
    """

    episodes: tuple[int, ...]
    confidence: float = 0.0
    evidence: frozenset[str] = frozenset()
    reason: str | None = None


def _strip_part_number(normalized: str) -> tuple[str, str]:
    match = re.search(r"\d{1,2}", normalized)
    if match:
        return normalized[: match.start()] + normalized[match.end():], match.group()
    return normalized, ""


def _substring_candidates(
    normalized: str,
    lookup: dict[str, tuple[int, str]],
) -> list[tuple[int, str]]:
    """Return all (episode, title) pairs where *normalized* and the key overlap.

    A key participates only when ``len(key) >= _MIN_KEY_SUBSTRING_LEN``.
    Called only when ``len(normalized) >= _MIN_SUBSTRING_LEN``.
    """
    return [
        (episode, title)
        for key, (episode, title) in lookup.items()
        if len(key) >= _MIN_KEY_SUBSTRING_LEN and (normalized in key or key in normalized)
    ]


def _has_ambiguous_title_evidence(
    raw_title: str | None,
    season_titles: dict[int, str],
) -> bool:
    """Return True when *raw_title* substring-matches 2+ distinct episode titles.

    Uses the same candidate logic as ``match_title_in_titles`` so both
    functions share one definition of 'ambiguous'.
    """
    if not raw_title or not season_titles:
        return False
    normalized = normalize_for_specials(raw_title)
    if not normalized or len(normalized) < _MIN_SUBSTRING_LEN:
        return False
    lookup = {
        normalize_for_specials(title): (episode, title)
        for episode, title in season_titles.items()
        if normalize_for_specials(title)
    }
    return len(_substring_candidates(normalized, lookup)) > 1


def match_title_in_titles(
    raw_text: str | None,
    titles: dict[int, str],
) -> TitleMatch | None:
    """Fuzzy-match *raw_text* against episode titles, with a strength score.

    Strength: 1.0 exact normalized, 0.90 unique substring, 0.80 unique
    part-number base match. Ambiguous (2+ candidates) returns None.
    """
    if not raw_text or not titles:
        return None
    normalized = normalize_for_specials(raw_text)
    if not normalized:
        return None

    lookup = {
        normalize_for_specials(title): (episode, title)
        for episode, title in titles.items()
        if normalize_for_specials(title)
    }

    hit = lookup.get(normalized)
    if hit is not None:
        return TitleMatch(episode=hit[0], title=hit[1], strength=_TITLE_EXACT)

    if len(normalized) >= _MIN_SUBSTRING_LEN:
        substring_hits = _substring_candidates(normalized, lookup)
        if len(substring_hits) == 1:
            episode, title = substring_hits[0]
            return TitleMatch(episode=episode, title=title, strength=_TITLE_SUBSTRING)
        if len(substring_hits) > 1:
            return None

    input_base, input_part = _strip_part_number(normalized)
    if input_base:
        base_hits = [
            (episode, title, key_part)
            for key, (episode, title) in lookup.items()
            for key_base, key_part in [_strip_part_number(key)]
            if key_base == input_base
        ]
        if len(base_hits) == 1:
            episode, title, _ = base_hits[0]
            return TitleMatch(episode=episode, title=title, strength=_TITLE_PART_NUMBER)
        if input_part and len(base_hits) > 1:
            by_part = [
                (episode, title)
                for episode, title, key_part in base_hits
                if key_part == input_part
            ]
            if len(by_part) == 1:
                episode, title = by_part[0]
                return TitleMatch(
                    episode=episode, title=title, strength=_TITLE_PART_NUMBER,
                )

    return None


def resolve_file(
    *,
    parsed_episodes: tuple[int, ...],
    raw_title: str | None,
    is_season_relative: bool,
    season_titles: dict[int, str],
) -> Resolution:
    """Apply the 6-rule resolution policy for one file against one season."""
    valid_numbers = tuple(e for e in parsed_episodes if e in season_titles)
    title_match = match_title_in_titles(raw_title, season_titles)
    strong_title = (
        title_match is not None and title_match.strength >= STRONG_TITLE_STRENGTH
    )

    if valid_numbers and title_match is not None:
        if title_match.episode in valid_numbers:
            return Resolution(  # rule 1
                episodes=valid_numbers,
                confidence=CONF_AGREE,
                evidence=frozenset({"number", "title-agree"}),
            )
        if strong_title:
            return Resolution(  # rule 2
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
        return Resolution(  # rule 3
            episodes=valid_numbers,
            confidence=CONF_WEAK_TITLE_NUMBER_CAP,
            evidence=frozenset({"number", "title-weak-disagree"}),
        )

    if valid_numbers:
        if _has_ambiguous_title_evidence(raw_title, season_titles):  # rule 3 (ambiguous)
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_WEAK_TITLE_NUMBER_CAP,
                evidence=frozenset({"number", "title-ambiguous"}),
            )
        # rule 4: no usable title evidence
        confidence = CONF_NUMBER_RELATIVE if is_season_relative else CONF_NUMBER_INFERRED
        evidence = {"number"}
        if is_season_relative:
            evidence.add("season-relative")
        return Resolution(
            episodes=valid_numbers,
            confidence=confidence,
            evidence=frozenset(evidence),
        )

    if title_match is not None and strong_title:  # rule 5
        return Resolution(
            episodes=(title_match.episode,),
            confidence=CONF_TITLE_ONLY,
            evidence=frozenset({"title-strong"}),
        )

    if parsed_episodes:
        return Resolution(episodes=(), reason=REASON_NOT_IN_SEASON)
    if raw_title:
        return Resolution(episodes=(), reason=REASON_NO_TITLE_MATCH)
    return Resolution(episodes=(), reason=REASON_NO_PARSE)


# ── post-resolution confidence floors and caps ──────────────────────
# Same semantics as the retired _tv_scanner_postprocess adjustments,
# rebased onto FileEntry evidence instead of filename re-parsing.
EXPLICIT_EPISODE_FLOOR = 0.86
COMPATIBLE_PREFIX_FLOOR = 0.88
EPISODE_TITLE_MATCH_FLOOR = 0.92
PLEX_READY_EPISODE_FLOOR = 1.0
EXACT_COVERAGE_FLOOR = 0.80
SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR = 0.85
NEAR_COMPLETE_COVERAGE_FLOOR = 0.74
CONTRADICTORY_PREFIX_CAP = 0.45


def _parse_air_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _expected_for_season(slots: list[EpisodeSlot]) -> set[int]:
    """Episode numbers expected for coverage, ignoring unaired episodes.

    Slots whose air date is in the future are excluded — but only when at
    least one slot in the season has already aired, so seasons with no
    air-date metadata still count in full.
    """
    today = date.today()
    aired: set[int] = set()
    saw_future = False
    for slot in slots:
        air_date = _parse_air_date(slot.air_date)
        if air_date is None:
            continue
        if air_date <= today:
            aired.add(slot.episode)
        else:
            saw_future = True
    if saw_future and aired:
        return aired
    return {slot.episode for slot in slots}


def apply_confidence_adjustments(
    table: EpisodeAssignmentTable,
    *,
    show_info: dict,
    show_match_confidence: float | None = None,
) -> None:
    """Raise/cap auto-assignment confidence from corroborating evidence."""
    show_name = show_info.get("name", "")
    show_norm = normalize_for_match(show_name)
    conflicted = table.conflicted_file_ids()

    slots_by_season: dict[int, list[EpisodeSlot]] = {}
    for slot in table.slots.values():
        slots_by_season.setdefault(slot.season, []).append(slot)
    season_slots = {
        season: _expected_for_season(slots)
        for season, slots in slots_by_season.items()
    }

    season_has_issue: set[int] = set()
    matched_by_season: dict[int, set[int]] = {}
    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if assignment.file_id in conflicted:
            season_has_issue.add(assignment.season)
            continue
        matched_by_season.setdefault(assignment.season, set()).update(
            assignment.episodes
        )

    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL or assignment.file_id in conflicted:
            continue
        entry = table.files[assignment.file_id]
        confidence = assignment.confidence

        if entry.is_season_relative:
            confidence = max(confidence, EXPLICIT_EPISODE_FLOOR)

        source_title = extract_source_title_prefix(entry.path.name)
        if source_title:
            source_norm = normalize_for_match(source_title)
            compatible = bool(show_norm) and (
                source_norm == show_norm
                or source_norm.startswith(show_norm)
                or show_norm.startswith(source_norm)
            )
            if compatible and entry.is_season_relative:
                confidence = max(confidence, COMPATIBLE_PREFIX_FLOOR)
            if not compatible:
                confidence = min(confidence, CONTRADICTORY_PREFIX_CAP)

        first_slot = table.slots.get((assignment.season, assignment.episodes[0]))
        if (
            entry.raw_title
            and first_slot is not None
            and first_slot.title
            and normalize_for_specials(entry.raw_title)
            == normalize_for_specials(first_slot.title)
        ):
            confidence = max(confidence, EPISODE_TITLE_MATCH_FLOOR)

        titles = [
            (table.slots[(assignment.season, episode)].title or f"Episode {episode}")
            for episode in assignment.episodes
        ]
        expected_name = build_tv_name(
            show_name,
            show_info.get("year", ""),
            assignment.season,
            list(assignment.episodes),
            titles,
            entry.path.suffix,
        )
        if expected_name == entry.path.name:
            confidence = max(confidence, PLEX_READY_EPISODE_FLOOR)

        table.set_confidence(assignment.file_id, confidence)

    single_regular_season = (
        sum(1 for season in season_slots if season > 0) == 1
    )
    perfect_show = show_match_confidence is not None and show_match_confidence >= 1.0

    for season, expected in season_slots.items():
        if season == 0 or season in season_has_issue or not expected:
            continue
        matched = matched_by_season.get(season, set())
        missing = expected - matched
        if matched == expected:
            floor = EXACT_COVERAGE_FLOOR
            if single_regular_season and perfect_show:
                floor = SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR
        elif matched and matched <= expected and (
            len(missing) <= 1 or len(matched) / max(len(expected), 1) >= 0.90
        ):
            floor = NEAR_COMPLETE_COVERAGE_FLOOR
        else:
            continue
        for assignment in table.assignments():
            if (
                assignment.season == season
                and assignment.origin != ORIGIN_MANUAL
                and assignment.file_id not in conflicted
            ):
                table.set_confidence(
                    assignment.file_id, max(assignment.confidence, floor),
                )
