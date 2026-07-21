"""Shared episode resolution policy and confidence calibration.

ALL episode-level confidence constants live here. Tweak values in one
place; see docs/superpowers/specs/2026-06-11-episode-assignment-redesign-design.md.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .._parsing_parts import split_part_marker
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
    duplicate_copy_reason,
)

# ── calibration constants ───────────────────────────────────────────
STRONG_TITLE_STRENGTH = 0.85
CONF_AGREE = 0.96  # rule 1: number and title agree
CONF_TITLE_WINS = 0.90  # rule 2: strong title overrides number
CONF_WEAK_TITLE_NUMBER_CAP = 0.60  # rule 3: weak title disagreement caps number
CONF_NUMBER_RELATIVE = 0.86  # rule 4: S##E## number only
CONF_NUMBER_INFERRED = 0.50  # rule 4: bare/absolute number only
CONF_SPECIAL_NUMBER_ONLY = 0.50  # season-0 number with no title match -> REVIEW
CONF_TITLE_WINS_INEXACT = 0.70  # strong-but-inexact title overrides number -> REVIEW
CONF_TITLE_ONLY = 0.88  # rule 5: strong title, no usable number

_TITLE_EXACT = 1.0
_TITLE_NEAR_EXACT = 0.95  # typo-level edit or stopword-only difference (RC46)
_TITLE_SUBSTRING = 0.90
_TITLE_FUZZY = 0.86  # unique bounded-fuzzy title hit (typos, variants)
_TITLE_PART_NUMBER = 0.80
_MIN_SUBSTRING_LEN = 6  # minimum length of the INPUT to enter substring matching
_MIN_KEY_SUBSTRING_LEN = 4  # minimum length of a KEY to participate as a candidate
_MIN_FUZZY_LEN = 6  # minimum compacted length for edit-distance fuzz


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
        base = normalized[: match.start()] + normalized[match.end() :]
        # 'Heart of Archness Part 1' vs key 'Heart of Archness (1)': the
        # digit is gone but the word 'part' still blocks base equality.
        base = re.sub(r"(?:part|pt)$", "", base)
        return base, match.group()
    return normalized, ""


def _token_run_contains(container_spaced: str, contained_spaced: str) -> bool:
    """True when *contained_spaced* appears as a contiguous TOKEN run inside
    *container_spaced*. 'blues' is a compact substring of 'blue submarine…'
    but not a token run of it — such cross-boundary hits are noise (RC33)."""
    if not container_spaced or not contained_spaced:
        return False
    return f" {contained_spaced} " in f" {container_spaced} "


def _substring_candidates(
    normalized: str,
    spaced: str,
    lookup: dict[str, tuple[int, str]],
) -> list[tuple[int, str]]:
    """Return all (episode, title) pairs where *normalized* and the key overlap
    at a token boundary.

    Compact containment alone is unsafe ('blues' ⊂ 'bluesubmarine…'), so a hit
    must also align as a whole-token run in the spaced normalizations. Keys
    shorter than ``_MIN_KEY_SUBSTRING_LEN`` are allowed ONLY via the
    token-run check ('Sex' inside 'sex off the air adult swim').
    Called only when ``len(normalized) >= _MIN_SUBSTRING_LEN``.
    """
    hits: list[tuple[int, str]] = []
    for key, (episode, title) in lookup.items():
        if not key:
            continue
        key_spaced = normalize_for_specials_spaced(title)
        if len(key) >= _MIN_KEY_SUBSTRING_LEN:
            if normalized in key:
                if _token_run_contains(key_spaced, spaced):
                    hits.append((episode, title))
                continue
            if key in normalized and _token_run_contains(spaced, key_spaced):
                hits.append((episode, title))
        elif _token_run_contains(spaced, key_spaced):
            hits.append((episode, title))
    return hits


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
    spaced = normalize_for_specials_spaced(raw_title)
    return len(_substring_candidates(normalized, spaced, lookup)) > 1


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
    for token_a, token_b in zip(a_tokens, b_tokens, strict=False):
        if token_a == token_b:
            exact += 1
            continue
        short, long_ = (token_a, token_b) if len(token_a) <= len(token_b) else (token_b, token_a)
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


# Connective words whose presence/absence does not change which episode a
# title names ("Incident At The Trail's End" == "Incident of the Trail's
# End"). Leading articles are already stripped by normalize_for_match.
_TITLE_STOPWORDS = frozenset(
    {"a", "an", "the", "of", "at", "in", "on", "to", "and", "or", "for", "with", "by"}
)


def _content_tokens(spaced: str) -> tuple[str, ...]:
    return tuple(token for token in spaced.split() if token not in _TITLE_STOPWORDS)


def _acronym_folded_equal(a_spaced: str, b_spaced: str) -> bool:
    """Token walk treating an acronym as equal to the initials of a
    consecutive token run on the other side (tng == the next generation;
    RC48). Every other token must match exactly."""

    def _walk(a: list[str], b: list[str]) -> bool:
        i = j = 0
        folded = False
        while i < len(a) and j < len(b):
            if a[i] == b[j]:
                i += 1
                j += 1
                continue
            token = a[i]
            span = len(token)
            if (
                2 <= span <= 8
                and token.isalpha()
                and token not in _TITLE_STOPWORDS
                and j + span <= len(b)
                and "".join(word[0] for word in b[j : j + span]) == token
            ):
                i += 1
                j += span
                folded = True
                continue
            return False
        return folded and i == len(a) and j == len(b)

    a_tokens, b_tokens = a_spaced.split(), b_spaced.split()
    return _walk(a_tokens, b_tokens) or _walk(b_tokens, a_tokens)


def _near_exact_title_equal(
    input_compact: str,
    input_spaced: str,
    key_compact: str,
    key_spaced: str,
) -> bool:
    """Typo-level variants of one title: compact forms within edit distance
    2, identical content tokens once stopwords are dropped (RC46), or
    acronym-folded token equality (RC48)."""
    if (
        len(input_compact) >= _MIN_FUZZY_LEN
        and len(key_compact) >= _MIN_FUZZY_LEN
        and _edit_distance_at_most(input_compact, key_compact, 2)
    ):
        return True
    content = _content_tokens(input_spaced)
    if content and content == _content_tokens(key_spaced):
        return True
    return _acronym_folded_equal(input_spaced, key_spaced)


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

    spaced = normalize_for_specials_spaced(raw_text)

    # Typo-level variants of exactly one title rank just below exact: the
    # whole input IS that title modulo a small edit or stopword swap (RC46).
    # Ambiguity falls through — the part-number tier may still resolve it.
    near_hits = [
        (episode, title)
        for key, (episode, title) in lookup.items()
        if _near_exact_title_equal(
            normalized,
            spaced,
            key,
            normalize_for_specials_spaced(title),
        )
    ]
    if len(near_hits) == 1:
        episode, title = near_hits[0]
        return TitleMatch(episode=episode, title=title, strength=_TITLE_NEAR_EXACT)

    if len(normalized) >= _MIN_SUBSTRING_LEN:
        substring_hits = _substring_candidates(normalized, spaced, lookup)
        if len(substring_hits) == 1:
            episode, title = substring_hits[0]
            return TitleMatch(episode=episode, title=title, strength=_TITLE_SUBSTRING)
        if len(substring_hits) > 1:
            return None

    # Part-number bases are checked BEFORE the fuzzy tier: when both could
    # match ("Heart of Archness Part 1" vs "(1)"), the part correspondence
    # is the more specific claim and callers key policy off its strength.
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
                (episode, title) for episode, title, key_part in base_hits if key_part == input_part
            ]
            if len(by_part) == 1:
                episode, title = by_part[0]
                return TitleMatch(
                    episode=episode,
                    title=title,
                    strength=_TITLE_PART_NUMBER,
                )

    fuzzy_hits = [
        (episode, title)
        for key, (episode, title) in lookup.items()
        if _fuzzy_title_equal(
            normalized,
            spaced,
            key,
            normalize_for_specials_spaced(title),
        )
    ]
    if len(fuzzy_hits) == 1:
        episode, title = fuzzy_hits[0]
        return TitleMatch(episode=episode, title=title, strength=_TITLE_FUZZY)
    if len(fuzzy_hits) > 1:
        return None

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
    scored = _match_segmented_title_run_scored(raw_title, titles, expected_count)
    if scored is None:
        return None
    return scored[0], scored[1]


def _match_segmented_title_run_scored(
    raw_title: str | None,
    titles: dict[int, str],
    expected_count: int,
) -> tuple[tuple[int, ...], bool, int] | None:
    """``match_segmented_title_run`` plus a quality score.

    Returns ``(run, all_exact, direct)`` where ``direct`` counts the groups
    whose text matched their episode's title (exactly, fuzzily, or as a
    verified duplicate-title fill) — i.e. groups NOT placed by an unverified
    positional fill. Callers comparing runs of different sizes rank on it
    (RC49).
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

    matched_runs: dict[tuple[int, ...], tuple[bool, int]] = {}
    for cuts in itertools.combinations(range(1, atom_count), expected_count - 1):
        bounds = (0, *cuts, atom_count)
        unverified = 0
        episodes: list[int | None] = []
        exacts: list[bool] = []
        pieces: list[str] = []
        for group in range(expected_count):
            lo, hi = bounds[group], bounds[group + 1]
            piece = raw_title[spans[lo][0] : spans[hi - 1][1]]
            episode, exact = _match_piece(piece)
            if episode is None and hi - lo > 1:
                # A merged group's raw span keeps the separator ('&' folds to
                # the word "and"), but TMDB often titles the combined segment
                # with a colon ('Goodfeathers: The Beginning'); the
                # separator-stripped join bridges that spelling (RC41).
                joined = " ".join(raw_title[s:e] for s, e in spans[lo:hi])
                episode, exact = _match_piece(joined)
                if episode is not None:
                    piece = joined
            episodes.append(episode)
            exacts.append(exact)
            pieces.append(piece)

        matched = [(i, e) for i, e in enumerate(episodes) if e is not None]
        if len(matched) < expected_count:
            # Positional fill (RC31): >=2 groups matched a consistent
            # contiguous layout; an unmatched group's slot is start+i. The
            # fill stays EXACT when the group's title equals that slot's
            # title (a duplicate title the unique-lookup had to exclude),
            # and drops to review when the slot title differs (at most one
            # such unverified group).
            if len(matched) < 2:
                continue
            starts = {episode - index for index, episode in matched}
            if len(starts) != 1:
                continue
            start = starts.pop()
            for index, episode in enumerate(episodes):
                if episode is not None:
                    continue
                candidate = start + index
                if candidate not in titles:
                    unverified = 99
                    break
                piece_norm = normalize_for_specials(pieces[index])
                slot_norm = normalize_for_specials(titles[candidate])
                episodes[index] = candidate
                if not piece_norm or piece_norm != slot_norm:
                    # An unverified fill must still share evidence with the
                    # slot: a piece with NO tokens in common ('Flipper
                    # Parody' vs 'Taming of the Screwy') is naming some
                    # OTHER segment, not this slot (RC42).
                    piece_tokens = set(
                        _content_tokens(normalize_for_specials_spaced(pieces[index]))
                    )
                    slot_tokens = set(
                        _content_tokens(normalize_for_specials_spaced(titles[candidate]))
                    )
                    if not piece_tokens & slot_tokens:
                        unverified = 99
                        break
                    unverified += 1
                    exacts[index] = False
                else:
                    exacts[index] = True
            if unverified > 1:
                continue
        all_exact = all(exacts)
        if len(set(episodes)) == expected_count:
            run = tuple(sorted(episodes))  # type: ignore[arg-type]
            direct = expected_count - unverified
            prev = matched_runs.get(run)
            if prev is None:
                matched_runs[run] = (all_exact, direct)
            else:
                matched_runs[run] = (prev[0] or all_exact, max(prev[1], direct))
    if len(matched_runs) != 1:
        return None
    run, (all_exact, direct) = next(iter(matched_runs.items()))
    if any(b - a != 1 for a, b in itertools.pairwise(run)):
        return None
    return run, all_exact, direct


