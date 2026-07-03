"""Consolidated-preview helpers for TVScanner."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import (
    build_tv_name,
    extract_episode,
    extract_season_number,
    normalize_for_specials,
    normalize_for_specials_spaced,
)
from ._episode_resolution import CONF_TITLE_WINS_INEXACT, _fuzzy_title_equal
from ._movie_scanner import _build_subtitle_companions
from .episode_assignments import (
    ORIGIN_AUTO,
    REASON_AMBIGUOUS_RUN,
    REASON_NO_PARSE,
    REASON_NOT_IN_SEASON,
    EpisodeAssignmentTable,
)
from .models import PreviewItem

AbsoluteFileEntry = tuple[Path, int, str | None, list[int], bool, int | None]

_RE_LEADING_ABS_NUM = re.compile("^(\\d{1,4})\\s*[-–]\\s*")

_MIN_LOOKUP_SUBSTRING_LEN = 4


def _contiguous_run(episode_numbers: list[int], season_titles: dict) -> list[int]:
    """Contiguous episode run from ``episode_numbers[0]``, limited to slots
    that exist in ``season_titles``. A single-episode file yields ``[ep]``."""
    if not episode_numbers:
        return []
    run = [episode_numbers[0]]
    for episode in episode_numbers[1:]:
        if episode == run[-1] + 1 and episode in season_titles:
            run.append(episode)
        else:
            break
    return run


def collect_absolute_files(
    season_dirs: list[tuple[Path, int]],
) -> list[AbsoluteFileEntry]:
    """Collect all video files sorted by absolute episode number."""
    all_files: list[AbsoluteFileEntry] = []
    for season_dir, _season_num in season_dirs:
        for file_path in sorted(season_dir.iterdir()):
            if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
            season_hint = extract_season_number(file_path.name) if is_season_relative else None
            abs_num = episode_numbers[0] if episode_numbers else 9999
            all_files.append((file_path, abs_num, raw_title, episode_numbers, is_season_relative, season_hint))
    all_files.sort(key=lambda item: item[1])
    return all_files


def match_file_title_to_tmdb(
    raw_title: str | None,
    title_lookup: dict[str, tuple[int, int, str]],
    number_lookup: dict[int, tuple[int, int, str]],
    used: set[tuple[int, int]],
    spaced_lookup: dict[str, tuple[int, int, str]] | None = None,
) -> tuple[int, int, str] | None:
    """Match a file's title against the cross-season TMDB title lookup."""
    if not raw_title:
        return None

    cleaned_title = raw_title
    abs_match = _RE_LEADING_ABS_NUM.match(raw_title)
    if abs_match:
        abs_ep = int(abs_match.group(1))
        cleaned_title = raw_title[abs_match.end():]
        if abs_ep in number_lookup:
            result = number_lookup[abs_ep]
            if (result[0], result[1]) not in used:
                return result

    normalized = normalize_for_specials(cleaned_title)
    if not normalized:
        return None

    if normalized in title_lookup:
        result = title_lookup[normalized]
        if (result[0], result[1]) not in used:
            return result

    if len(normalized) < _MIN_LOOKUP_SUBSTRING_LEN:
        return None

    best: tuple[int, int, str] | None = None
    best_len = 0
    for key, value in title_lookup.items():
        if len(key) < _MIN_LOOKUP_SUBSTRING_LEN:
            continue
        if (value[0], value[1]) in used:
            continue
        if normalized in key or key in normalized:
            if len(key) > best_len:
                best = value
                best_len = len(key)
    if best is not None:
        return best

    if spaced_lookup:
        spaced = normalize_for_specials_spaced(cleaned_title)
        hits = [
            value
            for key_spaced, value in spaced_lookup.items()
            if (value[0], value[1]) not in used
            and _fuzzy_title_equal(
                normalized, spaced,
                re.sub(r"[^a-z0-9]", "", key_spaced), key_spaced,
            )
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def try_title_based_matching(
    all_files: list[AbsoluteFileEntry],
    tmdb_seasons: dict,
) -> list[tuple[int, int, str] | None] | None:
    """Two-phase matching: title claims first (all seasons incl. S0), then
    explicit season-hint number fills, then absolute-number prefixes. Title
    claims MUST run first so a mis-numbered file can't squat on a slot a
    genuinely-titled file owns (RC18a)."""
    title_lookup: dict[str, tuple[int, int, str]] = {}
    spaced_lookup: dict[str, tuple[int, int, str]] = {}
    file_count = len(all_files)
    qualifying_seasons = [
        season_num for season_num, season_data in tmdb_seasons.items()
        if season_num != 0 and season_data["count"] >= file_count
    ]
    number_lookup: dict[int, tuple[int, int, str]] = {}
    # Regular seasons first so an S0 special never shadows a same-titled
    # regular episode; S0 keys fill the remaining gaps (RC18d).
    for season_num in sorted(tmdb_seasons.keys(), key=lambda s: (s == 0, s)):
        season_data = tmdb_seasons[season_num]
        for episode_num, title in season_data["titles"].items():
            normalized = normalize_for_specials(title)
            if normalized and normalized not in title_lookup:
                title_lookup[normalized] = (season_num, episode_num, title)
                spaced_lookup[normalize_for_specials_spaced(title)] = (
                    season_num, episode_num, title,
                )
            if (
                season_num != 0
                and len(qualifying_seasons) == 1
                and season_num == qualifying_seasons[0]
                and episode_num not in number_lookup
            ):
                number_lookup[episode_num] = (season_num, episode_num, title)

    if not title_lookup:
        return None

    matches: list[tuple[int, int, str] | None] = [None] * file_count
    used: set[tuple[int, int]] = set()

    def _reserve(match, episode_numbers, is_season_relative, season_hint):
        season_num, episode_num, _title = match
        used.add((season_num, episode_num))
        season_data = tmdb_seasons.get(season_num)
        if (
            season_data
            and is_season_relative
            and season_hint == season_num
            and episode_numbers
            and episode_numbers[0] == episode_num
        ):
            for episode in _contiguous_run(episode_numbers, season_data["titles"]):
                used.add((season_num, episode))

    # Phase 1: pure title claims.
    for index, (_fp, _abs, raw_title, eps, rel, hint) in enumerate(all_files):
        match = match_file_title_to_tmdb(
            raw_title, title_lookup, {}, used, spaced_lookup=spaced_lookup,
        )
        if match is not None:
            matches[index] = match
            _reserve(match, eps, rel, hint)

    # Phase 2: explicit season-hint number fills; Phase 3: absolute prefixes.
    for index, (_fp, _abs, raw_title, eps, rel, hint) in enumerate(all_files):
        if matches[index] is not None:
            continue
        if rel and hint is not None and eps:
            season_data = tmdb_seasons.get(hint)
            if season_data:
                title = season_data["titles"].get(eps[0])
                if title and (hint, eps[0]) not in used:
                    match = (hint, eps[0], title)
                    matches[index] = match
                    _reserve(match, eps, rel, hint)
                    continue
        match = match_file_title_to_tmdb(raw_title, {}, number_lookup, used)
        if match is not None:
            matches[index] = match
            used.add((match[0], match[1]))

    matched_count = sum(1 for match in matches if match is not None)
    if matched_count < len(all_files) * 0.5:
        return None
    return matches


def build_consolidated_preview(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    root: Path,
    show_info: dict,
    media_fields: dict,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
) -> list[PreviewItem]:
    """Build preview mapping files in absolute order to TMDB structure."""
    all_files = collect_absolute_files(season_dirs)

    tmdb_list: list[tuple[int, int, str]] = []
    for season_num in sorted(tmdb_seasons.keys()):
        if season_num == 0:
            continue
        season_data = tmdb_seasons[season_num]
        for episode_num in sorted(season_data["titles"].keys()):
            tmdb_list.append((season_num, episode_num, season_data["titles"][episode_num]))

    for season_num, season_data in tmdb_seasons.items():
        store_tmdb_data(
            season_num,
            season_data["titles"],
            season_data["posters"],
            season_data.get("episodes", {}),
        )

    title_matches = try_title_based_matching(all_files, tmdb_seasons)
    if title_matches is not None:
        items: list[PreviewItem] = []
        for index, (file_path, _abs_num, _raw_title, episode_numbers, is_season_relative, season_hint) in enumerate(all_files):
            match = title_matches[index]
            if match is None:
                items.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=0,
                    episodes=episode_numbers,
                    status="SKIP: could not match episode title to TMDB",
                    **media_fields,
                ))
                continue
            season_num, episode_num, title = match
            season_titles = tmdb_seasons.get(season_num, {}).get("titles", {})
            if (
                is_season_relative
                and season_hint == season_num
                and len(episode_numbers) > 1
                and episode_numbers[0] == episode_num
            ):
                run = _contiguous_run(episode_numbers, season_titles)
            else:
                run = [episode_num]
            run_titles = [season_titles.get(episode, title) for episode in run]
            target_dir = root / f"Season {season_num:02d}"
            new_name = build_tv_name(
                show_info["name"],
                show_info["year"],
                season_num,
                run,
                run_titles,
                file_path.suffix,
            )
            episode_confidence = 0.7
            if (
                is_season_relative
                and season_hint == season_num
                and episode_numbers == run
            ):
                episode_confidence = 0.86
            item = PreviewItem(
                original=file_path,
                new_name=new_name,
                target_dir=target_dir,
                season=season_num,
                episodes=run,
                status="OK",
                episode_confidence=episode_confidence,
                **media_fields,
            )
            item.companions = _build_subtitle_companions(file_path, new_name)
            items.append(item)
        return items

    items: list[PreviewItem] = []
    tmdb_index = 0

    for file_path, _abs_num, _raw_title, episode_numbers, is_season_relative, _season_hint in all_files:
        if (
            is_season_relative
            and _season_hint is not None
            and _season_hint not in tmdb_seasons
        ):
            # An explicit S## that TMDB doesn't know can't be sequence-
            # mapped — the interleave corrupts every later slot (RC18c).
            items.append(PreviewItem(
                original=file_path,
                new_name=None,
                target_dir=None,
                season=0,
                episodes=episode_numbers,
                status="SKIP: explicit season not in TMDB",
                **media_fields,
            ))
            continue

        num_eps = max(1, len(episode_numbers))

        if tmdb_index >= len(tmdb_list):
            items.append(PreviewItem(
                original=file_path,
                new_name=None,
                target_dir=None,
                season=0,
                episodes=episode_numbers,
                status="SKIP: no matching TMDB episode (extra file?)",
                **media_fields,
            ))
            continue

        file_eps = []
        file_titles = []
        target_season = tmdb_list[tmdb_index][0]
        for offset in range(num_eps):
            if tmdb_index + offset < len(tmdb_list):
                season_num, episode_num, title = tmdb_list[tmdb_index + offset]
                file_eps.append(episode_num)
                file_titles.append(title)
                target_season = season_num
        tmdb_index += num_eps

        target_dir = root / f"Season {target_season:02d}"
        new_name = build_tv_name(
            show_info["name"],
            show_info["year"],
            target_season,
            file_eps,
            file_titles,
            file_path.suffix,
        )

        item = PreviewItem(
            original=file_path,
            new_name=new_name,
            target_dir=target_dir,
            season=target_season,
            episodes=file_eps,
            status="OK",
            episode_confidence=(
                0.86
                if is_season_relative
                and (_season_hint is None or _season_hint == target_season)
                else 0.3
            ),
            **media_fields,
        )
        item.companions = _build_subtitle_companions(file_path, new_name)
        items.append(item)

    return items


