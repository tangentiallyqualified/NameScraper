# Deferred Work

This is the sole authoritative backlog for unfinished NameScraper work.
Historical plans and specifications are recovery material, not current requirements.

Last reviewed: 2026-07-21 at `eb7f6df`

## Maintenance rules

- Add unfinished work here only after checking current code, tests, and audit evidence.
- Give each entry a stable ID from the appropriate family; never reuse an ID after an
  entry is completed or rejected.
- Keep `Status`, `Priority`, `Scope`, `Outcome`, `Acceptance`, and `Evidence` current.
- Remove completed entries from the active sections. Record a rejection below only
  when the decision prevents a known proposal from being repeatedly rediscovered.
- Treat current source and tests as stronger evidence than historical prose. A plan
  checkbox is never task status.
- Use priorities consistently: P1 affects correctness or a safety gate, P2 is a
  bounded product or maintainability improvement, and P3 is opportunistic hardening.

## Priority summary

| Priority | Meaning | Active IDs |
| --- | --- | --- |
| P1 | Correctness, recovery, or safety-gate gaps | `MATCH-001`, `QUAL-001` |
| P2 | Bounded feature and maintainability work | `PARSE-001`–`PARSE-005`, `MATCH-003`–`MATCH-004`, `META-001`–`META-006`, `MUX-001`–`MUX-003`, `MUX-005`, `GUI-002`, `ARCH-001`, `ARCH-003`, `QUAL-002` |
| P3 | Opportunistic polish and decision-covered debt | `MUX-004`, `MUX-006`, `GUI-003`, `QUAL-003`, `AUDIT-004`–`AUDIT-005` |

## Matching and parsing

### PARSE-001 — Parse parenthesized batch ranges

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Episode-number parsing for names such as `Show Name (01-12) [Batch]`.
- **Outcome:** Recognize an intentional parenthesized episode range without treating
  unrelated title numbers or years as ranges.
- **Acceptance:** The `batch range in parens` corpus record passes without `xfail`,
  alongside negative range/title ambiguity cases.
- **Evidence:** `tests/parsing_corpus.py` records the unresolved `(01-12)` example and
  its required range-versus-title policy.

### PARSE-002 — Disambiguate OVA title numbers from episode numbers

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** OVA filenames containing both a numeric title and a real episode suffix.
- **Outcome:** Prefer the episode token in `Area 88 OVA 01` while preserving genuine
  numeric-title behavior.
- **Acceptance:** The OVA-number corpus record passes without `xfail`, with regression
  coverage for numeric show and movie titles.
- **Evidence:** `tests/parsing_corpus.py` shows title number 88 currently winning over
  episode 01.

### PARSE-003 — Suppress dotted-version phantom episodes

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Movie/version strings such as `Evangelion 1.11 ... 2007`.
- **Outcome:** Prevent dotted version numbers from producing an episode assignment.
- **Acceptance:** The dotted-version corpus record returns no episodes and passes
  without `xfail`, while legitimate dotted episode conventions remain covered.
- **Evidence:** `tests/parsing_corpus.py` records the current phantom episode `[1]`.

### PARSE-004 — Classify four-digit seasons as TV

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Parsed `SYYYYE##` season/episode names.
- **Outcome:** Make TV classification agree with the parser for valid four-digit
  season identifiers without weakening year/movie guards.
- **Acceptance:** `Show.Name.S2020E01` is classified as TV and its corpus record passes
  without `xfail`; ordinary year-bearing movies remain non-TV.
- **Evidence:** `tests/parsing_corpus.py` notes that parsing succeeds but
  `looks_like_tv_episode` currently caps the season width at two digits.

### PARSE-005 — Parse `1x01x02` multi-episode names

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Cross-format `NxNNxNN` multi-episode notation.
- **Outcome:** Extract all episode numbers from a shared-season chain.
- **Acceptance:** `Show.Name.1x01x02` yields season 1 and episodes 1 and 2, and the
  corpus record passes without `xfail` with malformed-chain negatives.