def _atom_is_title_fragment(atom_text: str, title: str) -> bool:
    """True when the atom's compact form is a PROPER substring of the
    title's — the atom is a piece of the title, not a name for it (RC43)."""
    atom_norm = normalize_for_specials(atom_text)
    title_norm = normalize_for_specials(title)
    return bool(atom_norm) and atom_norm != title_norm and atom_norm in title_norm


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
    exactly one atom matches that episode, every unmatched atom looks like a
    real title (>=2 words — a leftover 'new'/'Tigtone' fragment is noise,
    not a neighbor episode; RC30), and every slot exists.

    An atom anchors only when it NAMES the episode — equal to (or
    containing) the matched title. An atom that is merely a fragment of
    the title ('Unenlightened Peoples' inside 'Comparative Wickedness of
    Civilized and Unenlightened Peoples') is the tail of a title the
    separator split apart, not a neighbor list (RC43).
    """
    spans = _segment_atom_spans(raw_title)
    run_length = max(parsed_count, len(spans))
    if run_length < 2 or len(spans) != run_length:
        return None
    matching_indexes = [
        index
        for index, (lo, hi) in enumerate(spans)
        for match in [match_title_in_titles(raw_title[lo:hi], season_titles)]
        if match is not None
        and match.episode == matched_episode
        and not _atom_is_title_fragment(raw_title[lo:hi], match.title)
    ]
    if len(matching_indexes) != 1:
        return None
    if any(
        len(raw_title[lo:hi].split()) < 2
        for index, (lo, hi) in enumerate(spans)
        if index != matching_indexes[0]
    ):
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
    season_hint: int | None = None,
) -> Resolution:
    """Apply the 6-rule resolution policy for one file against one season.

    Pure dispatch: evidence is computed once, then exactly one phase
    resolves the file — combined/segmented titles first, then
    number+title, number-only, title-only, and finally the no-evidence
    fallthrough. Phase order is the policy; do not reorder.
    """
    valid_numbers = tuple(e for e in parsed_episodes if e in season_titles)
    title_match = match_title_in_titles(raw_title, season_titles)
    strong_title = title_match is not None and title_match.strength >= STRONG_TITLE_STRENGTH

    combined = _resolve_combined_title(
        parsed_episodes=parsed_episodes,
        raw_title=raw_title,
        valid_numbers=valid_numbers,
        title_match=title_match,
        season_titles=season_titles,
    )
    if combined is not None:
        return combined

    if valid_numbers and title_match is not None:
        return _resolve_number_and_title(
            valid_numbers=valid_numbers,
            title_match=title_match,
            strong_title=strong_title,
            raw_title=raw_title,
            parsed_episodes=parsed_episodes,
            season=season,
            season_titles=season_titles,
        )

    if valid_numbers:
        return _resolve_number_only(
            valid_numbers=valid_numbers,
            raw_title=raw_title,
            title_match=title_match,
            season_titles=season_titles,
            season=season,
            season_hint=season_hint,
            is_season_relative=is_season_relative,
        )

    if title_match is not None and strong_title:
        return _resolve_title_only(title_match)

    if parsed_episodes:
        return Resolution(episodes=(), reason=REASON_NOT_IN_SEASON)
    if raw_title:
        return Resolution(episodes=(), reason=REASON_NO_TITLE_MATCH)
    return Resolution(episodes=(), reason=REASON_NO_PARSE)


def _resolve_combined_title(
    *,
    parsed_episodes: tuple[int, ...],
    raw_title: str | None,
    valid_numbers: tuple[int, ...],
    title_match: TitleMatch | None,
    season_titles: dict[int, str],
) -> Resolution | None:
    """Segmented/combined-title phase; ``None`` means fall through."""
    # Multi-episode files often carry a combined title ("A and B"); when every
    # segment is an exact distinct TMDB title forming a contiguous run, trust
    # the titles over the (frequently mis-numbered) source episode numbers.
    if len(parsed_episodes) >= 2:
        seg = match_segmented_title_run(
            raw_title,
            season_titles,
            len(parsed_episodes),
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
        and (title_match is None or title_match.strength < _TITLE_NEAR_EXACT)
    ):
        # Disc-grouped sources put SEVERAL segment-indexed episodes behind
        # ONE file number (Animaniacs, Catscratch); the combined title is
        # then the only signal for the real run. Try plausible run sizes and
        # accept only an unambiguous result. An exact full-title match is
        # excluded above: when TMDB itself lists the combined title, that
        # agreement outranks decomposing it.
        runs: dict[tuple[int, ...], tuple[bool, int]] = {}
        for expected in (2, 3, 4):
            seg = _match_segmented_title_run_scored(
                raw_title,
                season_titles,
                expected,
            )
            if seg is not None:
                runs[seg[0]] = (seg[1], seg[2])
        if len(runs) > 1:
            # Disagreeing sizes are not equal witnesses: a run grounded in
            # more directly-matched groups outranks one that had to merge
            # atoms and place the merged group by positional fill (RC49).
            # Only a tie in that count is real ambiguity.
            best = max(direct for _, direct in runs.values())
            top = {run: q for run, q in runs.items() if q[1] == best}
            if len(top) == 1:
                runs = top
        if len(runs) == 1:
            seg_run, (seg_exact, _) = next(iter(runs.items()))
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

    return None


def _resolve_number_and_title(
    *,
    valid_numbers: tuple[int, ...],
    title_match: TitleMatch,
    strong_title: bool,
    raw_title: str | None,
    parsed_episodes: tuple[int, ...],
    season: int | None,
    season_titles: dict[int, str],
) -> Resolution:
    """Rules 1 / 2 / 2b / S0-part-override / 3: number AND title present."""
    if title_match.episode in valid_numbers:
        if raw_title and title_match.strength < _TITLE_NEAR_EXACT:
            # The parsed number agrees, but a combined title with MORE
            # atoms than parsed numbers means the file holds neighbors
            # too ("S04E21 - The Mattress & Looking for Jack" = E20-E21).
            # Only when the matched title sits INSIDE the raw title —
            # an input that is merely a prefix of a longer TMDB title
            # names nothing extra.
            spans = _segment_atom_spans(raw_title)
            if len(spans) > len(valid_numbers) and normalize_for_specials(
                title_match.title
            ) in normalize_for_specials(raw_title):
                run = _extend_partial_title_run(
                    raw_title,
                    title_match.episode,
                    season_titles,
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
    if strong_title and title_match.strength >= _TITLE_NEAR_EXACT:
        # An EXACT (or typo-level near-exact; RC46) full-title match
        # consumes the whole title: there is no leftover segment naming a
        # neighbor, so a single-number file never extends here ("Tigtone
        # and the Wine Crisis" = exactly one slot even though "and"
        # splits it into atoms; RC30). Multi-number files may still
        # extend from the matched anchor.
        run = None
        if raw_title and len(parsed_episodes) >= 2:
            run = _extend_partial_title_run(
                raw_title,
                title_match.episode,
                season_titles,
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
        if raw_title and (len(parsed_episodes) >= 2 or len(_segment_atom_spans(raw_title)) >= 2):
            run = _extend_partial_title_run(
                raw_title,
                title_match.episode,
                season_titles,
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
    if season == 0 and title_match.strength >= _TITLE_PART_NUMBER:
        # Specials numbering is source-unreliable; a unique titled part
        # match outranks a disagreeing S0 number (review).
        return Resolution(
            episodes=(title_match.episode,),
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-part-number", "number-disagree"}),
        )
    return Resolution(  # rule 3
        episodes=valid_numbers,
        confidence=CONF_WEAK_TITLE_NUMBER_CAP,
        evidence=frozenset({"number", "title-weak-disagree"}),
    )


def _resolve_number_only(
    *,
    valid_numbers: tuple[int, ...],
    raw_title: str | None,
    title_match: TitleMatch | None,
    season_titles: dict[int, str],
    season: int | None,
    season_hint: int | None,
    is_season_relative: bool,
) -> Resolution:
    """Rules 3-ambiguous / multi-segment-no-match / S0 / 4: number only."""
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
        if is_season_relative and season_hint == 0 and not raw_title:
            # An explicit S00E## in the FILENAME with no contradicting
            # title is the author's own specials labeling, not an
            # inferred guess (IT Crowd 'S00E01.mkv'; RC34). Files whose
            # rich titles match nothing keep the review lock below.
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_NUMBER_RELATIVE,
                evidence=frozenset(
                    {"number", "season-relative", "special-explicit"},
                ),
            )
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


def _resolve_title_only(title_match: TitleMatch) -> Resolution:
    """Rule 5: strong title, no usable number."""
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
    if (
        source_compact
        and show_compact
        and (
            source_compact == show_compact
            or source_compact.startswith(show_compact)
            or show_compact.startswith(source_compact)
        )
    ):
        return True
    source_tokens = source_norm.split()
    show_tokens = show_norm.split()
    if _acronym_prefix_compatible(source_tokens, show_tokens):
        return True
    if not show_tokens or len(show_tokens) > len(source_tokens):
        return False
    return (
        source_tokens[-len(show_tokens) :] == show_tokens
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


def _normalized_show_names(show_name: str, alt_show_names: Sequence[str]) -> list[str]:
    """Primary show name plus provider aliases, normalized and de-duplicated."""
    norms = [normalize_for_match(show_name)]
    for alt_name in alt_show_names:
        alt_norm = normalize_for_match(alt_name)
        if alt_norm and alt_norm not in norms:
            norms.append(alt_norm)
    return norms


def _source_prefix_compatible_any(source_norm: str, show_norms: Sequence[str]) -> bool:
    """True when the source prefix corroborates any of the show's names."""
    return any(_source_prefix_compatible(source_norm, norm) for norm in show_norms)


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
    if claim.evidence & {
        "title-strong-inexact",
        "title-segmented",
        "title-fuzzy",
        "title-part-number",
    }:
        return 2
    if "season-relative" in claim.evidence and "special-number-only" not in claim.evidence:
        return 2
    return 0


_TRAILING_PARENTHETICAL = re.compile(r"\s*\(([^()]*)\)\s*$")


def _strip_variant_tag(title: str) -> str:
    """Drop one trailing NON-NUMERIC parenthesized qualifier ('(Color)',
    '(Pencil)') — a print/version tag, not part numbering ('(1)' stays)."""
    match = _TRAILING_PARENTHETICAL.search(title)
    if match and not any(ch.isdigit() for ch in match.group(1)):
        return title[: match.start()]
    return title


def _claims_are_duplicate_copies(table: EpisodeAssignmentTable, claims: list) -> bool:
    """True when tied claims share the SAME real title — copies of one
    episode from parallel source folders, even when their parsed numbers
    differ (a mislabeled copy: "S01E34 - Dexter's Rival"). One normalized
    title may extend another with release junk or season branding
    ('Danger Island Comparative Wickedness...'; RC43), and one base title
    may sit behind different trailing version tags ('(Color)' vs
    '(Pencil)'; RC51) — numeric tags are part numbers and never fold."""
    titles = [
        normalize_for_specials(table.files[claim.file_id].raw_title or "") for claim in claims
    ]
    if any(not title for title in titles):
        return False
    shortest = min(titles, key=len)
    if all(shortest in title for title in titles):
        return True
    bases = {
        normalize_for_specials(_strip_variant_tag(table.files[claim.file_id].raw_title or ""))
        for claim in claims
    }
    return len(bases) == 1 and bool(next(iter(bases)))


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
            claim
            for claim in claims
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
                claim.file_id,
                season,
                list(remaining),
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
            c
            for c in claims
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
            entry.raw_title,
            proposed_titles,
            len(proposed),
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
            claim.file_id,
            season,
            list(proposed),
            origin=claim.origin,
            confidence=min(claim.confidence, CONF_TITLE_WINS),
            evidence=claim.evidence | {"run-shifted"},
        )