_CLUSTER_GAP_DAYS = 60


def _parse_air_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _air_date_clusters(season_data: dict) -> list[list[int]]:
    """Split a season's episodes into airing runs at multi-month gaps.

    Returns [] when any episode lacks a parseable air date — a partial
    clustering would mis-place everything after the hole.
    """
    episodes_meta = season_data.get("episodes", {}) or {}
    dated: list[tuple[int, date]] = []
    for episode_num in sorted(season_data.get("titles", {})):
        meta = episodes_meta.get(episode_num) or {}
        air = _parse_air_date(meta.get("air_date"))
        if air is None:
            return []
        dated.append((episode_num, air))
    if not dated:
        return []
    clusters: list[list[int]] = [[dated[0][0]]]
    previous = dated[0][1]
    for episode_num, air in dated[1:]:
        if (air - previous).days > _CLUSTER_GAP_DAYS:
            clusters.append([])
        clusters[-1].append(episode_num)
        previous = air
    return clusters


def apply_air_date_cluster_mapping(
    table: EpisodeAssignmentTable,
    tmdb_seasons: dict,
) -> None:
    """Map folder-season-N files onto the Nth airing cluster of a single
    consolidated TMDB season (Oshi no Ko S03 -> S01E25.., RC19). Review
    confidence — the mapping is inferred from air dates, not observed."""
    regular = [season for season in tmdb_seasons if season != 0]
    if len(regular) != 1:
        return
    target_season = regular[0]
    clusters = _air_date_clusters(tmdb_seasons[target_season])
    if len(clusters) < 2:
        return
    groups: dict[int, list[int]] = {}
    for file_id in table.unassigned_reasons:
        entry = table.files[file_id]
        hint = entry.season_hint
        if hint is None or hint == 0 or hint in tmdb_seasons:
            continue
        if not entry.parsed_episodes:
            continue
        groups.setdefault(hint, []).append(file_id)
    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    for hint, file_ids in groups.items():
        if hint > len(clusters):
            continue
        cluster = clusters[hint - 1]
        for file_id in sorted(
            file_ids, key=lambda f: table.files[f].parsed_episodes[0],
        ):
            entry = table.files[file_id]
            index = entry.parsed_episodes[0] - 1
            if index < 0 or index + len(entry.parsed_episodes) > len(cluster):
                continue
            proposed = cluster[index : index + len(entry.parsed_episodes)]
            slots = {(target_season, episode) for episode in proposed}
            if slots & claimed:
                continue
            table.assign(
                file_id, target_season, list(proposed), origin=ORIGIN_AUTO,
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"number", "air-date-cluster"}),
            )
            claimed |= slots