- **Evidence:** `tests/parsing_corpus.py` explicitly marks this notation unsupported.

### MATCH-001 — Calibrate confidence tiers against real outcomes

- **Status:** Active deferred
- **Priority:** P1
- **Scope:** Shared episode-assignment confidence floors, caps, and review thresholds.
- **Outcome:** Characterize false approvals and needless reviews, then adjust named
  confidence tiers without bypassing explicit conflict evidence.
- **Acceptance:** A documented fixture set covers each changed tier, demonstrates the
  intended approve/review split, and passes the episode-resolution and scan suites.
- **Evidence:** `plex_renamer/engine/_episode_resolution.py` defines the named
  confidence constants and `apply_confidence_adjustments`; a deterministic search of
  `tests/` for `calibrat|false approval|needless review|outcome fixture` finds no
  outcome-calibration fixture set.

### MATCH-003 — Match date-named files to aired episodes

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Daily and talk-show filenames identified by `YYYY.MM.DD` or `YYYY-MM-DD`.
- **Outcome:** Resolve a parsed air date against provider episode metadata without
  minting phantom episode numbers from the date components.
- **Acceptance:** Date-based fixtures map to the unique matching episode, ambiguous or
  missing dates stay in review, and existing date-as-TV-signal cases keep passing.
- **Evidence:** `plex_renamer/_parsing_episodes.py` explicitly returns no episode
  evidence because downstream air-date matching does not yet exist;
  `tests/parsing_corpus.py` preserves date classification cases.

### MATCH-004 — Broaden TV library classification

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Show-root discovery and TV/movie classification beyond current filename
  token heuristics.
- **Outcome:** Add evidence-based classification for still-missed TV layouts without
  routing ordinary movies into the TV workflow.
- **Acceptance:** New positive fixtures for confirmed missed layouts and paired movie
  negatives pass through discovery and `looks_like_tv_episode` classification.
- **Evidence:** The active four-digit-season miss in `tests/parsing_corpus.py` and the
  classification boundary in `plex_renamer/app/services/tv_library_discovery_service.py`
  confirm remaining coverage gaps.

## Metadata providers and exported metadata

### META-001 — Add movie metadata-provider selection

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Provider selection for movie discovery and metadata generation.
- **Outcome:** Give movies a provider abstraction and setting equivalent to the TV
  provider path, with provider identity preserved on jobs.
- **Acceptance:** At least two registered movie providers can be selected and routed
  end to end in tests without changing TV provider behavior.
- **Evidence:** `SettingsService` and `_settings_schema.py` expose
  `tv_metadata_source` but no movie-provider key; a deterministic search of
  `plex_renamer/` and `tests/` for
  `movie_metadata_source|movie_provider|metadata_provider` returns no symbols.

### META-002 — Add TVDB key test UX

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Settings UI validation for the configured TVDB API key.
- **Outcome:** Let the user test TVDB credentials and receive a clear success or
  failure result without starting a scan.
- **Acceptance:** Settings tests cover success, rejected credentials, transport
  failure, disabled/empty-key state, and no key disclosure in messages.
- **Evidence:** `plex_renamer/gui_qt/widgets/_settings_tab_sections.py` provides a TVDB
  key field but no corresponding TVDB test action.

### META-003 — Show provider labels on jobs

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Queue and history job-row presentation.
- **Outcome:** Display the recorded provider for each job so fallback and per-show
  routing remain visible after scanning.
- **Acceptance:** TMDB and TVDB jobs render distinct provider labels in queue/history
  rows and retain the label after store round trips.
- **Evidence:** `RenameJob.data_source` is persisted in `plex_renamer/job_store.py`,
  but the job-row UI does not surface it.

### META-004 — Write provider ID tags into renamed output

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Optional folder/file naming for provider-qualified media IDs.
- **Outcome:** Emit canonical provider ID tags such as `{tvdb-12345}` in renamed
  output so later scans can route directly to the same source.