def detect_part_groups(table: EpisodeAssignmentTable) -> None:
    """Convert same-slot sibling claims with sequential part markers into
    part groups (spec: multi-file-episode-merge section 1).

    Grouping requires: same directory, identical marker-free base stem, a
    complete 1..N marker run (N >= 2), no unmarked sibling sharing the
    base stem, and every member auto-assigned to the identical
    (season, episodes) target. Runs BEFORE conflict resolution so groups
    are never consumed by the pile-up or duplicate-copy rules.
    """
    by_base: dict[tuple[Path, str], list[tuple[int, int | None]]] = {}
    for file_id, entry in table.files.items():
        base, marker = split_part_marker(entry.path.stem)
        by_base.setdefault((entry.path.parent, base), []).append((file_id, marker))

    for (_parent, _base), members in by_base.items():
        marked = [(fid, m) for fid, m in members if m is not None]
        if len(marked) < 2 or len(marked) != len(members):
            continue  # unmarked sibling present, or not enough parts
        markers = sorted(m for _fid, m in marked)
        if markers != list(range(1, len(markers) + 1)):
            continue  # incomplete or duplicated run
        assignments = [table.assignment_for(fid) for fid, _m in marked]
        if any(a is None or a.origin != ORIGIN_AUTO or a.part_order > 0 for a in assignments):
            continue
        targets = {(a.season, a.episodes) for a in assignments if a is not None}
        if len(targets) != 1:
            continue  # members resolved to different slots
        season, episodes = next(iter(targets))
        ordered = sorted(marked, key=lambda pair: pair[1] or 0)
        confidence = min(a.confidence for a in assignments if a is not None)
        for fid, marker in ordered:
            table.files[fid].part_marker = marker
        table.group_parts(
            [fid for fid, _m in ordered],
            season,
            list(episodes),
            origin=ORIGIN_AUTO,
            confidence=confidence,
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
    detect_part_groups(table)
    _trim_run_edge_conflicts(table)
    _shift_run_off_segmented_conflict(table)
    for season, episode in list(table.conflicts().keys()):
        # Re-fetch per slot: resolving an earlier slot can unassign a file
        # that claimed this one too, and a stale winner crashes
        # resolve_conflict ("File N does not claim S##E##" — RC32).
        claims = table.claims(season, episode)
        if len(table.logical_claims(season, episode)) < 2:
            continue  # a part group is one logical claim, not a conflict
        if any(claim.origin == ORIGIN_MANUAL for claim in claims):
            continue
        strengths = {claim.file_id: _claim_strength(claim) for claim in claims}
        top = max(strengths.values())
        winners = [claim for claim in claims if strengths[claim.file_id] == top]
        if len(winners) == 1:
            table.resolve_conflict(season, episode, winner_file_id=winners[0].file_id)
            continue

        if _claims_are_duplicate_copies(table, winners):
            # Prefer the claimant whose parsed number agrees with the slot;
            # fall back to the first-registered copy.
            keep = next(
                (
                    claim
                    for claim in winners
                    if episode in table.files[claim.file_id].parsed_episodes
                ),
                min(winners, key=lambda claim: claim.file_id),
            )
            table.resolve_conflict(season, episode, winner_file_id=keep.file_id)
            for claim in winners:
                if claim.file_id != keep.file_id:
                    table.mark_unassigned(
                        claim.file_id,
                        duplicate_copy_reason(season, episode),
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
    alt_show_names: Sequence[str] = (),
) -> None:
    """Raise/cap auto-assignment confidence from corroborating evidence.

    ``alt_show_names`` carries the provider's alternative titles/aliases:
    a source prefix corroborates the show when it matches the primary name
    OR any alias. Providers whose primary name is non-English (TVDB) would
    otherwise contradict files carrying the English alias.
    """
    _auto_resolve_strong_title_conflicts(table)
    show_name = show_info.get("name", "")
    show_norms = _normalized_show_names(show_name, alt_show_names)
    conflicted = table.conflicted_file_ids()

    slots_by_season: dict[int, list[EpisodeSlot]] = {}
    for slot in table.slots.values():
        slots_by_season.setdefault(slot.season, []).append(slot)
    season_slots = {
        season: _expected_for_season(slots) for season, slots in slots_by_season.items()
    }

    season_has_issue: set[int] = set()
    matched_by_season: dict[int, set[int]] = {}
    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if assignment.file_id in conflicted:
            season_has_issue.add(assignment.season)
            continue
        matched_by_season.setdefault(assignment.season, set()).update(assignment.episodes)

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
            compatible = _source_prefix_compatible_any(source_norm, show_norms)
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
            and normalize_for_specials(entry.raw_title) == normalize_for_specials(first_slot.title)
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

    single_regular_season = sum(1 for season in season_slots if season > 0) == 1
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
        elif (
            matched
            and matched <= expected
            and (len(missing) <= 1 or len(matched) / max(len(expected), 1) >= 0.90)
        ):
            floor = NEAR_COMPLETE_COVERAGE_FLOOR
        else:
            continue
        # NOTE (2026-07-10 review, finding R-F2): this floor is a SET-equality
        # test and cannot tell two transposed number-only files apart, so a
        # perfect single-season show can auto-accept swapped numbering at
        # exactly the user's 0.85 threshold. That lift is a deliberate,
        # test-locked product decision (see test_scan_improvements'
        # single-season exact-coverage tests) — revisit against the real
        # library before tightening.
        for assignment in table.assignments():
            if (
                assignment.season == season
                and assignment.origin != ORIGIN_MANUAL
                and assignment.file_id not in conflicted
            ):
                table.set_confidence(
                    assignment.file_id,
                    max(assignment.confidence, floor),
                )

    # Contradictory source prefixes cap LAST so no floor can lift them
    # back up (mirrors the retired postprocess ordering).
    for file_id in contradicted:
        assignment = table.assignment_for(file_id)
        if assignment is not None:
            table.set_confidence(
                file_id,
                min(assignment.confidence, CONTRADICTORY_PREFIX_CAP),
            )

    # Review-locked evidence (inexact title override, cross-season special,
    # cross-season title rescue, weak/ambiguous title disagreement) must stay
    # below threshold no matter what floors ran above.
    for assignment in table.assignments():
        if assignment.evidence & {
            "title-strong-inexact",
            "cross-season-special",
            "cross-season-rescue",
            "offset-inferred",
            "title-multi-segment",
            "title-fuzzy",
            "run-extended",
            "same-season-rescue",
            "title-part-number",
            "air-date-cluster",
            "title-weak-disagree",
            "title-ambiguous",
        }:
            table.set_confidence(
                assignment.file_id,
                min(assignment.confidence, CONF_TITLE_WINS_INEXACT),
            )


_ANCHOR_TITLE_EVIDENCE = frozenset(
    {
        "title-agree",
        "title-strong",
        "title-strong-inexact",
        "title-segmented",
    }
)
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
        anchors.append((assignment.season, assignment.episodes[0] - entry.parsed_episodes[0]))

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
            if reason != REASON_NOT_IN_SEASON and not reason.startswith(REASON_LOST_CONFLICT):
                continue
            movers.append((file_id, proposed))

    if not movers:
        return

    claimed = table.claimed_slots()
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
        if entry.is_season_relative and (
            entry.season_hint is None or entry.season_hint == target_season
        ):
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
    """Rescue single-episode files SKIPped as 'episode not in TMDB season' —
    or unassigned after LOSING a conflict (RC35) — whose exact title is an
    unclaimed slot in a *different* regular season.

    Source season folders sometimes hold episodes TMDB lists under another
    regular season (As Told By Ginger's Season 1 folder holds S2E1-E4, named
    S01E17-E20; Ren & Stimpy's S5 files hold S4E24-25 content). The parsed
    number is wrong — or already beaten by a stronger claimant — but an exact
    title in exactly one unclaimed regular-season slot is trustworthy enough
    to rescue at review confidence. Ambiguous titles (matching 2+ unclaimed
    regular seasons) and already-claimed targets are left untouched.
    """
    title_index: dict[str, list[tuple[int, int]]] = {}
    for (season, episode), slot in table.slots.items():
        if season == 0 or not slot.title:
            continue
        norm = normalize_for_specials(slot.title)
        if norm:
            title_index.setdefault(norm, []).append((season, episode))

    claimed = table.claimed_slots()

    for file_id, reason in list(table.unassigned_reasons.items()):
        if not (reason == REASON_NOT_IN_SEASON or reason.startswith(REASON_LOST_CONFLICT)):
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
            file_id,
            season,
            [episode],
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong", "cross-season-rescue"}),
        )
        claimed.add((season, episode))

    # RC36: a number-only claim whose title matches NOTHING in its titled
    # season but exactly matches a unique unclaimed slot elsewhere is a
    # mis-filed episode ('S08E18 - Murmur On The Ornery Express' living at
    # S09E27) — move it at review confidence instead of auto-accepting the
    # number.
    number_only = frozenset({"number", "season-relative"})
    for assignment in list(table.assignments()):
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if not (assignment.evidence and assignment.evidence <= number_only):
            continue
        entry = table.files.get(assignment.file_id)
        if entry is None or not entry.raw_title or len(entry.parsed_episodes) != 1:
            continue
        own_has_titles = any(
            slot.title
            for (slot_season, _episode), slot in table.slots.items()
            if slot_season == assignment.season
        )
        if not own_has_titles:
            continue
        norm = normalize_for_specials(entry.raw_title)
        if not norm:
            continue
        candidates = [
            (season, episode)
            for (season, episode) in title_index.get(norm, [])
            if season != assignment.season and (season, episode) not in claimed
        ]
        if len(candidates) != 1:
            continue
        season, episode = candidates[0]
        claimed -= {(assignment.season, e) for e in assignment.episodes}
        table.assign(
            assignment.file_id,
            season,
            [episode],
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong", "cross-season-rescue"}),
        )
        claimed.add((season, episode))


