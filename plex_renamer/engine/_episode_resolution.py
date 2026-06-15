"""Shared episode resolution policy and confidence calibration.

ALL episode-level confidence constants live here. Tweak values in one
place; see docs/superpowers/specs/2026-06-11-episode-assignment-redesign-design.md.
"""

from __future__ import annotations

import itertools
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
    ORIGIN_AUTO,
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
CONF_SPECIAL_NUMBER_ONLY = 0.50  # season-0 number with no title match -> REVIEW
CONF_TITLE_WINS_INEXACT = 0.70  # strong-but-inexact title overrides number -> REVIEW
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


# Segment separators inside a combined multi-episode title
# ("Barbeque Story & Waiter, There's A Baby" / "Foo and Bar"). Note "and"
# also appears INSIDE titles ("Armed and Dangerous"), so segmentation tries
# every grouping rather than splitting greedily.
_SEGMENT_SEP = re.compile(r"\s*(?:&|/|,|\band\b)\s*", re.IGNORECASE)
_MAX_SEGMENT_ATOMS = 12  # guard against combinatorial blowups on odd titles


def _segment_atom_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the atoms lying between segment separators."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for sep in _SEGMENT_SEP.finditer(text):
        spans.append((pos, sep.start()))
        pos = sep.end()
    spans.append((pos, len(text)))
    return spans


def match_segmented_title_run(
    raw_title: str | None,
    titles: dict[int, str],
    expected_count: int,
) -> tuple[int, ...] | None:
    """Resolve a combined multi-segment title into an episode run by titles.

    Splits *raw_title* on segment separators and merges adjacent atoms into
    exactly *expected_count* groups so each group is an EXACT TMDB title for a
    distinct episode. Because separators ("and"/","/"&") also occur *inside*
    titles, every grouping is tried; the run is accepted only when exactly one
    grouping matches and the episodes form a contiguous run. Otherwise None,
    and the caller falls back to the number-based rules.
    """
    if not raw_title or expected_count < 2 or not titles:
        return None
    spans = _segment_atom_spans(raw_title)
    atom_count = len(spans)
    if atom_count < expected_count or atom_count > _MAX_SEGMENT_ATOMS:
        return None
    # Exact normalized title -> episode, excluding duplicate titles (a
    # duplicated title can't disambiguate which episode a segment means).
    seen: dict[str, int] = {}
    duplicates: set[str] = set()
    for episode, title in titles.items():
        norm = normalize_for_specials(title)
        if not norm:
            continue
        if norm in seen:
            duplicates.add(norm)
        else:
            seen[norm] = episode
    norm_to_episode = {n: e for n, e in seen.items() if n not in duplicates}
    if not norm_to_episode:
        return None
    matched_runs: set[tuple[int, ...]] = set()
    for cuts in itertools.combinations(range(1, atom_count), expected_count - 1):
        bounds = (0, *cuts, atom_count)
        episodes: list[int] = []
        for group in range(expected_count):
            lo, hi = bounds[group], bounds[group + 1]
            piece = raw_title[spans[lo][0]:spans[hi - 1][1]]
            episode = norm_to_episode.get(normalize_for_specials(piece))
            if episode is None:
                break
            episodes.append(episode)
        else:
            if len(set(episodes)) == expected_count:
                matched_runs.add(tuple(sorted(episodes)))
    if len(matched_runs) != 1:
        return None
    run = next(iter(matched_runs))
    if any(b - a != 1 for a, b in zip(run, run[1:])):
        return None
    return run