- **Acceptance:** A setting-gated formatter writes canonical tags for each supported
  provider, round-trips through ID-tag parsing, and avoids duplicate tags.
- **Evidence:** `_parsing_id_tags.extract_provider_id_tag` and
  `strip_provider_id_tags` implement input routing, while the output builders
  `build_tv_name`, `build_movie_name`, and `build_show_folder_name` accept no
  provider or media-ID argument.

### META-005 — Wire TVDB translations

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** TVDB v4 request language/translation handling.
- **Outcome:** Send the selected language through supported TVDB endpoints and apply
  deterministic fallback when a translation is unavailable.
- **Acceptance:** Transport tests assert language parameters and translated fields,
  plus default-language fallback and cache-key separation.
- **Evidence:** `plex_renamer/tvdb.py` explicitly says `language` is retained but not
  sent to TVDB endpoints.

### META-006 — Backfill or regenerate exported metadata

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Already-renamed folders and previously completed jobs with missing or
  stale NFO, artwork, tags, or related exported metadata.
- **Outcome:** Provide a safe, explicit regeneration workflow that does not require
  renaming media again.
- **Acceptance:** A dry-run-capable operation identifies eligible outputs, regenerates
  selected metadata idempotently, and reports partial failures without touching media.
- **Evidence:** `backfill_missing_queue_job_poster_paths` updates only
  `RenameJob.poster_path`; a deterministic search for NFO/artwork/tag metadata
  backfill or regeneration finds only the poster-path backfill tests.

## AutoMux and multi-part media

### MUX-001 — Add free-form manual part merging

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Manual grouping of an arbitrary ordered file selection into one episode.
- **Outcome:** Expose the existing ordered merge service through a multi-select UI,
  rather than limiting manual grouping to every claimant already on one conflict row.
- **Acceptance:** Users can select, order, merge, and ungroup valid files; invalid or
  cross-title selections are refused with merge-gate reasons.
- **Evidence:** `EpisodeMappingService.merge_files` accepts ordered IDs, while
  `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` currently groups the
  claimants of a single episode row.

### MUX-002 — Support movie multi-part merging

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** CD/Part-style movie files that form one logical movie output.
- **Outcome:** Extend part detection, validation, preview, and queue execution to the
  movie workflow without weakening TV merge gates.
- **Acceptance:** Ordered movie parts produce one preview and one verified merge job;
  incompatible tracks and ambiguous part sets stay unmerged with actionable errors.
- **Evidence:** `EpisodeMappingService.merge_files` requires an episode assignment
  table plus `season` and `episodes`, while `MovieScanner.scan` has no
  `detect_part_groups`, `part_group`, or merge path.

### MUX-003 — Deduplicate subtitle tracks

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Embedded subtitle tracks in AutoMux plans.
- **Outcome:** Detect semantically duplicate subtitle tracks using language, flags,
  codec, title, and content-safe evidence, then retain the preferred track.
- **Acceptance:** Duplicate, forced, commentary-like, and same-language distinct-track
  fixtures produce deterministic plans without deleting unique subtitles.
- **Evidence:** `_mux_planner.build_mux_plan` invokes
  `_mux_audio_dedup.dedupe_audio_decisions` only for `probe.audio_tracks`; a
  deterministic search for `subtitle.*dedup|dedup.*subtitle|dedupe_sub` returns no
  implementation or tests.

### MUX-004 — Prioritize multiple video tracks

- **Status:** Active deferred
- **Priority:** P3
- **Scope:** Inputs containing more than one video track.
- **Outcome:** Select or order the intended primary video track by an explicit,
  conservative policy and leave ambiguous files untouched.
- **Acceptance:** Resolution, default flag, codec, and ambiguity fixtures produce a
  deterministic selected track or a review result, never silent destructive removal.
- **Evidence:** `_mux_planner.build_mux_plan` emits every `probe.video_tracks` member
  with `keep=True` and reason `video`; it performs no ranking or ambiguity branch
  before adding those decisions.

