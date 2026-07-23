"""Batch orchestration for TV and movie library discovery/scanning."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import cast

from ..constants import SCORE_TIE_MARGIN, VIDEO_EXTENSIONS
from ..metadata_types import MediaInfo
from ..parsing import (
    best_tv_match_title,
    clean_folder_name,
    extract_provider_id_tag,
    extract_year,
    is_generic_show_folder_name,
    is_sample_file,
    looks_like_tv_episode,
)
from ..providers import MetadataProvider
from ..tmdb import TMDBClient
from . import _discovery_ports as _ports
from ._batch_tv_duplicates import (
    apply_duplicate_labels as _apply_tv_duplicate_labels,
    normalized_relative_folder as _normalized_tv_relative_folder,
)
from ._batch_tv_episode_claims import (
    assign_preview_source_folders as _assign_tv_preview_source_folders,
    reconcile_scanned_episode_claims as _reconcile_tv_episode_claims,
)
from ._batch_tv_match_policy import (
    count_season_subdirs as _count_tv_season_subdirs,
    episode_count_tiebreak as _episode_count_tiebreak,
    primary_name_breaks_tie as _primary_name_breaks_tie,
    year_hint_breaks_tie as _year_hint_breaks_tie,
)
from ._batch_tv_season_merge import (
    expanded_season_folders as _expanded_tv_season_folders,
    merge_season_siblings as _merge_tv_season_siblings,
    merge_umbrella_siblings as _merge_tv_umbrella_siblings,
    represented_seasons as _represented_tv_seasons,
    resolve_season_folder as _resolve_tv_season_folder,
    season_merge_priority as _season_merge_priority,
)
from ._provider_scan_guard import guard_season_map_scan
from ._rename_execution import check_duplicates
from ._scan_runtime import ScanCancelledError, fail_scan_state, raise_if_cancelled
from ._state import get_auto_accept_threshold
from .matching import (
    apply_movie_confidence_adjustments,
    best_episode_title_similarity,
    boost_scores_with_alt_titles,
    country_from_language,
    pick_alternate_matches,
    score_results,
    score_tv_results,
    tv_episode_evidence_adjustment,
)
from .models import (
    DirectEpisodeEvidence,
    PreviewItem,
    ScanState,
    SeasonFolderEntry,
    collect_direct_episode_evidence,
    infer_explicit_season_assignment,
    show_pin_key,
)
from .show_details import ShowDetails, show_details_from_tmdb

_log = logging.getLogger(__name__)


def _emit_scan_progress(
    progress_callback: Callable[..., object] | None,
    done: int,
    total: int,
    current_item: str,
    phase: str | None = None,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(done, total, current_item, phase)
    except TypeError:
        try:
            progress_callback(done, total, current_item)
        except TypeError:
            progress_callback(done, total)


class BatchTVOrchestrator:
    """
    Discovers TV show folders in a library root, matches each to TMDB,
    and creates ScanState instances for the GUI.

    Two-phase workflow:
      Phase 1 (match): Scan filesystem, identify show folders, parallel
          TMDB search. Fast — no season data fetched yet.
      Phase 2 (scan): For each matched show, run TVScanner to build
          episode previews. Can be triggered per-show or in bulk.

    Holds a small provider pool: ``tmdb`` is the primary provider, with an
    optional ``fallback_provider`` (e.g. TVDB) available for per-show
    routing. ``provider_for(state)`` resolves the provider a given
    ``ScanState`` is attributed to (via ``ScanState.provider_name``);
    show-scoped downstream metadata calls route through it instead of
    always using ``self.tmdb`` directly, so id-tag routing / fallback /
    switch-provider flows (later tasks) can attribute a show to either
    provider.

    ``fallback_provider`` being pooled and ``fallback_matching`` being
    enabled are independent: the pool should be fed whenever the other
    provider's API key exists (pin routing and ID-tag routing only need
    that), while ``fallback_matching`` gates just the confidence-based
    second-opinion PASS in ``_apply_fallback_matches``.
    """

    def __init__(
        self,
        tmdb: MetadataProvider,
        library_root: Path,
        discovery_service: _ports.TVLibraryDiscoverer,
        *,
        fallback_provider: MetadataProvider | None = None,
        provider_overrides: dict | None = None,
        id_tag_routing: bool = True,
        fallback_matching: bool = True,
    ):
        self.tmdb = tmdb
        self.fallback_provider = fallback_provider
        self.provider_overrides = dict(provider_overrides or {})
        self.id_tag_routing = id_tag_routing
        # Gates ONLY the second-opinion PASS in _apply_fallback_matches —
        # independent of whether fallback_provider is pooled at all. Pin
        # routing and ID-tag routing need only the tag/pin provider's key
        # (spec §2b/§5), not this flag; a caller can pool the other
        # provider for those purposes while keeping the confidence-gated
        # second-opinion search suppressed.
        self.fallback_matching = fallback_matching
        self.root = library_root
        self.states: list[ScanState] = []
        self.discovery_service = discovery_service

    def provider_named(self, name: str) -> MetadataProvider | None:
        """Resolve a provider in the pool by ``provider_name``, or None."""
        if name == self.tmdb.provider_name:
            return self.tmdb
        if self.fallback_provider is not None and name == self.fallback_provider.provider_name:
            return self.fallback_provider
        return None

    def provider_for(self, state: ScanState) -> MetadataProvider:
        """Resolve the provider a ``ScanState`` is attributed to.

        Falls back to the primary ``self.tmdb`` when the state's
        ``provider_name`` doesn't match a pooled provider (e.g. an unknown
        or stale name).
        """
        return self.provider_named(state.provider_name) or self.tmdb

    def _pinned_provider(self, folder: Path) -> MetadataProvider | None:
        """Resolve a persisted provider pin for *folder* to a pooled provider.

        Corrupt or unresolvable pins (not a mapping, missing/non-string
        ``"provider"``, or a provider name not in the pool) are ignored —
        pruning the stale entry happens the next time the GUI writes
        ``provider_overrides`` (Task 9's pin-write helper), not here.
        """
        pin = self.provider_overrides.get(show_pin_key(folder))
        if not isinstance(pin, dict):
            return None
        provider_name = pin.get("provider")
        if not isinstance(provider_name, str):
            return None
        return self.provider_named(provider_name)

    def _apply_duplicate_labels(self) -> None:
        _apply_tv_duplicate_labels(self.states)

    def _episode_count_tiebreak(
        self,
        scored: list[tuple[dict, float]],
        file_count: int,
        threshold: float = 0.10,
        compare_seasons: bool = False,
        explicit_seasons: set[int] | None = None,
        provider: MetadataProvider | None = None,
    ) -> tuple[dict, float, bool]:
        return _episode_count_tiebreak(
            provider or self.tmdb,
            scored,
            file_count,
            threshold=threshold,
            compare_seasons=compare_seasons,
            explicit_seasons=explicit_seasons,
        )

    @staticmethod
    def _collect_direct_episode_evidence(folder: Path) -> list[DirectEpisodeEvidence]:
        """Collect explicit ``S##E##`` evidence from direct child video files."""
        return collect_direct_episode_evidence(folder)

    @staticmethod
    def _best_episode_title_similarity(
        raw_title: str | None,
        season_titles: dict[int, str],
    ) -> float:
        return best_episode_title_similarity(raw_title, season_titles)

    def _tv_episode_evidence_adjustment(
        self,
        show_id: int,
        evidence: list[DirectEpisodeEvidence],
        provider: MetadataProvider | None = None,
    ) -> float:
        return tv_episode_evidence_adjustment(provider or self.tmdb, show_id, evidence)

    def _build_show_candidates(
        self,
        discovered: Sequence[_ports.TVDiscoveryCandidateLike],
        cancel_event: threading.Event | None = None,
    ) -> list[_ports.ShowCandidate]:
        candidates: list[_ports.ShowCandidate] = []
        for candidate in discovered:
            raise_if_cancelled(cancel_event)
            # A candidate named only with a season/collection label
            # ("Specials (1998-2003)", "Series") — typical when an umbrella's
            # season folders are empty on disk — would search TMDB for a show
            # literally called "Specials". Inherit the parent folder's title
            # (the parent must be inside the library, not the root itself).
            name_fallback = None
            if candidate.parent_relative_folder is not None and is_generic_show_folder_name(
                candidate.folder.name
            ):
                name_fallback = candidate.folder.parent
            cleaned = best_tv_match_title(
                candidate.folder,
                include_year=False,
                name_fallback_folder=name_fallback,
            )
            score_name = best_tv_match_title(
                candidate.folder,
                name_fallback_folder=name_fallback,
            )
            folder_score_name = clean_folder_name(
                (name_fallback or candidate.folder).name,
            )
            # When the generic-name fallback is active, the PARENT carries the
            # show's year; the child's own year range ("Specials (2003-06)")
            # is special air dates, not the show year (RC37).
            year_hint = None
            if name_fallback is not None:
                year_hint = extract_year(name_fallback.name)
            if year_hint is None:
                year_hint = extract_year(candidate.folder.name)
            episode_evidence = self._collect_direct_episode_evidence(candidate.folder)
            candidates.append(
                (
                    candidate,
                    cleaned,
                    score_name,
                    folder_score_name,
                    year_hint,
                    episode_evidence,
                )
            )
        return candidates

    @staticmethod
    def _candidate_state_kwargs(
        candidate: _ports.TVDiscoveryCandidateLike,
    ) -> _ports.TVCandidateStateKwargs:
        """Return the ``ScanState`` fields copied from a discovery candidate."""
        return {
            "relative_folder": candidate.relative_folder,
            "parent_relative_folder": candidate.parent_relative_folder,
            "discovery_reason": candidate.discovery_reason,
            "has_direct_season_subdirs": candidate.has_direct_season_subdirs,
            "direct_episode_file_count": candidate.direct_episode_file_count,
            "direct_video_file_count": candidate.direct_video_file_count,
            "discovered_via_symlink": candidate.discovered_via_symlink,
        }

    @classmethod
    def _build_unmatched_show_state(
        cls,
        candidate: _ports.TVDiscoveryCandidateLike,
        folder: Path,
        year_hint: str | None,
        results: list[dict],
        episode_evidence: list[DirectEpisodeEvidence],
        provider_name: str = "tmdb",
    ) -> ScanState:
        return ScanState(
            folder=folder,
            media_info={
                "id": None,
                "name": folder.name,
                "year": year_hint or "",
                "poster_path": None,
                "overview": "",
            },
            confidence=0.0,
            provider_name=provider_name,
            search_results=results,
            alternate_matches=[],
            checked=False,
            season_assignment=infer_explicit_season_assignment(folder, episode_evidence),
            **cls._candidate_state_kwargs(candidate),
        )

    def _show_details_for_match(
        self, best: MediaInfo, provider: MetadataProvider | None = None
    ) -> ShowDetails | None:
        show_id = best.get("id")
        if type(show_id) is not int:
            return None
        return show_details_from_tmdb((provider or self.tmdb).get_tv_details(show_id))

    @staticmethod
    def _season_names_for_match(details: ShowDetails | None) -> dict[int, str]:
        season_names: dict[int, str] = {}
        if details is None:
            return season_names
        for season in details.seasons:
            if season.season_number <= 0 or not season.name:
                continue
            if season.name != f"Season {season.season_number}":
                season_names[season.season_number] = season.name
        return season_names

    def _select_best_show_match(
        self,
        candidate: _ports.TVDiscoveryCandidateLike,
        folder: Path,
        score_name: str,
        folder_score_name: str,
        year_hint: str | None,
        episode_evidence: list[DirectEpisodeEvidence],
        results: list[dict],
        cancel_event: threading.Event | None = None,
        provider: MetadataProvider | None = None,
    ) -> tuple[dict, float, list[dict], bool, dict[int, str]]:
        provider = provider or self.tmdb
        scored = score_tv_results(
            results,
            score_name,
            year_hint,
            provider,
            folder=folder,
            folder_score_name=folder_score_name,
            episode_evidence=episode_evidence,
        )

        best, best_score = scored[0]

        file_count = candidate.direct_video_file_count
        use_seasons = False
        if file_count == 0 and candidate.has_direct_season_subdirs:
            raise_if_cancelled(cancel_event)
            file_count = _count_tv_season_subdirs(candidate.folder)
            use_seasons = True
        # When direct files carry explicit S##E## evidence, the file count is
        # one season's worth of episodes — compare against the candidates'
        # matching-season episode counts rather than whole-show totals.
        explicit_seasons = {item.season_num for item in episode_evidence} or None
        tie_broken_by_counts = False
        if file_count > 0 and len(scored) >= 2:
            _runner_up, runner_up_score = scored[1]
            if best_score - runner_up_score <= 0.10:
                best, best_score, tie_broken_by_counts = self._episode_count_tiebreak(
                    scored,
                    file_count,
                    threshold=0.10,
                    compare_seasons=use_seasons,
                    explicit_seasons=None if use_seasons else explicit_seasons,
                    provider=provider,
                )

        ep_file_count = file_count if not use_seasons else candidate.direct_episode_file_count
        details = self._show_details_for_match(best, provider)
        if ep_file_count > 0 and details is not None:
            tmdb_ep_count = details.number_of_episodes
            if tmdb_ep_count > 0:
                if ep_file_count == tmdb_ep_count:
                    best_score = min(best_score + 0.10, 1.0)
                elif abs(ep_file_count - tmdb_ep_count) <= 2:
                    best_score = min(best_score + 0.05, 1.0)

        # Clamp the winner onto the [0, 1] scale for the stored/returned
        # confidence. Stacked exact-title bonuses push raw scores past 1.0;
        # tie detection below compares the RAW scores instead (see comment
        # there) so this clamp doesn't affect the margin calculation.
        best_score = min(best_score, 1.0)

        alternates = pick_alternate_matches(
            scored,
            selected_id=best.get("id"),
            limit=3,
        )

        # Tie detection compares RAW scored values: shared boosts (alt-title,
        # episode evidence) cancel out on both sides, while per-candidate
        # evidence like a year-hint match survives. Clamping both sides first
        # (the previous approach) erased real margins once boosts pushed both
        # raw scores past 1.0 — the Powerpuff 1998-vs-2016 regression.
        tie_detected = False
        if len(scored) >= 2 and not tie_broken_by_counts:
            raw_by_id = {result.get("id"): score for result, score in scored}
            raw_best = raw_by_id.get(best.get("id"), best_score)
            for result, raw_runner in scored:
                if result.get("id") != best.get("id"):
                    if (
                        raw_best - raw_runner <= SCORE_TIE_MARGIN
                        and best_score >= get_auto_accept_threshold()
                        and not _primary_name_breaks_tie(
                            best,
                            result,
                            score_name,
                            year_hint,
                        )
                        and not _year_hint_breaks_tie(best, result, year_hint)
                    ):
                        tie_detected = True
                    break

        season_names = self._season_names_for_match(details)
        return best, best_score, alternates, tie_detected, season_names

    def _build_discovered_show_state(
        self,
        candidate: _ports.TVDiscoveryCandidateLike,
        score_name: str,
        folder_score_name: str,
        year_hint: str | None,
        episode_evidence: list[DirectEpisodeEvidence],
        results: list[dict],
        cancel_event: threading.Event | None = None,
        provider: MetadataProvider | None = None,
    ) -> ScanState:
        provider = provider or self.tmdb
        folder = candidate.folder
        if not results:
            return self._build_unmatched_show_state(
                candidate,
                folder,
                year_hint,
                results,
                episode_evidence,
                provider_name=provider.provider_name,
            )

        best, best_score, alternates, tie_detected, season_names = self._select_best_show_match(
            candidate,
            folder,
            score_name,
            folder_score_name,
            year_hint,
            episode_evidence,
            results,
            cancel_event=cancel_event,
            provider=provider,
        )
        return ScanState(
            folder=folder,
            media_info=best,
            confidence=best_score,
            provider_name=provider.provider_name,
            search_results=results,
            alternate_matches=alternates,
            checked=False,
            tie_detected=tie_detected,
            season_names=season_names,
            season_assignment=infer_explicit_season_assignment(
                folder,
                episode_evidence,
                show_name=best.get("name"),
            ),
            **self._candidate_state_kwargs(candidate),
        )

    def _try_id_tag_state(
        self,
        candidate: _ports.TVDiscoveryCandidateLike,
        entry: _ports.ShowCandidate,
    ) -> ScanState | None:
        """Resolve a bracketed provider-ID tag on *candidate* to a state.

        Recognized tags (``{tvdb-81189}``, ``[tmdb-1396]``, ...) on the candidate's
        own folder name, or on its umbrella parent when the generic-name fallback
        is active, skip search/scoring and resolve by direct ``get_tv_details``.
        Returns ``None`` when routing is disabled, no tag is present, the tag's
        provider isn't in the pool, or the direct lookup fails.
        """
        if not self.id_tag_routing:
            return None
        source_name = candidate.folder.name
        tag = extract_provider_id_tag(source_name)
        if (
            tag is None
            and candidate.parent_relative_folder is not None
            and is_generic_show_folder_name(source_name)
        ):
            tag = extract_provider_id_tag(candidate.folder.parent.name)
        if tag is None:
            return None
        provider = self.provider_named(tag[0])
        if provider is None:
            _log.info("ID tag %s on %s: provider unavailable", tag, source_name)
            return None
        details = show_details_from_tmdb(provider.get_tv_details(tag[1]))
        if details is None or details.id is None:
            _log.warning("ID tag %s on %s: lookup failed", tag, source_name)
            return None
        (_candidate, _cleaned, _score_name, _folder_score_name, _year_hint, episode_evidence) = (
            entry
        )
        media_info: MediaInfo = {
            "id": details.id,
            "name": details.name,
            "year": (details.first_air_date or "")[:4],
            "poster_path": details.poster_path,
            "overview": details.overview,
        }
        state = ScanState(
            folder=candidate.folder,
            media_info=media_info,
            confidence=1.0,
            match_origin="id_tag",
            provider_name=provider.provider_name,
            search_results=[],
            alternate_matches=[],
            checked=False,
            season_assignment=infer_explicit_season_assignment(
                candidate.folder, episode_evidence, show_name=details.name
            ),
            **self._candidate_state_kwargs(candidate),
        )
        state.season_names = self._season_names_for_match(details)
        return state

    @staticmethod
    def _sort_discovered_show_state(state: ScanState) -> tuple[int, str, str]:
        if state.duplicate_of is not None:
            group = 3
        elif state.show_id is None:
            group = 2
        elif state.needs_review:
            group = 1
        else:
            group = 0
        return (
            group,
            state.display_name.lower(),
            _normalized_tv_relative_folder(state.relative_folder, state.folder),
        )

    def discover_shows(
        self,
        progress_callback: Callable[..., object] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[ScanState]:
        """Phase 1: Find show folders and match to TMDB."""
        discovered = self.discovery_service.discover_show_roots(self.root)
        candidates = self._build_show_candidates(discovered, cancel_event=cancel_event)

        if not candidates:
            return []

        _log.info("Discovered %d candidate show folders", len(candidates))

        # A persisted provider pin (Task 8: switch_provider) outranks an
        # ID tag — the pin routes the candidate's SEARCH to the pinned
        # provider and skips ID-tag resolution entirely. Everything else
        # falls through to the existing tag-then-search flow. Candidates
        # whose folder (or umbrella parent) carries a recognized provider-ID
        # tag skip the batch search entirely — they're resolved by a direct
        # get_tv_details lookup below instead.
        id_routed: dict[int, ScanState] = {}
        provider_by_index: dict[int, MetadataProvider] = {}
        pinned_indices: set[int] = set()
        search_groups: dict[str, list[int]] = defaultdict(list)
        for candidate_index, entry in enumerate(candidates):
            candidate = entry[0]
            pinned_provider = self._pinned_provider(candidate.folder)
            if pinned_provider is not None:
                provider_by_index[candidate_index] = pinned_provider
                pinned_indices.add(candidate_index)
                search_groups[pinned_provider.provider_name].append(candidate_index)
                continue
            state = self._try_id_tag_state(candidate, entry)
            if state is not None:
                id_routed[candidate_index] = state
            else:
                provider_by_index[candidate_index] = self.tmdb
                search_groups[self.tmdb.provider_name].append(candidate_index)

        results_by_index: dict[int, list[dict]] = {}
        for indices in search_groups.values():
            provider = provider_by_index[indices[0]]
            queries = [(candidates[i][1], candidates[i][4]) for i in indices]
            searched = provider.search_tv_batch(queries, progress_callback=progress_callback)
            for i, result in zip(indices, searched, strict=False):
                results_by_index[i] = result

        states: list[ScanState] = []
        total_candidates = len(candidates)
        _emit_scan_progress(
            progress_callback,
            0,
            total_candidates,
            "Preparing matched shows...",
            "Preparing matched shows...",
        )
        for candidate_index, (
            candidate,
            _cleaned_name,
            score_name,
            folder_score_name,
            year_hint,
            episode_evidence,
        ) in enumerate(candidates):
            raise_if_cancelled(cancel_event)
            if candidate_index in id_routed:
                states.append(id_routed[candidate_index])
            else:
                states.append(
                    self._build_discovered_show_state(
                        candidate,
                        score_name,
                        folder_score_name,
                        year_hint,
                        episode_evidence,
                        results_by_index[candidate_index],
                        cancel_event=cancel_event,
                        provider=provider_by_index[candidate_index],
                    )
                )
            _emit_scan_progress(
                progress_callback,
                candidate_index + 1,
                total_candidates,
                candidate.folder.name,
                "Preparing matched shows...",
            )

        if self.fallback_provider is not None and self.fallback_matching:
            self._apply_fallback_matches(
                candidates, states, pinned_indices, progress_callback, cancel_event
            )

        _emit_scan_progress(
            progress_callback,
            0,
            0,
            "Merging related seasons...",
            "Preparing matched shows...",
        )
        states = _merge_tv_season_siblings(states)
        states = _merge_tv_umbrella_siblings(states)
        states.sort(key=self._sort_discovered_show_state)

        self.states = states
        self._apply_duplicate_labels()
        self.states.sort(key=self._sort_discovered_show_state)
        return states

    def _apply_fallback_matches(
        self,
        candidates: list[_ports.ShowCandidate],
        states: list[ScanState],
        pinned_indices: set[int] | None = None,
        progress_callback: Callable[..., object] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Second-opinion pass: weak primary matches retry on the fallback
        provider; adopted only on a strictly better score, always flagged
        for review (spec: fallback never auto-accepts).

        A folder the primary couldn't match at all (``show_id is None``,
        confidence 0.0) is included in ``weak`` too — it's the strongest
        case for a second opinion, not a reason to skip one. This is safe
        because adoption always sets ``match_origin="fallback"``, which
        ``ScanState.needs_review`` treats as always-review regardless of
        the adopted score.

        A candidate whose provider was pinned by the user (``pinned_indices``)
        is excluded even when its search came back weak: a pin means "use
        this provider for this show," so a weak-but-pinned match must stay
        on the pinned provider rather than being second-guessed away from it.
        """
        assert self.fallback_provider is not None
        raise_if_cancelled(cancel_event)
        threshold = get_auto_accept_threshold()
        pinned = pinned_indices or set()
        weak = [
            index
            for index, state in enumerate(states)
            if index not in pinned and state.match_origin == "auto" and state.confidence < threshold
        ]
        if not weak:
            return
        queries = [(candidates[index][1], candidates[index][4]) for index in weak]
        _emit_scan_progress(
            progress_callback,
            0,
            len(weak),
            "Trying fallback source...",
            "Trying fallback source...",
        )
        try:
            all_results = self.fallback_provider.search_tv_batch(
                queries, progress_callback=progress_callback
            )
        except Exception:
            _log.exception("Fallback provider search failed; keeping primary matches")
            return
        for index, results in zip(weak, all_results, strict=False):
            raise_if_cancelled(cancel_event)
            if not results:
                continue
            (candidate, _cleaned, score_name, folder_score_name, year_hint, evidence) = candidates[
                index
            ]
            try:
                best, best_score, alternates, tie_detected, season_names = (
                    self._select_best_show_match(
                        candidate,
                        candidate.folder,
                        score_name,
                        folder_score_name,
                        year_hint,
                        evidence,
                        results,
                        cancel_event=cancel_event,
                        provider=self.fallback_provider,
                    )
                )
            except ScanCancelledError:
                raise
            except Exception:
                _log.exception("Fallback scoring failed for %s", candidate.folder.name)
                continue
            if best_score <= states[index].confidence:
                continue
            state = states[index]
            state.media_info = best
            state.confidence = best_score
            state.match_origin = "fallback"
            state.provider_name = self.fallback_provider.provider_name
            state.alternate_matches = alternates
            state.search_results = results
            state.tie_detected = tie_detected
            state.season_names = season_names
            # The show-name-suffix branch of infer_explicit_season_assignment
            # depends on the MATCHED show's name — recompute against the
            # adopted (fallback) name rather than leaving the primary-derived
            # assignment, which season-sibling merges group by right after
            # this pass (mirrors _build_discovered_show_state).
            state.season_assignment = infer_explicit_season_assignment(
                candidate.folder,
                evidence,
                show_name=best.get("name"),
            )

    def merge_rematched_state(self, state: ScanState) -> ScanState:
        """Merge a rematched season/special state into existing show siblings."""
        show_key = state.provider_show_key
        state_seasons = _represented_tv_seasons(state)
        if show_key is None or not state_seasons:
            self._apply_duplicate_labels()
            return state

        merge_group: list[ScanState] = [state]
        covered_seasons = set(state_seasons)
        for other in self.states:
            if other is state or other.provider_show_key != show_key:
                continue
            other_seasons = _represented_tv_seasons(other)
            if not other_seasons or covered_seasons & other_seasons:
                continue
            merge_group.append(other)
            covered_seasons.update(other_seasons)

        if len(merge_group) == 1:
            self._apply_duplicate_labels()
            return state

        target = max(merge_group, key=_season_merge_priority)
        season_map: dict[int, SeasonFolderEntry] = {}
        total_files = 0
        total_episode_files = 0
        merged_search_results = target.search_results
        merged_alternates = target.alternate_matches
        merged_tie_detected = target.tie_detected
        merged_checked = False

        for member in merge_group:
            total_files += member.direct_video_file_count
            total_episode_files += member.direct_episode_file_count
            for season_num, folder in _expanded_tv_season_folders(member).items():
                season_map[season_num] = folder
            for season_num, name in member.season_names.items():
                target.season_names.setdefault(season_num, name)
            if member is state:
                merged_search_results = member.search_results
                merged_alternates = member.alternate_matches
                merged_tie_detected = member.tie_detected
            merged_checked = merged_checked or member.checked

        target.media_info = state.media_info
        target.confidence = max(member.confidence for member in merge_group)
        target.match_origin = state.match_origin
        target.search_results = merged_search_results
        target.alternate_matches = merged_alternates
        target.tie_detected = merged_tie_detected
        target.checked = merged_checked
        target.season_folders = season_map
        target.season_assignment = None
        target.direct_video_file_count = total_files
        target.direct_episode_file_count = total_episode_files
        target.duplicate_of = None
        target.duplicate_of_relative_folder = None
        target.reset_scan()

        self.states[:] = [
            member for member in self.states if member not in merge_group or member is target
        ]
        self._apply_duplicate_labels()
        return target

    @guard_season_map_scan
    def scan_show(
        self,
        state: ScanState,
        progress_callback: Callable[..., object] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Phase 2: Run TVScanner for a single show and populate its ScanState."""
        if state.scanned or state.scanning:
            return
        if state.show_id is None:
            _log.warning("Cannot scan %s — no TMDB match", state.folder.name)
            return

        from ._tv_scanner import TVScanner

        raise_if_cancelled(cancel_event)
        state.scanning = True
        state.scan_error = None
        _log.info("Scanning episodes for: %s", state.display_name)

        try:
            scanner = TVScanner(
                self.provider_for(state),
                state.media_info,
                state.folder,
                season_hint=state.season_assignment,
                season_folders=state.season_folders or None,
                show_match_confidence=state.confidence,
            )
            items, has_mismatch = scanner.scan()
            raise_if_cancelled(cancel_event)

            _log.info(
                "Folder '%s' produced %d items (mismatch=%s), seasons: %s",
                state.folder.name,
                len(items),
                has_mismatch,
                sorted({item.season for item in items if item.season is not None}),
            )

            if has_mismatch:
                _log.info(
                    "Season mismatch detected for %s, using consolidated scan",
                    state.display_name,
                )
                items = scanner.scan_consolidated()
                raise_if_cancelled(cancel_event)

            check_duplicates(items)
            state.preview_items = items
            _assign_tv_preview_source_folders(state, self.root)

            initial_checked = {index for index, item in enumerate(items) if item.status == "OK"}
            completeness = scanner.get_completeness(items, checked_indices=initial_checked)

            state.scanner = scanner
            state.assignments = scanner.assignment_table
            state.completeness = completeness
            state.scanned = True

            has_actionable = any(item.is_actionable for item in items)
            if not has_actionable:
                state.checked = False
        finally:
            state.scanning = False
        by_season: dict[int | None, int] = defaultdict(int)
        for item in items:
            by_season[item.season] += 1
        _log.info(
            "Scan complete for '%s': %d total items, seasons: %s",
            state.display_name,
            len(items),
            # None seasons (unparseable root files) must not break the sort.
            dict(sorted(by_season.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))),
        )

    def scan_all(
        self,
        progress_callback: Callable[..., object] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Phase 2 bulk: Scan all shows that have a TMDB match."""
        to_scan = [
            state for state in self.states if not state.scanned and state.show_id is not None
        ]
        total = len(to_scan)

        for index, state in enumerate(to_scan):
            raise_if_cancelled(cancel_event)
            _emit_scan_progress(progress_callback, index, total, state.display_name)
            try:
                self.scan_show(state, cancel_event=cancel_event)
            except Exception as error:
                if isinstance(error, ScanCancelledError):
                    raise
                # Keep the failure user-visible: an empty show with no
                # explanation reads as "no episodes found" (RC40).
                fail_scan_state(state, error)
                _log.exception("Failed to scan %s: %s", state.display_name, error)
            _emit_scan_progress(progress_callback, index + 1, total, state.display_name)

        _emit_scan_progress(
            progress_callback,
            0,
            0,
            "Reconciling merged seasons...",
            "Reconciling scan results...",
        )
        self._reconcile_scanned_siblings(cancel_event=cancel_event)
        _emit_scan_progress(
            progress_callback,
            0,
            0,
            "Reconciling episode claims...",
            "Reconciling scan results...",
        )
        self.reconcile_scanned_episode_claims()

    def reconcile_scanned_episode_claims(self, state: ScanState | None = None) -> ScanState | None:
        """Merge scanned same-show siblings by episode claim."""
        if not hasattr(self, "root"):
            return state
        replacements = _reconcile_tv_episode_claims(self.states, self.root)
        if state is None:
            return None
        return replacements.get(id(state), state)

    def reconcile_scanned_state(self, state: ScanState) -> ScanState:
        """Try to merge a freshly-scanned state into a same-show sibling."""
        if state.show_id is None or not state.preview_items:
            return state
        if state.season_folders or state.season_assignment is not None:
            return state
        detected = {item.season for item in state.preview_items if item.season is not None}
        if len(detected) != 1:
            return state
        season_num = next(iter(detected))
        has_sibling = any(
            other is not state and other.provider_show_key == state.provider_show_key
            for other in self.states
        )
        if not has_sibling:
            return state
        state.season_folders = {
            season_num: _resolve_tv_season_folder(state.folder, season_num),
        }
        return self.merge_rematched_state(state)

    def _reconcile_scanned_siblings(
        self,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Post-scan pass: merge same-show siblings into multi-season cards."""
        groups: dict[tuple[str, int], list[ScanState]] = {}
        for state in self.states:
            key = state.provider_show_key
            if key is None:
                continue
            groups.setdefault(key, []).append(state)

        for group in groups.values():
            if len(group) < 2:
                continue
            for state in list(group):
                raise_if_cancelled(cancel_event)
                if state not in self.states:
                    continue
                reconciled = self.reconcile_scanned_state(state)
                if reconciled.scanned:
                    continue
                try:
                    self.scan_show(reconciled, cancel_event=cancel_event)
                except ScanCancelledError:
                    raise
                except Exception as error:
                    _log.error(
                        "Failed to re-scan merged %s: %s",
                        reconciled.display_name,
                        fail_scan_state(reconciled, error),
                    )

    def rematch_show(self, state: ScanState, new_match: dict) -> ScanState:
        """Swap a show's TMDB match and invalidate its scan data."""
        state.media_info = new_match
        raw_name = best_tv_match_title(state.folder)
        year_hint = extract_year(state.folder.name)
        scored = score_tv_results(
            [new_match], raw_name, year_hint, self.provider_for(state), folder=state.folder
        )
        state.confidence = scored[0][1] if scored else 0.0
        state.reset_scan()
        merged_state = self.merge_rematched_state(state)
        self._apply_duplicate_labels()
        return merged_state

    def switch_provider(self, state: ScanState, provider_name: str) -> tuple[ScanState, bool]:
        """Re-resolve *state* on another provider (user action — pins it)."""
        provider = self.provider_named(provider_name)
        if provider is None or provider_name == state.provider_name:
            return state, False
        raw_name = best_tv_match_title(state.folder, include_year=False)
        year_hint = extract_year(state.folder.name)
        try:
            results = provider.search_tv(raw_name, year_hint)
        except Exception:
            _log.exception("switch_provider search failed for %s", state.folder.name)
            return state, False
        if not results:
            return state, False
        scored = score_tv_results(results, raw_name, year_hint, provider, folder=state.folder)
        best, best_score = scored[0]
        state.media_info = best
        state.confidence = min(best_score, 1.0)
        state.match_origin = "manual"
        state.provider_name = provider_name
        state.search_results = results
        state.alternate_matches = pick_alternate_matches(
            scored, selected_id=best.get("id"), limit=3
        )
        state.tie_detected = False
        details = self._show_details_for_match(best, provider)
        state.season_names = self._season_names_for_match(details)
        # Mirrors the fallback-adoption recompute (8e9f763): the
        # show-name-suffix branch of infer_explicit_season_assignment
        # depends on the MATCHED show's name, which just changed. No
        # candidate evidence tuple is available here (unlike
        # discover_shows/_apply_fallback_matches) — passing evidence=None
        # lets the helper collect direct S##E## evidence from disk itself.
        state.season_assignment = infer_explicit_season_assignment(
            state.folder, show_name=best.get("name")
        )
        state.reset_scan()
        merged = self.merge_rematched_state(state)
        self._apply_duplicate_labels()
        return merged, True


class BatchMovieOrchestrator:
    """
    Discovers movie folders in a library root, matches each to TMDB,
    and creates ScanState instances for the GUI.

    Two-phase workflow:
      Phase 1 (discover): Scan filesystem via the injected MovieLibraryDiscoverer,
          identify movie_root and multi_movie_folder candidates, parallel
          TMDB search.
      Phase 2 (scan): For each matched movie, build PreviewItems with
          rename plans. Can be triggered per-movie or in bulk.
    """

    def __init__(
        self,
        tmdb: TMDBClient,
        library_root: Path,
        discovery_service: _ports.MovieLibraryDiscoverer,
    ):
        self.tmdb = tmdb
        self.root = library_root
        self.states: list[ScanState] = []
        self.discovery_service = discovery_service

    @staticmethod
    def _normalized_relative_folder(relative_folder: str, fallback: Path) -> str:
        text = relative_folder or fallback.as_posix()
        return text.replace("\\", "/").casefold()

    @classmethod
    def _is_ready_movie_candidate(cls, state: ScanState) -> bool:
        return bool(
            state.scanned
            and state.preview_items
            and not any(item.is_actionable for item in state.preview_items)
        )

    @classmethod
    def _duplicate_priority(cls, state: ScanState) -> tuple[int, float, int, int, str]:
        normalized_relative = cls._normalized_relative_folder(
            state.relative_folder,
            state.folder,
        )
        depth = len(PurePosixPath(normalized_relative).parts)
        ready_rank = 0 if cls._is_ready_movie_candidate(state) else 1
        evidence_rank = 0 if state.discovery_reason == "title_year_folder" else 1
        return (ready_rank, -state.confidence, depth, evidence_rank, normalized_relative)

    def _apply_duplicate_labels(self) -> None:
        """Mark lower-priority TMDB matches as duplicates deterministically."""
        for state in self.states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        groups: dict[int, list[ScanState]] = {}
        for state in self.states:
            movie_id = state.show_id
            if movie_id is None:
                continue
            groups.setdefault(movie_id, []).append(state)

        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=self._duplicate_priority)
            primaries: dict[int | None, ScanState] = {}
            for state in group:
                season_assignment = state.season_assignment
                if season_assignment is not None:
                    existing = primaries.get(season_assignment)
                    if existing is None:
                        primaries[season_assignment] = state
                        continue
                else:
                    existing = next(iter(primaries.values()), None) if primaries else None
                    if existing is None:
                        primaries[None] = state
                        continue
                state.duplicate_of = existing.display_name
                state.duplicate_of_relative_folder = existing.relative_folder or None
                state.checked = False

    def discover_movies(
        self,
        progress_callback: Callable[..., object] | None = None,
    ) -> list[ScanState]:
        """Phase 1: Find movie folders and match to TMDB."""
        from ._movie_scanner import _prepare_movie_query

        discovered = self.discovery_service.discover_movie_roots(self.root)

        entries: list[_ports.MovieCandidate] = []
        for candidate in discovered:
            if candidate.discovery_reason == "multiple_direct_video_files":
                video_files = sorted(
                    file
                    for file in candidate.folder.iterdir()
                    if file.is_file()
                    and file.suffix.lower() in VIDEO_EXTENSIONS
                    and not looks_like_tv_episode(file)
                    and not is_sample_file(file)
                )
                for video_file in video_files:
                    query, year, _raw = _prepare_movie_query(video_file.stem)
                    entries.append((candidate, query, year, video_file))
            else:
                cleaned = clean_folder_name(candidate.folder.name, include_year=False)
                year_hint = extract_year(candidate.folder.name)
                entries.append((candidate, cleaned, year_hint, None))

        if not entries:
            return []

        _log.info("Discovered %d movie candidate entries", len(entries))

        queries = [(name, year) for _, name, year, _ in entries]
        all_results = self.tmdb.search_movies_batch(
            queries,
            progress_callback=progress_callback,
        )

        states: list[ScanState] = []
        for (candidate, _search_query, year_hint, source_file), results in zip(
            entries, all_results, strict=False
        ):
            folder = candidate.folder

            if not results:
                display = source_file.stem if source_file else folder.name
                state = ScanState(
                    folder=folder,
                    media_info={
                        "id": None,
                        "title": display,
                        "year": year_hint or "",
                        "poster_path": None,
                        "overview": "",
                    },
                    confidence=0.0,
                    search_results=results,
                    alternate_matches=[],
                    checked=False,
                    source_file=source_file,
                    relative_folder=candidate.relative_folder,
                    parent_relative_folder=candidate.parent_relative_folder,
                    discovery_reason=candidate.discovery_reason,
                    direct_video_file_count=candidate.direct_video_file_count,
                    discovered_via_symlink=candidate.discovered_via_symlink,
                )
                states.append(state)
                continue

            raw_name = (
                clean_folder_name(source_file.stem)
                if source_file
                else clean_folder_name(folder.name)
            )
            scored = score_results(results, raw_name, year_hint, title_key="title")
            scored = boost_scores_with_alt_titles(
                scored,
                raw_name,
                year_hint,
                self.tmdb,
                title_key="title",
                media_type="movie",
                preferred_country=country_from_language(self.tmdb.language),
            )

            best, best_score = scored[0]
            alternates = [result for result, score in scored[1:4] if score > 0.3]

            # Tie detection compares raw scores (shared boosts cancel); the
            # stored confidence below is clamped separately.
            pre_adjust_best = min(best_score, 1.0)
            tie_detected = False
            if len(scored) >= 2:
                for result, raw_runner in scored:
                    if result.get("id") != best.get("id"):
                        if (
                            best_score - raw_runner <= SCORE_TIE_MARGIN
                            and pre_adjust_best >= get_auto_accept_threshold()
                        ):
                            tie_detected = True
                        break

            # Same evidence floors/caps the interactive MovieScanner applies
            # (sequel mismatch, year severely off) — the two entry points must
            # agree on the same folder (M-H2). Folder-shaped entries use the
            # folder name as their evidence stem, matching the query source.
            evidence_path = source_file if source_file is not None else folder / folder.name
            best_score = apply_movie_confidence_adjustments(
                raw_confidence=pre_adjust_best,
                file_path=evidence_path,
                tmdb_title=best.get("title", ""),
                tmdb_year=best.get("year"),
            )

            state = ScanState(
                folder=folder,
                media_info=best,
                confidence=best_score,
                search_results=results,
                alternate_matches=alternates,
                checked=False,
                source_file=source_file,
                relative_folder=candidate.relative_folder,
                parent_relative_folder=candidate.parent_relative_folder,
                discovery_reason=candidate.discovery_reason,
                direct_video_file_count=candidate.direct_video_file_count,
                discovered_via_symlink=candidate.discovered_via_symlink,
                tie_detected=tie_detected,
            )
            states.append(state)

        def _sort_key(state: ScanState) -> tuple:
            if state.duplicate_of is not None:
                group = 3
            elif state.show_id is None:
                group = 2
            elif state.needs_review:
                group = 1
            else:
                group = 0
            return (
                group,
                state.display_name.lower(),
                self._normalized_relative_folder(state.relative_folder, state.folder),
            )

        states.sort(key=_sort_key)

        self.states = states
        self._apply_duplicate_labels()
        self.states.sort(key=_sort_key)
        return states

    def scan_movie(
        self,
        state: ScanState,
        progress_callback: Callable[..., object] | None = None,
    ) -> None:
        """Phase 2: Build preview items for a single movie ScanState."""
        if state.scanned or state.scanning:
            return
        if state.show_id is None:
            _log.warning("Cannot scan %s — no TMDB match", state.folder.name)
            return

        from ._movie_scanner import (
            MovieScanner,
            _build_movie_preview_item,
            _build_subtitle_companions,
        )

        state.scanning = True
        _log.info("Scanning movie: %s", state.display_name)

        try:
            chosen = state.media_info
            if state.source_file is not None:
                video_files = [state.source_file] if state.source_file.exists() else []
            else:
                video_files = sorted(
                    file
                    for file in state.folder.iterdir()
                    if file.is_file()
                    and file.suffix.lower() in VIDEO_EXTENSIONS
                    and not is_sample_file(file)
                    and not looks_like_tv_episode(file)
                )

            items: list[PreviewItem] = []
            for file in video_files:
                item = _build_movie_preview_item(file, chosen, self.root)
                new_name = cast(str, item.new_name)
                item.companions = _build_subtitle_companions(file, new_name)
                if state.confidence < get_auto_accept_threshold():
                    item.status = (
                        f'REVIEW: best match "{chosen.get("title", "")}" '
                        f"(confidence {state.confidence:.0%}) — click to verify"
                    )
                items.append(item)

            check_duplicates(items)

            scanner = MovieScanner(self.tmdb, state.folder, files=video_files)
            for file in video_files:
                scanner.set_movie_info(file, chosen)
                scanner.set_search_results(file, state.search_results)

            state.scanner = scanner
            state.preview_items = items
            state.scanned = True

            has_actionable = any(item.is_actionable for item in items)
            if not has_actionable:
                state.checked = False
        finally:
            state.scanning = False

        self._apply_duplicate_labels()

    def scan_all(
        self,
        progress_callback: Callable[..., object] | None = None,
    ) -> None:
        """Phase 2 bulk: Scan all movies that have a TMDB match."""
        to_scan = [
            state
            for state in self.states
            if not state.scanned and not state.queued and state.show_id is not None
        ]
        total = len(to_scan)

        for index, state in enumerate(to_scan):
            try:
                self.scan_movie(state)
            except Exception as error:
                _log.error("Failed to scan %s: %s", state.display_name, error)
            if progress_callback:
                progress_callback(index + 1, total)