def resolve_file(
    *,
    parsed_episodes: tuple[int, ...],
    raw_title: str | None,
    is_season_relative: bool,
    season_titles: dict[int, str],
    season: int | None = None,
) -> Resolution:
    """Apply the 6-rule resolution policy for one file against one season."""
    valid_numbers = tuple(e for e in parsed_episodes if e in season_titles)
    title_match = match_title_in_titles(raw_title, season_titles)
    strong_title = (
        title_match is not None and title_match.strength >= STRONG_TITLE_STRENGTH
    )

    # Multi-episode files often carry a combined title ("A and B"); when every
    # segment is an exact distinct TMDB title forming a contiguous run, trust
    # the titles over the (frequently mis-numbered) source episode numbers.
    if len(parsed_episodes) >= 2:
        seg_run = match_segmented_title_run(
            raw_title, season_titles, len(parsed_episodes),
        )
        if seg_run is not None:
            if valid_numbers and set(seg_run) == set(valid_numbers):
                return Resolution(  # segmented agreement (rule-1-like)
                    episodes=seg_run,
                    confidence=CONF_AGREE,
                    evidence=frozenset({"number", "title-agree", "title-segmented"}),
                )
            return Resolution(  # segment titles override the source numbers
                episodes=seg_run,
                confidence=CONF_TITLE_WINS,
                evidence=frozenset(
                    {"title-strong", "title-segmented", "number-disagree"},
                ),
            )

    if valid_numbers and title_match is not None:
        if title_match.episode in valid_numbers:
            return Resolution(  # rule 1
                episodes=valid_numbers,
                confidence=CONF_AGREE,
                evidence=frozenset({"number", "title-agree"}),
            )
        if strong_title and title_match.strength >= _TITLE_EXACT:
            return Resolution(  # rule 2: exact title overrides, auto-accept
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
        if strong_title:
            return Resolution(  # rule 2b: strong inexact title overrides, REVIEW
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"title-strong-inexact", "number-disagree"}),
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
        if season == 0:
            # Season-0 numbering varies by source; a bare number is not
            # trustworthy on its own -> force review.
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_SPECIAL_NUMBER_ONLY,
                evidence=frozenset({"number", "special-number-only"}),
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

# Evidence tags that mark a claimant as an EXACT title match (rule 1 agree or
# rule 2 exact override). Used to auto-resolve a conflict in favour of the
# exact-title file over a weaker number-only claim. Excludes the substring
# rule-2b tag "title-strong-inexact" on purpose.
_EXACT_TITLE_EVIDENCE = frozenset({"title-agree", "title-strong"})


def _source_prefix_compatible(source_norm: str, show_norm: str) -> bool:
    """Return True when a file's source-title prefix corroborates the show.

    Handles three cases:
      - exact / prefix / suffix containment of the full normalized strings
        (e.g. "The Office US" vs "The Office"), and
      - a *franchise prefix* where the show name forms a contiguous trailing
        or leading token group of the source title. Release groups often add
        a franchise label TMDB omits, e.g. "Star Wars Andor" for the show
        "Andor". Matching on whole-token boundaries (not raw substring) keeps
        genuinely different shows ("Andromeda") contradictory.
    """
    if not source_norm or not show_norm:
        return False
    if (
        source_norm == show_norm
        or source_norm.startswith(show_norm)
        or show_norm.startswith(source_norm)
    ):
        return True
    source_tokens = source_norm.split()
    show_tokens = show_norm.split()
    if not show_tokens or len(show_tokens) > len(source_tokens):
        return False
    return (
        source_tokens[-len(show_tokens):] == show_tokens
        or source_tokens[: len(show_tokens)] == show_tokens
    )


def _parse_air_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _expected_for_season(slots: list[EpisodeSlot]) -> set[int]:
    """Episode numbers expected for coverage, ignoring unaired episodes.

    Untitled placeholder slots (count-implied, no TMDB listing yet) don't
    count toward coverage when titled slots exist. Slots whose air date is
    in the future are excluded — but only when at least one slot in the
    season has already aired, so seasons with no air-date metadata still
    count in full.
    """
    titled = [slot for slot in slots if slot.title]
    candidates = titled or slots
    today = date.today()
    aired: set[int] = set()
    saw_future = False
    for slot in candidates:
        air_date = _parse_air_date(slot.air_date)
        if air_date is None:
            continue
        if air_date <= today:
            aired.add(slot.episode)
        else:
            saw_future = True
    if saw_future and aired:
        return aired
    return {slot.episode for slot in candidates}


