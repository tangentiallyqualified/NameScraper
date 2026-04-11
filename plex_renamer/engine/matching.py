"""Title scoring and TMDB match ranking.

Pure functions that turn a TMDB search result list into a ranked
``(result, score)`` list.  Callers in ``_core`` delegate here so the
engine's orchestrators and scanners stay focused on file discovery
and preview generation instead of scoring math.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..parsing import clean_folder_name, normalize_for_match
from ..tmdb import TMDBClient
from ._state import get_auto_accept_threshold
from .models import DirectEpisodeEvidence, collect_direct_episode_evidence


_log = logging.getLogger(__name__)


# Number of top candidates to fetch alternative titles for
_ALT_TITLE_CANDIDATES = 5


def title_similarity(a: str, b: str) -> float:
    """
    Compute a simple title similarity score between 0.0 and 1.0.

    Uses the longest common subsequence ratio, which handles:
      - Exact matches → 1.0
      - Substring matches (Daybreakers vs Daybreak) → high but < 1.0
      - Partial overlaps → proportional score
      - Completely different → near 0.0

    This is lightweight and doesn't need external libraries.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    # Quick check: one is substring of the other
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return len(shorter) / len(longer)

    # LCS length ratio — keep only two rows for O(min(m,n)) space
    m, n = len(a), len(b)
    if m < n:
        a, b = b, a
        m, n = n, m

    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev = curr

    lcs_len = prev[n]
    return (2.0 * lcs_len) / (m + n)  # Dice-like coefficient