def rescue_explicit_hint_slots(table: EpisodeAssignmentTable) -> None:
    """Re-anchor lost-conflict files to their explicit S##E## slots (RC44).

    A file that carried an explicit season-relative number but was dragged
    onto (and lost) some other slot — a bare-show-name title match, a
    positional guess — still names its own slot in the filename. When every
    ``(hint, episode)`` slot exists and is unclaimed, assign there at review
    confidence; a titled rescue that already claimed the file wins by
    running earlier.
    """
    claimed = table.claimed_slots()
    for file_id, reason in list(table.unassigned_reasons.items()):
        if not reason.startswith(REASON_LOST_CONFLICT):
            continue
        entry = table.files.get(file_id)
        if (
            entry is None
            or not entry.is_season_relative
            or not entry.season_hint
            or not entry.parsed_episodes
        ):
            continue
        slots = {(entry.season_hint, episode) for episode in entry.parsed_episodes}
        if any(slot not in table.slots for slot in slots) or slots & claimed:
            continue
        table.assign(
            file_id,
            entry.season_hint,
            list(entry.parsed_episodes),
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"number", "season-relative", "hint-rescue"}),
        )
        claimed |= slots


def _scattered_atom_seasons(
    raw_title: str,
    titles_by_season: dict[int, dict[int, str]],
    current_season: int | None,
) -> set[int]:
    """Seasons (other than *current_season*) where >=2 of the title's atoms
    exact-match episode titles WITHOUT forming a run (RC36)."""
    spans = _segment_atom_spans(raw_title)
    if len(spans) < 2:
        return set()
    atom_norms = [normalize_for_specials(raw_title[lo:hi]) for lo, hi in spans]
    seasons: set[int] = set()
    for season, titles in titles_by_season.items():
        if season == current_season:
            continue
        norms = {normalize_for_specials(title) for title in titles.values() if title}
        matched = {norm for norm in atom_norms if norm and norm in norms}
        if len(matched) >= 2:
            seasons.add(season)
    return seasons