### MUX-005 — Add per-title AutoMux policy overrides

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Reusable show/movie-specific overrides for AutoMux rules.
- **Outcome:** Allow a title to override global track policies without manually
  toggling each file or changing defaults for the rest of the library.
- **Acceptance:** Overrides persist by provider-qualified title identity, visibly
  affect preview plans, can be reset, and do not leak across titles.
- **Evidence:** Current controls provide global settings, per-show disablement, and
  session-scoped per-file opt-outs, but no persistent per-title rule layer.

### MUX-006 — Advance probe-cache eviction and sweep coordination

- **Status:** Active deferred
- **Priority:** P3
- **Scope:** Probe-cache recency and AutoMux warm-sweep scheduling under mixed demand.
- **Outcome:** Evaluate true LRU eviction and workload-aware sweep coordination beyond
  the current FIFO cache and one-worker executor downshift.
- **Acceptance:** Load/concurrency tests demonstrate fewer repeated probes and bounded
  foreground latency without duplicate probes, starvation, or shutdown leaks.
- **Evidence:** `plex_renamer/_mkv_probe.py` currently uses FIFO eviction at 512
  entries; `_media_workspace_automux.py` uses a fixed three-worker sweep with a binary
  executor-busy downshift.

## GUI and workflow follow-ups

### GUI-002 — Persist per-episode AutoMux opt-outs

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Per-file AutoMux opt-out state across scans and application sessions.
- **Outcome:** Store and restore opt-outs using a stable media identity, with clear
  reset behavior when the source changes.
- **Acceptance:** Restart/round-trip tests preserve opted-out files, avoid transferring
  state to unrelated files, and keep queue planning consistent with the UI.
- **Evidence:** `plex_renamer/engine/models.py` and
  `_media_workspace_actions.py` explicitly define the current opt-out as session-scoped.

### GUI-003 — Finish HiDPI and QSS literal cleanup

- **Status:** Active deferred
- **Priority:** P3
- **Scope:** Remaining unscaled widget geometry and literal pixel values in the Qt
  stylesheet template.
- **Outcome:** Classify intentional Qt sentinel/hairline values, route scalable
  geometry through shared scale/theme tokens, and add guards for new residue.
- **Acceptance:** The reviewed literal inventory has documented allowlist entries or
  tokenized replacements, and 100/150/200-percent visual checks remain unclipped.
- **Evidence:** The file `theme.qss.tmpl` in
  `plex_renamer/gui_qt/resources/` contains 228 matches for `[0-9]+px`;
  `_media_workspace_roster.py` and `_settings_tab_sections.py` still pass direct
  integer geometry to Qt sizing, margin, and spacing APIs.

## Architecture and quality debt

### ARCH-001 — Extract episode-resolution complexity seams

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** `plex_renamer/engine/_episode_resolution.py`, starting with
  `apply_confidence_adjustments` and the related rescue decision paths.
- **Outcome:** Add decision-table characterization, then extract cohesive pure-policy
  seams while preserving branch order and confidence behavior.
- **Acceptance:** Characterization covers every extracted branch, targeted/full tests
  remain green, and complexity/LOC ratchets improve without new decisions.
- **Evidence:** The current `scripts/audit/quality-baseline.json` records a 2,037-LOC
  ceiling for `_episode_resolution.py` and complexity 49 for
  `apply_confidence_adjustments`.

### ARCH-003 — Extract episode-row action dispatch seams

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** `MediaWorkspaceActionCoordinator.handle_episode_row_action` in
  `_media_workspace_actions.py`.
- **Outcome:** Characterize action-to-service/UI effects, then split dispatch handlers
  while retaining one refresh and status-message contract.
- **Acceptance:** Each action has a dispatch characterization test, GUI behavior is
  unchanged, and the coordinator method's complexity is materially reduced.
- **Evidence:** The current `scripts/audit/quality-baseline.json` records complexity
  51 for `handle_episode_row_action` and a 595-LOC ceiling for
  `_media_workspace_actions.py`.