def score_results(
    results: list[dict],
    raw_name: str,
    year_hint: str | None,
    title_key: str = "title",
) -> list[tuple[dict, float]]:
    """
    Score a list of TMDB search results against a cleaned name.

    Shared by both TV and movie matching paths.  Each result gets a
    confidence score based on:
      - Title similarity (normalized, case-insensitive) weighted at 70%
      - Year match weighted at 30%  (exact=1.0, ±1=0.8, ±2=0.5, ±3=0.2)
      - Exact normalized title match gets a +0.15 bonus

    Returns a list of (result, score) tuples sorted by score descending.
    """
    query_norm = normalize_for_match(raw_name)
    scored: list[tuple[dict, float]] = []

    for r in results:
        title = r.get(title_key, "")
        title_norm = normalize_for_match(title)

        t_score = title_similarity(query_norm, title_norm)

        year_score = 0.0
        if year_hint and r.get("year"):
            try:
                diff = abs(int(year_hint) - int(r["year"]))
                if diff == 0:
                    year_score = 1.0
                elif diff == 1:
                    year_score = 0.8
                elif diff == 2:
                    year_score = 0.5
                elif diff == 3:
                    year_score = 0.2
            except (ValueError, TypeError):
                pass

        score = (t_score * 0.7) + (year_score * 0.3)

        if query_norm == title_norm:
            score += 0.15

        scored.append((r, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def pick_alternate_matches(
    scored: list[tuple[dict, float]],
    *,
    selected_id: int | None,
    limit: int = 3,
) -> list[dict]:
    """Return the highest-ranked alternate matches excluding the selected id."""
    alternates: list[dict] = []
    for result, _score in scored:
        if result.get("id") == selected_id:
            continue
        alternates.append(result)
        if len(alternates) >= limit:
            break
    return alternates


def _country_from_language(language_tag: str) -> str | None:
    """Extract the ISO 3166-1 country code from a TMDB language tag.

    ``"fr-FR"`` → ``"FR"``, ``"en-US"`` → ``"US"``, ``"ja"`` → ``"JP"``.
    Returns None for empty/unrecognised input.
    """
    if not language_tag:
        return None
    if "-" in language_tag:
        return language_tag.split("-", 1)[1].upper()
    _LANG_TO_COUNTRY = {
        "en": "US", "fr": "FR", "es": "ES", "de": "DE", "it": "IT",
        "pt": "BR", "ja": "JP", "ko": "KR", "zh": "CN", "ru": "RU",
        "nl": "NL", "sv": "SE", "da": "DK", "no": "NO", "fi": "FI",
        "pl": "PL", "tr": "TR", "ar": "SA", "hi": "IN", "th": "TH",
    }
    return _LANG_TO_COUNTRY.get(language_tag.lower())


def boost_scores_with_alt_titles(
    scored: list[tuple[dict, float]],
    raw_name: str,
    year_hint: str | None,
    tmdb: TMDBClient,
    title_key: str = "title",
    media_type: str = "movie",
    preferred_country: str | None = None,
    force: bool = False,
) -> list[tuple[dict, float]]:
    """
    Re-score top candidates using TMDB alternative titles.

    When the best match scores below the auto-accept threshold, fetches
    alternative titles for the top candidates and re-scores each using the
    best-matching alternative.  Returns the full list re-sorted by the
    (potentially boosted) scores.

    Matching priority (fallback chain):

    1. Primary title from the TMDB search result (already scored).
    2. Alternative titles in the user's preferred language/country.
    3. English alternative titles (US / GB) as a universal fallback.
    4. All remaining alternative titles from other languages.

    If no alternative title pushes the score above the auto-accept
    threshold, the original (low) score is preserved and the item will
    be flagged for manual review.

    This is a no-op when the top result already exceeds the threshold or
    when there are no results.
    """
    if not scored:
        return scored

    best_score = scored[0][1]
    if best_score >= get_auto_accept_threshold() and not force:
        _log.debug(
            "Alt title boost skipped — top result already at %.2f "
            "(threshold %.2f) for %r",
            best_score, get_auto_accept_threshold(), raw_name,
        )
        return scored

    _log.info(
        "Alt title boost: top score %.2f for %r — checking alt titles "
        "(preferred_country=%s, force=%s)",
        best_score, raw_name, preferred_country, force,
    )

    query_norm = normalize_for_match(raw_name)
    english_countries = {"US", "GB"}
    updated: list[tuple[dict, float]] = []

    for i, (result, original_score) in enumerate(scored):
        if i < _ALT_TITLE_CANDIDATES and result.get("id") is not None:
            raw_alts = tmdb.get_alternative_titles(
                result["id"], media_type,
            )
            _log.debug(
                "  [%s] id=%s %r: %d alt titles fetched",
                media_type, result["id"],
                result.get(title_key, "?"), len(raw_alts),
            )

            preferred: list[str] = []
            english: list[str] = []
            rest: list[str] = []
            for title, cc in raw_alts:
                if preferred_country and cc == preferred_country:
                    preferred.append(title)
                elif cc in english_countries:
                    english.append(title)
                else:
                    rest.append(title)
            ordered_alts = preferred + english + rest

            best_alt_score = original_score
            best_alt_title = None
            for alt in ordered_alts:
                alt_norm = normalize_for_match(alt)
                t_score = title_similarity(query_norm, alt_norm)

                year_score = 0.0
                if year_hint and result.get("year"):
                    try:
                        diff = abs(int(year_hint) - int(result["year"]))
                        if diff == 0:
                            year_score = 1.0
                        elif diff == 1:
                            year_score = 0.3
                    except (ValueError, TypeError):
                        pass

                score = (t_score * 0.7) + (year_score * 0.3)
                if query_norm == alt_norm:
                    score += 0.15

                if score > best_alt_score:
                    best_alt_score = score
                    best_alt_title = alt

            if best_alt_title:
                _log.info(
                    "  Boosted id=%s from %.2f → %.2f via alt title %r",
                    result["id"], original_score, best_alt_score,
                    best_alt_title,
                )
            updated.append((result, best_alt_score))
        else:
            updated.append((result, original_score))

    updated.sort(key=lambda x: x[1], reverse=True)
    return updated


def _best_episode_title_similarity(
    raw_title: str | None,
    season_titles: dict[int, str],
) -> float:
    if not raw_title or not season_titles:
        return 0.0

    query_norm = normalize_for_match(raw_title)
    if not query_norm:
        return 0.0

    best = 0.0
    for title in season_titles.values():
        title_norm = normalize_for_match(title)
        if not title_norm:
            continue
        score = title_similarity(query_norm, title_norm)
        if len(query_norm) >= 8 and (query_norm in title_norm or title_norm in query_norm):
            score = max(score, 0.95)
        best = max(best, score)
        if best >= 0.999:
            break

    return best


def _tv_episode_evidence_adjustment(
    tmdb: TMDBClient,
    show_id: int,
    evidence: list[DirectEpisodeEvidence],
) -> float:
    tmdb_seasons, _ = tmdb.get_season_map(show_id)
    if not tmdb_seasons:
        return 0.0

    adjustment = 0.0
    explicit_seasons = {item.season_num for item in evidence if item.season_num > 0}
    if explicit_seasons:
        tmdb_regular_seasons = {sn for sn in tmdb_seasons if sn > 0}
        coverage = len(explicit_seasons & tmdb_regular_seasons) / len(explicit_seasons)
        adjustment += (coverage - 0.5) * 0.24

    exact_episode_hits = 0
    title_scores: list[float] = []
    limited_evidence = evidence[:8]
    for item in limited_evidence:
        season_data = tmdb_seasons.get(item.season_num)
        if not season_data:
            continue
        season_titles = season_data.get("titles", {})
        if item.episode_num in season_titles:
            exact_episode_hits += 1
        title_scores.append(_best_episode_title_similarity(item.raw_title, season_titles))

    if limited_evidence:
        adjustment += min(exact_episode_hits / len(limited_evidence), 1.0) * 0.10

    title_scores = [score for score in title_scores if score > 0.0]
    if title_scores:
        average_title_score = sum(title_scores) / len(title_scores)
        adjustment += average_title_score * 0.24
        if len(title_scores) >= 2 and average_title_score < 0.35:
            adjustment -= 0.12

    return adjustment


def boost_tv_scores_with_episode_evidence(
    tmdb: TMDBClient,
    scored: list[tuple[dict, float]],
    evidence: list[DirectEpisodeEvidence],
) -> list[tuple[dict, float]]:
    if not scored or not evidence:
        return scored

    updated: list[tuple[dict, float]] = []
    for index, (result, score) in enumerate(scored):
        show_id = result.get("id")
        if index >= _ALT_TITLE_CANDIDATES or show_id is None:
            updated.append((result, score))
            continue

        adjustment = _tv_episode_evidence_adjustment(tmdb, show_id, evidence)
        updated.append((result, score + adjustment))

    updated.sort(key=lambda item: item[1], reverse=True)
    return updated


def score_tv_results(
    results: list[dict],
    raw_name: str,
    year_hint: str | None,
    tmdb: TMDBClient,
    *,
    folder: Path | None = None,
    folder_score_name: str | None = None,
    episode_evidence: list[DirectEpisodeEvidence] | None = None,
) -> list[tuple[dict, float]]:
    """Score TV search results using the same logic as batch discovery."""
    scored = score_results(results, raw_name, year_hint, title_key="name")
    if folder is not None and folder_score_name is None:
        folder_score_name = clean_folder_name(folder.name)
    if folder_score_name and folder_score_name != raw_name:
        folder_scored = score_results(results, folder_score_name, year_hint, title_key="name")
        folder_map = {result.get("id"): score for result, score in folder_scored}
        scored = [
            (result, max(score, folder_map.get(result.get("id"), 0.0)))
            for result, score in scored
        ]
        scored.sort(key=lambda item: item[1], reverse=True)

    direct_evidence = episode_evidence
    if direct_evidence is None and folder is not None:
        direct_evidence = collect_direct_episode_evidence(folder)
    direct_evidence = direct_evidence or []

    scored = boost_scores_with_alt_titles(
        scored,
        raw_name,
        year_hint,
        tmdb,
        title_key="name",
        media_type="tv",
        preferred_country=_country_from_language(tmdb.language),
        force=bool(direct_evidence),
    )
    return boost_tv_scores_with_episode_evidence(tmdb, scored, direct_evidence)