def rescue_cross_season_segmented(table: EpisodeAssignmentTable) -> None:
    """Re-home multi-segment files whose titles match nothing in their
    assigned season but form an EXACT segmented run in exactly one OTHER
    regular season (CatDog 'Season 3' files holding S2 content). Review
    confidence — the parsed numbers are known-wrong.

    Files whose atoms exact-match another season NON-contiguously cannot be
    a run there; their number claim is known-wrong too, so they unassign to
    review (RC36). Unassignments are applied before run moves so the freed
    slots can host other rescues in the same pass.
    """
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

    run_moves: list[tuple[int, int, tuple[int, ...]]] = []
    scattered_unassigns: list[tuple[int, int]] = []
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
        if len(hits) == 1:
            run_moves.append((file_id, hits[0][0], hits[0][1]))
            continue
        if hits:
            continue  # ambiguous across seasons — leave for review
        if table.assignment_for(file_id) is None:
            continue
        scattered = _scattered_atom_seasons(
            entry.raw_title or "",
            titles_by_season,
            current_season,
        )
        if len(scattered) == 1:
            scattered_unassigns.append((file_id, scattered.pop()))

    for file_id, season in scattered_unassigns:
        table.mark_unassigned(
            file_id,
            f"segment titles match Season {season} non-contiguously",
        )

    claimed = table.claimed_slots()
    # Movers can block each other in chains ('Back To School' squats the
    # slots 'Cat Got Your Tongue' needs until it moves to ITS titled run);
    # iterate to a fixpoint so every vacated slot can host the next move
    # regardless of iteration order (RC45).
    pending = list(run_moves)
    progress = True
    while pending and progress:
        progress = False
        remaining: list[tuple[int, int, tuple[int, ...]]] = []
        for file_id, season, run in pending:
            assignment = table.assignment_for(file_id)
            own = (
                {(assignment.season, e) for e in assignment.episodes}
                if assignment is not None
                else set()
            )
            run_slots = {(season, episode) for episode in run}
            if run_slots & (claimed - own):
                remaining.append((file_id, season, run))
                continue
            table.assign(
                file_id,
                season,
                list(run),
                origin=ORIGIN_AUTO,
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"title-segmented", "cross-season-rescue"}),
            )
            claimed -= own
            claimed |= run_slots
            progress = True
        pending = remaining