def _apply_resolution(table, file_id, season, resolution) -> None:
    if resolution.episodes:
        try:
            table.assign(
                file_id,
                season,
                list(resolution.episodes),
                origin="auto",
                confidence=resolution.confidence,
                evidence=resolution.evidence,
            )
            return
        except ValueError:
            table.mark_unassigned(file_id, REASON_AMBIGUOUS_RUN)
            return
    table.mark_unassigned(file_id, resolution.reason or "")


def build_consolidated_table(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    tmdb,
    show_info: dict,
    root: Path,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
) -> EpisodeAssignmentTable:
    """Build the assignment table for flat/mixed multi-season folders.

    Registers every TMDB season's slots (including Season 0), routes
    specials through the specials policy, and reconciles each regular
    file's absolute-mapped candidate through ``resolve_file`` so title
    evidence applies (the normal path already does this per file).
    """
    from .._parsing_titles import clean_title_evidence
    from ._episode_resolution import Resolution, resolve_file
    from ._tv_scanner_normal import _SPECIAL_STEM_PREFIX_RE, _register_season_slots

    table = EpisodeAssignmentTable()

    for season_num in sorted(s for s in tmdb_seasons if s != 0):
        season_data = tmdb_seasons[season_num]
        _register_season_slots(
            table, season_num,
            season_data.get("titles", {}), season_data.get("episodes", {}),
        )
        store_tmdb_data(
            season_num, season_data.get("titles", {}),
            season_data.get("posters", {}), season_data.get("episodes", {}),
        )

    if 0 in tmdb_seasons:
        s0_data = tmdb_seasons[0]
    else:
        s0_data = tmdb.get_season(show_info["id"], 0)
    s0_titles = s0_data.get("titles", {})
    if s0_titles:
        _register_season_slots(table, 0, s0_titles, s0_data.get("episodes", {}))
        store_tmdb_data(
            0, s0_titles, s0_data.get("posters", {}), s0_data.get("episodes", {}),
        )

    items = build_consolidated_preview(
        season_dirs=season_dirs,
        tmdb_seasons=tmdb_seasons,
        root=root,
        show_info=show_info,
        media_fields={},
        store_tmdb_data=store_tmdb_data,
    )
    mapped_by_path = {item.original: item for item in items}
    show_name_norm = normalize_for_specials(show_info.get("name") or "")

    for (
        file_path, _abs_num, raw_title, episode_numbers,
        is_season_relative, season_hint,
    ) in collect_absolute_files(season_dirs):
        if raw_title and normalize_for_specials(raw_title) == show_name_norm:
            raw_title = None
        entry = table.add_file(
            file_path,
            parsed_episodes=tuple(episode_numbers),
            raw_title=raw_title,
            is_season_relative=is_season_relative,
            season_hint=season_hint if is_season_relative else None,
            folder_season=season_hint,
        )

        if season_hint == 0:
            title_evidence = raw_title
            if not title_evidence and not episode_numbers:
                # Only titleless, numberless files fall back to the stem —
                # a stem that is just the episode marker ('S00E01') is not
                # title evidence (RC34).
                title_evidence = (
                    _SPECIAL_STEM_PREFIX_RE.sub("", file_path.stem).strip() or None
                )
            resolution = resolve_file(
                parsed_episodes=tuple(episode_numbers),
                raw_title=title_evidence,
                is_season_relative=is_season_relative,
                season_titles=s0_titles,
                season=0,
                season_hint=entry.season_hint,
            )
            _apply_resolution(table, entry.file_id, 0, resolution)
            continue

        item = mapped_by_path.get(file_path)
        if (
            item is not None
            and item.season is not None
            and item.episodes
            # SKIP items carry season=0 as a sentinel plus their parsed
            # numbers; only a REAL mapping (named target) may resolve here —
            # sentinels fall through to the hinted-season fallback.
            and item.new_name is not None
        ):
            cand_season = item.season
            if cand_season == 0:
                cand_titles = s0_titles
            else:
                cand_titles = tmdb_seasons.get(cand_season, {}).get("titles", {})
            # A file's explicit S## only vouches for its number within THAT
            # season. When the consolidated mapping lands in a different
            # TMDB season, the number is inferred, not season-relative.
            hint_matches = season_hint is None or season_hint == cand_season
            resolution = resolve_file(
                parsed_episodes=tuple(item.episodes),
                raw_title=raw_title,
                is_season_relative=is_season_relative and hint_matches,
                season_titles=cand_titles,
                season=cand_season,
            )
            if cand_season == 0 and (season_hint or 0) != 0 and resolution.episodes:
                # A hinted regular-season file landing in S0 is a
                # cross-season special pull -> review, never auto (RC18d).
                resolution = Resolution(
                    episodes=resolution.episodes,
                    confidence=min(resolution.confidence, CONF_TITLE_WINS_INEXACT),
                    evidence=resolution.evidence | {"cross-season-special"},
                )
            if resolution.episodes:
                # The consolidated pass picked this slot BY TITLE and
                # resolve_file re-matched the same title against it —
                # 'title-agree' here is self-confirming, so mark the origin.
                resolution = Resolution(
                    episodes=resolution.episodes,
                    confidence=resolution.confidence,
                    evidence=resolution.evidence | {"title-consolidated"},
                    reason=resolution.reason,
                )
            _apply_resolution(table, entry.file_id, cand_season, resolution)
        else:
            # A file the consolidated pass couldn't place still deserves a
            # real resolve_file run against its OWN hinted season — seg-run
            # and fuzzy title evidence live there (RC18e).
            fallback = None
            if season_hint is not None and season_hint != 0:
                hinted_titles = tmdb_seasons.get(season_hint, {}).get("titles", {})
                if hinted_titles:
                    candidate = resolve_file(
                        parsed_episodes=tuple(episode_numbers),
                        raw_title=raw_title,
                        is_season_relative=is_season_relative,
                        season_titles=hinted_titles,
                        season=season_hint,
                    )
                    if candidate.episodes:
                        fallback = (season_hint, candidate)
            if fallback is None and not episode_numbers and not raw_title and s0_titles:
                # No parsed episode and no extracted title: the cleaned
                # filename itself is the only evidence — root specials like
                # "The Henry & June Show (1999).mp4" live in flat consolidated
                # folders too (RC26).
                stem = clean_title_evidence(file_path.stem)
                stem = _SPECIAL_STEM_PREFIX_RE.sub("", stem).strip()
                if stem:
                    candidate = resolve_file(
                        parsed_episodes=(),
                        raw_title=stem,
                        is_season_relative=False,
                        season_titles=s0_titles,
                        season=0,
                    )
                    if candidate.episodes:
                        fallback = (0, candidate)
            if fallback is not None:
                _apply_resolution(table, entry.file_id, fallback[0], fallback[1])
            else:
                table.mark_unassigned(
                    entry.file_id,
                    REASON_NO_PARSE if not episode_numbers else REASON_NOT_IN_SEASON,
                )

    apply_air_date_cluster_mapping(table, tmdb_seasons)
    return table
