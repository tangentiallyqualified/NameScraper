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
    normalize_for_specials_spaced,
)
from .episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    REASON_LOST_CONFLICT,
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
_TITLE_FUZZY = 0.86          # unique bounded-fuzzy title hit (typos, variants)
_TITLE_PART_NUMBER = 0.80
_MIN_SUBSTRING_LEN = 6       # minimum length of the INPUT to enter substring matching
_MIN_KEY_SUBSTRING_LEN = 4   # minimum length of a KEY to participate as a candidate
_MIN_FUZZY_LEN = 6           # minimum compacted length for edit-distance fuzz


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


def _edit_distance_at_most(a: str, b: str, limit: int) -> bool:
    """Banded Levenshtein: True when edit distance <= limit."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        best = curr[0]
        for j, ch_b in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ch_a != ch_b))
            best = min(best, curr[j])
        if best > limit:
            return False
        prev = curr
    return prev[-1] <= limit


def _tokens_prefix_equal(a_spaced: str, b_spaced: str) -> bool:
    """Token-aligned near-equality: same token count, each pair equal or one
    a prefix of the other (shorter side >=3 chars), and >=1 exact pair.
    Catches 'Friend Alliance' vs 'Friendship Alliance'."""
    a_tokens, b_tokens = a_spaced.split(), b_spaced.split()
    if len(a_tokens) != len(b_tokens) or not a_tokens:
        return False
    exact = 0
    for token_a, token_b in zip(a_tokens, b_tokens):
        if token_a == token_b:
            exact += 1
            continue
        short, long_ = (
            (token_a, token_b) if len(token_a) <= len(token_b) else (token_b, token_a)
        )
        if len(short) < 3 or not long_.startswith(short):
            return False
    return exact >= 1


def _token_multisets_equal(a_spaced: str, b_spaced: str) -> bool:
    """Reordered-token equality ignoring part-words ('Tokyo No 1 Colony
    Part 3' vs 'Tokyo Colony No. 1 (3)'). Requires >=3 tokens."""
    strip = {"part", "pt"}
    a = sorted(token for token in a_spaced.split() if token not in strip)
    b = sorted(token for token in b_spaced.split() if token not in strip)
    return len(a) >= 3 and a == b


def _fuzzy_title_equal(
    input_compact: str,
    input_spaced: str,
    key_compact: str,
    key_spaced: str,
) -> bool:
    if (
        len(input_compact) >= _MIN_FUZZY_LEN
        and len(key_compact) >= _MIN_FUZZY_LEN
        and _edit_distance_at_most(input_compact, key_compact, 2)
    ):
        return True
    if _tokens_prefix_equal(input_spaced, key_spaced):
        return True
    return _token_multisets_equal(input_spaced, key_spaced)


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

    spaced = normalize_for_specials_spaced(raw_text)
    fuzzy_hits = [
        (episode, title)
        for key, (episode, title) in lookup.items()
        if _fuzzy_title_equal(
            normalized, spaced, key, normalize_for_specials_spaced(title),
        )
    ]
    if len(fuzzy_hits) == 1:
        episode, title = fuzzy_hits[0]
        return TitleMatch(episode=episode, title=title, strength=_TITLE_FUZZY)
    if len(fuzzy_hits) > 1:
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
) -> tuple[tuple[int, ...], bool] | None:
    """Resolve a combined multi-segment title into an episode run by titles.

    Returns ``(run, all_exact)``; ``all_exact`` is False when any group
    matched a TMDB title fuzzily — callers must then use review confidence.
    Splits *raw_title* on segment separators and merges adjacent atoms into
    exactly *expected_count* groups so each group is a TMDB title for a
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
    spaced_keys = {
        norm: normalize_for_specials_spaced(titles[episode])
        for norm, episode in norm_to_episode.items()
    }

    def _match_piece(piece: str) -> tuple[int | None, bool]:
        compact = normalize_for_specials(piece)
        episode = norm_to_episode.get(compact)
        if episode is not None:
            return episode, True
        spaced = normalize_for_specials_spaced(piece)
        hits = [
            episode
            for norm, episode in norm_to_episode.items()
            if _fuzzy_title_equal(compact, spaced, norm, spaced_keys[norm])
        ]
        if len(hits) == 1:
            return hits[0], False
        return None, False

    matched_runs: dict[tuple[int, ...], bool] = {}
    for cuts in itertools.combinations(range(1, atom_count), expected_count - 1):
        bounds = (0, *cuts, atom_count)
        episodes: list[int] = []
        all_exact = True
        for group in range(expected_count):
            lo, hi = bounds[group], bounds[group + 1]
            piece = raw_title[spans[lo][0]:spans[hi - 1][1]]
            episode, exact = _match_piece(piece)
            if episode is None:
                break
            episodes.append(episode)
            all_exact = all_exact and exact
        else:
            if len(set(episodes)) == expected_count:
                run = tuple(sorted(episodes))
                matched_runs[run] = matched_runs.get(run, False) or all_exact
    if len(matched_runs) != 1:
        return None
    run, all_exact = next(iter(matched_runs.items()))
    if any(b - a != 1 for a, b in zip(run, run[1:])):
        return None
    return run, all_exact


def _extend_partial_title_run(
    raw_title: str,
    matched_episode: int,
    season_titles: dict[int, str],
    parsed_count: int,
) -> tuple[int, ...] | None:
    """Anchor a run at the one atom that title-matched (RC20(3)).

    A combined multi-segment title where only ONE segment matched (typos
    block the rest) still names its neighbors by position: n atoms with the
    match at index i mean episodes [matched-i .. matched-i+n-1]. Only
    extends when the atom count is unambiguous (== max(parsed, atoms) >= 2),
    exactly one atom matches that episode, and every slot exists.
    """
    spans = _segment_atom_spans(raw_title)
    run_length = max(parsed_count, len(spans))
    if run_length < 2 or len(spans) != run_length:
        return None
    matching_indexes = [
        index
        for index, (lo, hi) in enumerate(spans)
        for match in [match_title_in_titles(raw_title[lo:hi], season_titles)]
        if match is not None and match.episode == matched_episode
    ]
    if len(matching_indexes) != 1:
        return None
    start = matched_episode - matching_indexes[0]
    run = tuple(range(start, start + run_length))
    if any(episode not in season_titles for episode in run):
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
        seg = match_segmented_title_run(
            raw_title, season_titles, len(parsed_episodes),
        )
        if seg is not None:
            seg_run, seg_exact = seg
            if not seg_exact:
                return Resolution(  # fuzzy atoms -> review
                    episodes=seg_run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-segmented", "title-fuzzy", "number-disagree"},
                    ),
                )
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
    elif (
        len(parsed_episodes) == 1
        and raw_title
        and (title_match is None or title_match.strength < _TITLE_EXACT)
    ):
        # Disc-grouped sources put SEVERAL segment-indexed episodes behind
        # ONE file number (Animaniacs, Catscratch); the combined title is
        # then the only signal for the real run. Try plausible run sizes and
        # accept only an unambiguous result. An exact full-title match is
        # excluded above: when TMDB itself lists the combined title, that
        # agreement outranks decomposing it.
        runs: dict[tuple[int, ...], bool] = {}
        for expected in (2, 3, 4):
            seg = match_segmented_title_run(raw_title, season_titles, expected)
            if seg is not None:
                runs[seg[0]] = runs.get(seg[0], False) or seg[1]
        if len(runs) == 1:
            seg_run, seg_exact = next(iter(runs.items()))
            if not seg_exact:
                return Resolution(  # fuzzy atoms -> review
                    episodes=seg_run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-segmented", "title-fuzzy", "number-disagree"},
                    ),
                )
            if valid_numbers and set(valid_numbers) <= set(seg_run):
                return Resolution(  # number lies inside the titled run
                    episodes=seg_run,
                    confidence=CONF_AGREE,
                    evidence=frozenset({"number", "title-agree", "title-segmented"}),
                )
            return Resolution(  # segment titles override the grouping number
                episodes=seg_run,
                confidence=CONF_TITLE_WINS,
                evidence=frozenset(
                    {"title-strong", "title-segmented", "number-disagree"},
                ),
            )

    if valid_numbers and title_match is not None:
        if title_match.episode in valid_numbers:
            if raw_title and title_match.strength < _TITLE_EXACT:
                # The parsed number agrees, but a combined title with MORE
                # atoms than parsed numbers means the file holds neighbors
                # too ("S04E21 - The Mattress & Looking for Jack" = E20-E21).
                # Only when the matched title sits INSIDE the raw title —
                # an input that is merely a prefix of a longer TMDB title
                # names nothing extra.
                spans = _segment_atom_spans(raw_title)
                if (
                    len(spans) > len(valid_numbers)
                    and normalize_for_specials(title_match.title)
                    in normalize_for_specials(raw_title)
                ):
                    run = _extend_partial_title_run(
                        raw_title, title_match.episode, season_titles,
                        len(parsed_episodes),
                    )
                    if run is not None and set(valid_numbers) <= set(run):
                        return Resolution(  # extended run -> review
                            episodes=run,
                            confidence=CONF_TITLE_WINS_INEXACT,
                            evidence=frozenset(
                                {"number", "title-strong-inexact", "run-extended"},
                            ),
                        )
            return Resolution(  # rule 1
                episodes=valid_numbers,
                confidence=CONF_AGREE,
                evidence=frozenset({"number", "title-agree"}),
            )
        if strong_title and title_match.strength >= _TITLE_EXACT:
            run = None
            if raw_title and (
                len(parsed_episodes) >= 2 or len(_segment_atom_spans(raw_title)) >= 2
            ):
                run = _extend_partial_title_run(
                    raw_title, title_match.episode, season_titles,
                    len(parsed_episodes),
                )
            if run is not None and len(run) > 1:
                return Resolution(  # extended run -> review (partly unverified)
                    episodes=run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-strong-inexact", "number-disagree", "run-extended"},
                    ),
                )
            return Resolution(  # rule 2: exact title overrides, auto-accept
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
        if strong_title:
            run = None
            if raw_title and (
                len(parsed_episodes) >= 2 or len(_segment_atom_spans(raw_title)) >= 2
            ):
                run = _extend_partial_title_run(
                    raw_title, title_match.episode, season_titles,
                    len(parsed_episodes),
                )
            if run is not None and len(run) > 1:
                return Resolution(
                    episodes=run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-strong-inexact", "number-disagree", "run-extended"},
                    ),
                )
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
            evidence = {"number", "title-ambiguous"}
            if len(_segment_atom_spans(raw_title)) >= 2:
                # A combined multi-segment title that matched several titles
                # but resolved to no unique run: the number is a disc
                # grouping index, not a season position — review-locked.
                evidence.add("title-multi-segment")
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_WEAK_TITLE_NUMBER_CAP,
                evidence=frozenset(evidence),
            )
        if (
            raw_title
            and title_match is None
            and len(valid_numbers) >= 2
            and len(_segment_atom_spans(raw_title)) >= 2
            and any(title for title in season_titles.values())
        ):
            # A multi-EPISODE file whose rich multi-segment title matches
            # NOTHING in a titled season means the numbers are disc/source
            # indexes, not season positions (Rugrats S7 overflow, CatDog
            # mis-filed seasons). Review-locked. Single-number files stay on
            # rule 4 — an ordinary title containing "and" splits into atoms
            # too ("Church and State").
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_WEAK_TITLE_NUMBER_CAP,
                evidence=frozenset(
                    {"number", "title-no-match", "title-multi-segment"},
                ),
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
        if title_match.strength >= _TITLE_SUBSTRING:
            return Resolution(
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_ONLY,
                evidence=frozenset({"title-strong"}),
            )
        return Resolution(  # fuzzy-only match -> review
            episodes=(title_match.episode,),
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong-inexact", "title-fuzzy"}),
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
    # Punctuation splits tokens apart ("M*A*S*H" -> "m a s h", "Hell's" ->
    # "hell s"); compare space-collapsed compact forms so those source
    # spellings aren't treated as a different show.
    source_compact = source_norm.replace(" ", "")
    show_compact = show_norm.replace(" ", "")
    if source_compact and show_compact and (
        source_compact == show_compact
        or source_compact.startswith(show_compact)
        or show_compact.startswith(source_compact)
    ):
        return True
    source_tokens = source_norm.split()
    show_tokens = show_norm.split()
    if _acronym_prefix_compatible(source_tokens, show_tokens):
        return True
    if not show_tokens or len(show_tokens) > len(source_tokens):
        return False
    return (
        source_tokens[-len(show_tokens):] == show_tokens
        or source_tokens[: len(show_tokens)] == show_tokens
    )


_ACRONYM_STOPWORDS = frozenset({"the", "a", "an", "of", "and"})


def _acronym_prefix_compatible(
    source_tokens: list[str],
    show_tokens: list[str],
) -> bool:
    """True when the source abbreviates the show's tail as an acronym.

    Release names shorten long show names ("Star Trek TNG" for "Star Trek:
    The Next Generation"): shared leading tokens, then one source token equal
    to the initials of the remaining show tokens (stopwords optional).
    """
    if len(source_tokens) < 2 or len(show_tokens) <= len(source_tokens):
        return False
    shared = len(source_tokens) - 1
    if source_tokens[:shared] != show_tokens[:shared]:
        return False
    tail = show_tokens[shared:]
    if len(tail) < 2:
        return False
    acronym = "".join(token[0] for token in tail if token)
    acronym_no_stop = "".join(
        token[0] for token in tail if token and token not in _ACRONYM_STOPWORDS
    )
    candidate = source_tokens[-1]
    return len(candidate) >= 2 and candidate in (acronym, acronym_no_stop)


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


def _claim_strength(claim) -> int:
    """Evidence ladder: exact title > (inexact/segmented title ~ explicit
    season-relative number) > bare/special number.

    Inexact titles and explicit S##E## numbers deliberately TIE — neither may
    evict the other automatically — while both beat a bare or special-only
    number (specials numbering varies wildly across sources).
    """
    if claim.evidence & _EXACT_TITLE_EVIDENCE:
        return 3
    if claim.evidence & {"title-strong-inexact", "title-segmented", "title-fuzzy"}:
        return 2
    if "season-relative" in claim.evidence and "special-number-only" not in claim.evidence:
        return 2
    return 0


def _claims_are_duplicate_copies(table: EpisodeAssignmentTable, claims: list) -> bool:
    """True when tied claims are copies of the SAME episode from parallel
    source folders: identical parsed numbers and a shared real title (one
    normalized title may extend another with release junk, e.g.
    "Need for Weed" vs "Need for Weed 1080p H265 …")."""
    parsed = {table.files[claim.file_id].parsed_episodes for claim in claims}
    if len(parsed) != 1:
        return False
    titles = [
        normalize_for_specials(table.files[claim.file_id].raw_title or "")
        for claim in claims
    ]
    if any(not title for title in titles):
        return False
    shortest = min(titles, key=len)
    return all(title.startswith(shortest) for title in titles)


def _trim_run_edge_conflicts(table: EpisodeAssignmentTable) -> None:
    """Trim a multi-episode run whose edge collides with an exact-title single.

    TMDB often lists a feature-length premiere as ONE episode ("Emissary" =
    S01E01) while the source numbers it E01-E02. The run's own title anchors
    at a different episode of the run, and the disputed edge slot belongs by
    exact title to another file — shrink the run instead of conflicting.
    """
    for (season, episode), claims in list(table.conflicts().items()):
        if any(claim.origin == ORIGIN_MANUAL for claim in claims):
            continue
        singles = [
            claim for claim in claims
            if len(claim.episodes) == 1 and claim.evidence & _EXACT_TITLE_EVIDENCE
        ]
        if len(singles) != 1:
            continue
        for claim in claims:
            if len(claim.episodes) < 2:
                continue
            if episode not in (claim.episodes[0], claim.episodes[-1]):
                continue
            entry = table.files[claim.file_id]
            run_titles = {
                ep: table.slots[(season, ep)].title
                for ep in claim.episodes
                if (season, ep) in table.slots and table.slots[(season, ep)].title
            }
            match = match_title_in_titles(entry.raw_title, run_titles)
            if match is None or match.episode == episode or match.strength < _TITLE_EXACT:
                continue
            remaining = tuple(ep for ep in claim.episodes if ep != episode)
            table.assign(
                claim.file_id, season, list(remaining),
                origin=claim.origin,
                confidence=claim.confidence,
                evidence=claim.evidence | {"run-trimmed"},
            )


def _shift_run_off_segmented_conflict(table: EpisodeAssignmentTable) -> None:
    """Slide a whole-run claim off a segmented run's slot when possible.

    A segmented-title run pins each episode by its own exact segment title;
    an overlapping rule-1 run (combined title matching one episode of the
    run) is less precise. If shifting the rule-1 run one step away keeps its
    title anchor inside the run and lands on free slots, shift it.
    """
    for (season, episode), claims in list(table.conflicts().items()):
        if any(claim.origin == ORIGIN_MANUAL for claim in claims):
            continue
        segmented = [c for c in claims if "title-segmented" in c.evidence]
        movable = [
            c for c in claims
            if "title-segmented" not in c.evidence
            and c.evidence & _EXACT_TITLE_EVIDENCE
            and len(c.episodes) >= 2
            and episode in (c.episodes[0], c.episodes[-1])
        ]
        if len(segmented) != 1 or len(movable) != 1:
            continue
        claim = movable[0]
        shift = 1 if episode == claim.episodes[0] else -1
        proposed = tuple(ep + shift for ep in claim.episodes)
        if any((season, ep) not in table.slots for ep in proposed):
            continue
        entry = table.files[claim.file_id]
        proposed_titles = {
            ep: table.slots[(season, ep)].title
            for ep in proposed
            if table.slots[(season, ep)].title
        }
        seg = match_segmented_title_run(
            entry.raw_title, proposed_titles, len(proposed),
        )
        if seg is None or seg[0] != proposed:
            match = match_title_in_titles(entry.raw_title, proposed_titles)
            if match is None:
                continue
        occupied = {
            (assignment.season, ep)
            for assignment in table.assignments()
            if assignment.file_id != claim.file_id
            for ep in assignment.episodes
        }
        if any((season, ep) in occupied for ep in proposed):
            continue
        table.assign(
            claim.file_id, season, list(proposed),
            origin=claim.origin,
            confidence=min(claim.confidence, CONF_TITLE_WINS),
            evidence=claim.evidence | {"run-shifted"},
        )


def _auto_resolve_strong_title_conflicts(table: EpisodeAssignmentTable) -> None:
    """Resolve slot conflicts so no episode is listed twice unresolved.

    Order: trim double-episode run edges, slide whole-run claims off
    segmented runs, then per remaining slot award the unique strongest
    claimant on the evidence ladder. Tied claimants that are byte-for-byte
    duplicate copies (same parsed numbers + same title, different source
    folders) resolve to the first-registered file; other single-episode ties
    are unassigned as ambiguous. Slots with manual claimants are untouched.
    """
    _trim_run_edge_conflicts(table)
    _shift_run_off_segmented_conflict(table)
    for (season, episode), claims in list(table.conflicts().items()):
        if any(claim.origin == ORIGIN_MANUAL for claim in claims):
            continue
        strengths = {claim.file_id: _claim_strength(claim) for claim in claims}
        top = max(strengths.values())
        winners = [claim for claim in claims if strengths[claim.file_id] == top]
        if len(winners) == 1:
            table.resolve_conflict(season, episode, winner_file_id=winners[0].file_id)
            continue

        if _claims_are_duplicate_copies(table, winners):
            # Same parsed numbers AND the same real title from parallel
            # source folders = duplicate copies of one episode, not a
            # genuine conflict. Keep the first-registered (primary) copy.
            keep = min(winners, key=lambda claim: claim.file_id)
            table.resolve_conflict(season, episode, winner_file_id=keep.file_id)
            for claim in winners:
                if claim.file_id != keep.file_id:
                    table.mark_unassigned(
                        claim.file_id,
                        f"duplicate copy of S{season:02d}E{episode:02d}",
                    )
            continue

        if len(claims) >= 3 and all(len(claim.episodes) == 1 for claim in claims):
            # A pile-up of 3+ distinct files on one slot means the shared
            # title fragment matched them all; none is trustworthy.
            for claim in claims:
                table.mark_unassigned(
                    claim.file_id,
                    f"ambiguous claim for S{season:02d}E{episode:02d}",
                )


def resolve_table_conflicts(table: EpisodeAssignmentTable) -> None:
    """Public entry: resolve slot conflicts (used after sibling table merges)."""
    _auto_resolve_strong_title_conflicts(table)


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

        # A season-relative floor is only justified when the file's explicit
        # season actually IS the assigned season; an S03E06 file mapped into
        # season 1 has disputed numbering and must stay reviewable.
        hint_matches_assignment = (
            entry.season_hint is None or entry.season_hint == assignment.season
        )
        if entry.is_season_relative and assignment.season != 0 and hint_matches_assignment:
            confidence = max(confidence, EXPLICIT_EPISODE_FLOOR)

        source_title = extract_source_title_prefix(entry.path.name)
        if source_title:
            source_norm = normalize_for_match(source_title)
            compatible = _source_prefix_compatible(source_norm, show_norm)
            if (
                compatible
                and entry.is_season_relative
                and assignment.season != 0
                and hint_matches_assignment
            ):
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
            "offset-inferred", "title-multi-segment", "title-fuzzy", "run-extended",
            "same-season-rescue",
        }:
            table.set_confidence(
                assignment.file_id,
                min(assignment.confidence, CONF_TITLE_WINS_INEXACT),
            )


_ANCHOR_TITLE_EVIDENCE = frozenset({
    "title-agree", "title-strong", "title-strong-inexact", "title-segmented",
})
_NUMBER_ONLY_EVIDENCE = frozenset({"number", "season-relative", "special-number-only"})


def apply_uniform_offset_rescue(table: EpisodeAssignmentTable) -> None:
    """Follow a uniform title-anchor offset for number-only siblings.

    When every title-matched file of one source season lands at the SAME
    nonzero offset from its parsed number (JJK source S3 -> TMDB S1 E48+,
    Rawhide S5 shifted by one), the source numbering is systematically off.
    Number-only assignments and lost-conflict/not-in-season files in that
    group are re-mapped to ``parsed + offset`` at review confidence — never
    auto-accepted, because the offset is inferred, not observed.
    """
    groups: dict[int, list[int]] = {}
    for file_id, entry in table.files.items():
        source_season = entry.season_hint if entry.season_hint is not None else entry.folder_season
        if source_season is None or source_season == 0:
            continue
        if not entry.parsed_episodes:
            continue
        groups.setdefault(source_season, []).append(file_id)

    for file_ids in groups.values():
        _rescue_group(table, file_ids)


def _rescue_group(table: EpisodeAssignmentTable, file_ids: list[int]) -> None:
    anchors: list[tuple[int, int]] = []  # (target_season, offset)
    for file_id in file_ids:
        assignment = table.assignment_for(file_id)
        if assignment is None or assignment.origin == ORIGIN_MANUAL:
            continue
        if not assignment.evidence & _ANCHOR_TITLE_EVIDENCE:
            continue
        entry = table.files[file_id]
        anchors.append(
            (assignment.season, assignment.episodes[0] - entry.parsed_episodes[0])
        )

    if len(anchors) < 2:
        return
    seasons = {season for season, _ in anchors}
    offsets = {offset for _, offset in anchors}
    if len(seasons) != 1 or len(offsets) != 1:
        return
    target_season = next(iter(seasons))
    offset = next(iter(offsets))
    if offset == 0:
        return

    movers: list[tuple[int, tuple[int, ...]]] = []
    vacated: set[tuple[int, int]] = set()
    for file_id in file_ids:
        entry = table.files[file_id]
        proposed = tuple(episode + offset for episode in entry.parsed_episodes)
        if any((target_season, episode) not in table.slots for episode in proposed):
            continue
        assignment = table.assignment_for(file_id)
        if assignment is not None:
            if assignment.origin == ORIGIN_MANUAL:
                continue
            if assignment.evidence & _ANCHOR_TITLE_EVIDENCE:
                continue
            if not assignment.evidence <= _NUMBER_ONLY_EVIDENCE:
                continue
            if assignment.season != target_season:
                continue
            if assignment.episodes == proposed:
                continue
            vacated.update((assignment.season, ep) for ep in assignment.episodes)
            movers.append((file_id, proposed))
        else:
            reason = table.unassigned_reasons.get(file_id, "")
            if reason != REASON_NOT_IN_SEASON and not reason.startswith(
                REASON_LOST_CONFLICT
            ):
                continue
            movers.append((file_id, proposed))

    if not movers:
        return

    claimed: set[tuple[int, int]] = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    claimed -= vacated

    proposed_slots: set[tuple[int, int]] = set()
    accepted: list[tuple[int, tuple[int, ...]]] = []
    for file_id, proposed in movers:
        slots = {(target_season, episode) for episode in proposed}
        if slots & claimed or slots & proposed_slots:
            continue
        proposed_slots |= slots
        accepted.append((file_id, proposed))

    for file_id, proposed in accepted:
        entry = table.files[file_id]
        evidence = {"number", "offset-inferred"}
        if entry.is_season_relative:
            evidence.add("season-relative")
        table.assign(
            file_id,
            target_season,
            list(proposed),
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset(evidence),
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


def rescue_cross_season_segmented(table: EpisodeAssignmentTable) -> None:
    """Re-home multi-segment files whose titles match nothing in their
    assigned season but form an EXACT segmented run in exactly one OTHER
    regular season (CatDog 'Season 3' files holding S2 content). Review
    confidence — the parsed numbers are known-wrong."""
    titles_by_season: dict[int, dict[int, str]] = {}
    for (season, episode), slot in table.slots.items():
        if season != 0 and slot.title:
            titles_by_season.setdefault(season, {})[episode] = slot.title

    candidates: list[tuple[int, int | None]] = []
    for assignment in list(table.assignments()):
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if "title-no-match" not in assignment.evidence:
            continue
        candidates.append((assignment.file_id, assignment.season))
    for file_id, reason in table.unassigned_reasons.items():
        if reason != REASON_NOT_IN_SEASON:
            continue
        entry = table.files[file_id]
        if entry.raw_title and len(entry.parsed_episodes) >= 2:
            candidates.append((file_id, entry.folder_season))

    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    for file_id, current_season in candidates:
        entry = table.files[file_id]
        expected = max(len(entry.parsed_episodes), 2)
        hits: list[tuple[int, tuple[int, ...]]] = []
        for season, titles in titles_by_season.items():
            if season == current_season:
                continue
            seg = match_segmented_title_run(entry.raw_title, titles, expected)
            if seg is not None and seg[1]:  # exact runs only across seasons
                hits.append((season, seg[0]))
        if len(hits) != 1:
            continue
        season, run = hits[0]
        assignment = table.assignment_for(file_id)
        own = (
            {(assignment.season, e) for e in assignment.episodes}
            if assignment is not None else set()
        )
        run_slots = {(season, episode) for episode in run}
        if run_slots & (claimed - own):
            continue
        table.assign(
            file_id, season, list(run), origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-segmented", "cross-season-rescue"}),
        )
        claimed -= own
        claimed |= run_slots


def rescue_same_season_fuzzy_titles(table: EpisodeAssignmentTable) -> None:
    """Lost-conflict / no-match / not-in-season files whose (possibly fuzzy)
    title hits exactly ONE unclaimed slot in their own season -> review-assign
    (Angry Beavers: 3 unmapped files <-> 3 unclaimed same-title slots)."""
    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    for file_id, reason in list(table.unassigned_reasons.items()):
        if not (
            reason in (REASON_NOT_IN_SEASON, REASON_NO_TITLE_MATCH)
            or reason.startswith(REASON_LOST_CONFLICT)
        ):
            continue
        entry = table.files.get(file_id)
        if entry is None or not entry.raw_title:
            continue
        season = (
            entry.season_hint if entry.season_hint is not None
            else entry.folder_season
        )
        if season is None or season == 0:
            continue
        unclaimed_titles = {
            episode: slot.title
            for (slot_season, episode), slot in table.slots.items()
            if slot_season == season and slot.title
            and (slot_season, episode) not in claimed
        }
        match = match_title_in_titles(entry.raw_title, unclaimed_titles)
        if match is None or match.strength < STRONG_TITLE_STRENGTH:
            continue
        table.assign(
            file_id, season, [match.episode], origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-fuzzy", "same-season-rescue"}),
        )
        claimed.add((season, match.episode))