def _scattered_same_season_episodes(
    raw_title: str,
    titles: dict[int, str],
) -> tuple[int, ...]:
    """Episodes whose titles are exact-matched by the title's atom groups.

    Adjacent atoms are also tried merged (sizes 1-3) so a separator INSIDE
    one title ('Diapies and Dragons' splitting at 'and') still names its
    episode. Duplicate titles are excluded — they cannot pin an episode.
    """
    spans = _segment_atom_spans(raw_title)
    if len(spans) < 2 or len(spans) > _MAX_SEGMENT_ATOMS:
        return ()
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
    matched: set[int] = set()
    for size in (1, 2, 3):
        for start in range(len(spans) - size + 1):
            lo, hi = spans[start][0], spans[start + size - 1][1]
            pieces = [raw_title[lo:hi]]
            if size > 1:
                pieces.append(" ".join(raw_title[a:b] for a, b in spans[start : start + size]))
            for piece in pieces:
                episode = norm_to_episode.get(normalize_for_specials(piece))
                if episode is not None:
                    matched.add(episode)
                    break
    return tuple(sorted(matched))


def unassign_same_season_scattered_titles(table: EpisodeAssignmentTable) -> None:
    """Queue files whose segment titles pin >=2 episodes of their OWN season
    at non-adjacent numbers (RC50: Rugrats S9 pairs segments by broadcast
    half-hour while TMDB orders them differently).

    Such a file cannot be a run anywhere in the season, so its weak number
    claim (or lost-conflict fallback) presents wrong titles; unassigning
    with the explicit reason the cross-season path already mints routes it
    to the manual queue and keeps the single-slot fuzzy rescue from
    half-claiming one of its segments. Only weak states qualify —
    title-grounded assignments are never touched. Contiguous matches stay:
    they are a real run another pass may still place.
    """
    weak_title_evidence = {"title-ambiguous", "title-no-match"}
    candidates: list[tuple[int, int | None]] = []
    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if not (assignment.evidence & weak_title_evidence):
            continue
        candidates.append((assignment.file_id, assignment.season))
    for file_id, reason in table.unassigned_reasons.items():
        if not (
            reason in (REASON_NOT_IN_SEASON, REASON_NO_TITLE_MATCH)
            or reason.startswith(REASON_LOST_CONFLICT)
        ):
            continue
        entry = table.files[file_id]
        season = entry.season_hint if entry.season_hint is not None else entry.folder_season
        candidates.append((file_id, season))

    titles_by_season: dict[int, dict[int, str]] = {}
    for (season, episode), slot in table.slots.items():
        if season != 0 and slot.title:
            titles_by_season.setdefault(season, {})[episode] = slot.title

    for file_id, season in candidates:
        if season is None or season == 0:
            continue
        entry = table.files[file_id]
        titles = titles_by_season.get(season)
        if not titles or not entry.raw_title:
            continue
        matched = _scattered_same_season_episodes(entry.raw_title, titles)
        if len(matched) < 2:
            continue
        if all(b - a == 1 for a, b in itertools.pairwise(matched)):
            continue
        table.mark_unassigned(
            file_id,
            f"segment titles match Season {season} non-contiguously",
        )