### QUAL-001 — Burn down pyright clusters

- **Status:** Active deferred
- **Priority:** P1
- **Scope:** Clustered legacy pyright findings, especially Qt tests and typed fakes.
- **Outcome:** Run per-file campaigns that fix root types or add narrow documented
  decisions without weakening global checking.
- **Acceptance:** Each campaign reduces the committed pyright baseline, passes affected
  tests, and introduces no untracked suppressions or enlarged debt.
- **Evidence:** The current `scripts/audit/quality-baseline.json` contains 1,230
  pyright findings among 1,326 total findings.

### QUAL-002 — Reduce LOC ceilings and legacy-typing inventory

- **Status:** Active deferred
- **Priority:** P2
- **Scope:** Touched-file LOC ceilings and non-strict legacy Python files.
- **Outcome:** Shrink oversized files and migrate legacy files to the strict typing
  policy opportunistically, preserving the ratchets' no-enlargement behavior.
- **Acceptance:** Baseline refreshes only prune entries; no touched file grows past its
  ceiling and newly strict files pass pyright without blanket exclusions.
- **Evidence:** The current `scripts/audit/quality-baseline.json` contains 42 LOC
  ceilings and 354 legacy typing files.

### QUAL-003 — Resolve decision-covered vulture residue

- **Status:** Active deferred
- **Priority:** P3
- **Scope:** Remaining dead-code findings, including framework callbacks that may need
  explicit decisions rather than deletion.
- **Outcome:** Review residue when files are touched, remove proven dead code, and keep
  only narrow framework-required decisions.
- **Acceptance:** Each reviewed cluster reduces findings or records evidence-backed
  decisions; runtime callback discovery tests protect retained symbols.
- **Evidence:** The current `scripts/audit/quality-baseline.json` contains 95 vulture
  findings.

## Audit-harness hardening

### AUDIT-004 — Retire the decision-covered SIM103 residue

- **Status:** Active deferred
- **Priority:** P3
- **Scope:** `looks_like_tv_episode`'s needless-bool shape in
  `plex_renamer/_parsing_tv.py`.
- **Outcome:** Apply the simplification when coverage accounting can absorb the loss of
  covered statements, or adjust the ratchet through an independently justified change.
- **Acceptance:** Ruff SIM103 passes, package coverage remains at or above its ratchet,
  and the accepted-debt decision is removed.
- **Evidence:** `scripts/audit/decisions.toml` records this SIM103 finding with
  `reason_code = "accepted-debt"` and the coverage-floor conflict.

### AUDIT-005 — Retire the decision-covered SIM117 residue

- **Status:** Active deferred
- **Priority:** P3
- **Scope:** Nested context managers in the recorded
  `tests/test_qt_main_window.py` test.
- **Outcome:** Combine the contexts when the file ceiling has enough room or after an
  independently useful reduction.
- **Acceptance:** Ruff SIM117 passes, the file stays within its LOC ceiling, and the
  accepted-debt decision is removed.
- **Evidence:** `scripts/audit/decisions.toml` records this SIM117 finding with
  `reason_code = "accepted-debt"` and the two-line LOC-ceiling conflict.

## Retired or rejected proposals

- **Partial prefix-only part merges — rejected.** Do not infer a merge from only a
  shared prefix when the complete ordered part set is not established; keep ambiguous
  files in review or require an explicit manual group.
- **Transcoding in container-conversion flows — rejected.** Container conversion is a
  lossless mkvmerge/remux workflow. Codec conversion belongs in a separately designed
  transcoding feature with explicit quality and resource policy.
- **Independent commentary removal while strip toggles are disabled — rejected.** The
  commentary preference does not operate as a hidden destructive rule when its parent
  strip behavior is disabled; the previewed AutoMux policy remains authoritative.
- **Historical plan checkboxes as task status — rejected.** Current code, tests, audit
  evidence, and this backlog determine status; historical plans are recovery material.