def _auto_resolve_strong_title_conflicts(table: EpisodeAssignmentTable) -> None:
    """Award a conflicted slot to its sole exact-title claimant.

    When a slot is claimed by exactly one auto file with exact-title evidence
    (``title-agree``/``title-strong``) and the other claimants are weaker
    (number-only / no exact-title evidence), the exact-title file keeps the
    slot and the rest are marked ``REASON_LOST_CONFLICT``. Slots with no
    exact-title claimant, with two or more exact-title claimants, or with any
    manual claimant are left untouched for manual resolution.
    """
    for (season, episode), claims in list(table.conflicts().items()):
        if any(claim.origin == ORIGIN_MANUAL for claim in claims):
            continue
        winners = [claim for claim in claims if claim.evidence & _EXACT_TITLE_EVIDENCE]
        if len(winners) != 1:
            continue
        table.resolve_conflict(season, episode, winner_file_id=winners[0].file_id)


def apply_confidence_adjustments(
    table: EpisodeAssignmentTable,
    *,
    show_info: dict,
    show_match_confidence: float | None = None,
) -> None:
    """Raise/cap auto-assignment confidence from corroborating evidence."""
    _auto_resolve_strong_title_conflicts(table)
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

    contradicted: set[int] = set()
    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL or assignment.file_id in conflicted:
            continue
        entry = table.files[assignment.file_id]
        confidence = assignment.confidence

        if entry.is_season_relative and assignment.season != 0:
            confidence = max(confidence, EXPLICIT_EPISODE_FLOOR)

        source_title = extract_source_title_prefix(entry.path.name)
        if source_title:
            source_norm = normalize_for_match(source_title)
            compatible = _source_prefix_compatible(source_norm, show_norm)
            if compatible and entry.is_season_relative and assignment.season != 0:
                confidence = max(confidence, COMPATIBLE_PREFIX_FLOOR)
            if not compatible and assignment.season != 0:
                contradicted.add(assignment.file_id)

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

    # Contradictory source prefixes cap LAST so no floor can lift them
    # back up (mirrors the retired postprocess ordering).
    for file_id in contradicted:
        assignment = table.assignment_for(file_id)
        if assignment is not None:
            table.set_confidence(
                file_id, min(assignment.confidence, CONTRADICTORY_PREFIX_CAP),
            )

    # Review-locked evidence (inexact title override, cross-season special,
    # cross-season title rescue) must stay below threshold no matter what
    # floors ran above.
    for assignment in table.assignments():
        if assignment.evidence & {
            "title-strong-inexact", "cross-season-special", "cross-season-rescue",
        }:
            table.set_confidence(
                assignment.file_id,
                min(assignment.confidence, CONF_TITLE_WINS_INEXACT),
            )


def rescue_cross_season_titles(table: EpisodeAssignmentTable) -> None:
    """Rescue single-episode files SKIPped as 'episode not in TMDB season'
    whose exact title is an unclaimed slot in a *different* regular season.

    Source season folders sometimes hold episodes TMDB lists under another
    regular season (As Told By Ginger's Season 1 folder holds S2E1-E4, named
    S01E17-E20). The parsed number is wrong, but an exact title in exactly one
    unclaimed regular-season slot is trustworthy enough to rescue — at review
    confidence, because the source numbering is known-bad. Ambiguous titles
    (matching 2+ unclaimed regular seasons) and already-claimed targets are
    left untouched.
    """
    title_index: dict[str, list[tuple[int, int]]] = {}
    for (season, episode), slot in table.slots.items():
        if season == 0 or not slot.title:
            continue
        norm = normalize_for_specials(slot.title)
        if norm:
            title_index.setdefault(norm, []).append((season, episode))

    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }

    for file_id, reason in list(table.unassigned_reasons.items()):
        if reason != REASON_NOT_IN_SEASON:
            continue
        entry = table.files.get(file_id)
        if entry is None or not entry.raw_title or len(entry.parsed_episodes) != 1:
            continue
        norm = normalize_for_specials(entry.raw_title)
        if not norm:
            continue
        candidates = [
            (season, episode)
            for (season, episode) in title_index.get(norm, [])
            if season != entry.folder_season and (season, episode) not in claimed
        ]
        if len(candidates) != 1:
            continue
        season, episode = candidates[0]
        table.assign(
            file_id, season, [episode], origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong", "cross-season-rescue"}),
        )
        claimed.add((season, episode))