def rescue_same_season_fuzzy_titles(table: EpisodeAssignmentTable) -> None:
    """Lost-conflict / no-match / not-in-season files whose (possibly fuzzy)
    title hits exactly ONE unclaimed slot in their own season -> review-assign
    (Angry Beavers: 3 unmapped files <-> 3 unclaimed same-title slots)."""
    claimed = table.claimed_slots()
    for file_id, reason in list(table.unassigned_reasons.items()):
        if not (
            reason in (REASON_NOT_IN_SEASON, REASON_NO_TITLE_MATCH)
            or reason.startswith(REASON_LOST_CONFLICT)
        ):
            continue
        entry = table.files.get(file_id)
        if entry is None or not entry.raw_title:
            continue
        season = entry.season_hint if entry.season_hint is not None else entry.folder_season
        if season is None or season == 0:
            continue
        unclaimed_titles = {
            episode: slot.title
            for (slot_season, episode), slot in table.slots.items()
            if slot_season == season and slot.title and (slot_season, episode) not in claimed
        }
        match = match_title_in_titles(entry.raw_title, unclaimed_titles)
        if match is None or match.strength < STRONG_TITLE_STRENGTH:
            continue
        table.assign(
            file_id,
            season,
            [match.episode],
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-fuzzy", "same-season-rescue"}),
        )
        claimed.add((season, match.episode))
