# Deferred Work Consolidation and Plan Quarantine Design

**Date:** 2026-07-21  
**Status:** Approved for planning  
**Repository:** NameScraper

## Purpose

Give developers and repository-aware agents one authoritative view of unfinished
work while preventing completed, superseded, or abandoned implementation plans
from being mistaken for current requirements.

The cleanup preserves historical material in a recovery-only archive outside the
repository. The archive is not linked from repository documentation and is not an
input to future development work.

## Current problem

The repository contains three competing sources of deferred-work context:

1. `docs/audit/deferred-issues.md`, which has not been updated for the most recent
   implementations.
2. Approximately ninety ignored, untracked plans and specifications under
   `docs/superpowers/`, plus nine tracked plans/specifications in the same tree.
3. Agent-facing references in `CLAUDE.md` that direct readers to historical
   investigation plans.

Because ignored files remain visible to filesystem-aware agents, the ignore rules
do not prevent stale plans from influencing current work. Several source and test
comments also explicitly mark real follow-ups that are absent from the current
consolidated backlog.

## Chosen approach

Use a full-quarantine model:

- `docs/deferred-work.md` becomes the only authoritative backlog document.
- All historical files below `docs/superpowers/plans/` and
  `docs/superpowers/specs/` are copied to a dated external archive, then removed
  from the working tree.
- Agent-facing and general documentation points only to the canonical backlog,
  never to the external archive or an individual historical plan.
- Git history remains the recovery mechanism for formerly tracked plans. The
  external archive preserves ignored, untracked files that Git cannot recover.

The external archive location is:

`C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper Plan Archive\2026-07-21`

## Canonical backlog structure

`docs/deferred-work.md` contains:

- a statement that it is the sole current deferred-work source;
- maintenance rules for adding, completing, or rejecting entries;
- a `Last reviewed` date and repository commit used for the review;
- grouped backlog entries with stable identifiers;
- for each entry: status, priority, scope, actionable description, acceptance
  signal, and origin/evidence that can be recovered from Git or source;
- an explicitly rejected or retired section only when recording the decision is
  necessary to prevent a known stale proposal from returning.

Entries describe remaining outcomes, not old execution scripts. Historical task
numbers, obsolete line numbers, and implementation instructions are omitted unless
they remain essential to understanding the current work.

## Source classification rules

Every candidate from historical plans, specifications, the existing deferred
issues document, and explicit source/test markers is classified as one of:

- **Active deferred:** The behavior is still absent or the debt still exists.
  Include it in the canonical backlog.
- **Completed:** Current code, tests, audit data, or commits show that it landed.
  Do not include it as open work.
- **Superseded:** A later implementation or design replaced the proposal. Do not
  include the obsolete form; include only any still-valid outcome.
- **Rejected/out of scope:** The repository deliberately does not promise the
  behavior. Record it only when omission would make agents repeatedly rediscover
  and propose it.
- **Unverifiable:** Evidence is insufficient to call it active or complete. Keep a
  concise investigation entry in the backlog instead of guessing.

The current source tree and tests outrank plan checkboxes. Recent implementation
commits and audit artifacts outrank older prose. A plan marked incomplete is not
automatically deferred if its intended behavior is already present.

## Repository cleanup

The implementation will:

1. Inventory every plan/spec file before moving anything and record file counts.
2. Build the canonical backlog from unresolved outcomes.
3. Update `CLAUDE.md`, `docs/README.md`, and other live references so they point to
   `docs/deferred-work.md` and contain no historical-plan routing.
4. Retire `docs/audit/deferred-issues.md` by replacing it with a short canonical
   pointer if compatibility or audit discoverability requires the path; otherwise
   remove it and update its references.
5. Allowlist `docs/deferred-work.md` in `.gitignore` so it is intentionally tracked.
6. Copy the complete `docs/superpowers` plan/spec tree to the dated external
   archive and verify file counts and content hashes before repository removal.
7. Remove the archived plans/specs from the working tree. Tracked removals remain
   recoverable through Git; ignored removals remain recoverable from the archive.

The archive is never referenced from `CLAUDE.md`, `README.md`, or the canonical
backlog. Its purpose is disaster recovery, not active context.

## Safety and failure handling

- No source file is removed until the canonical backlog has been written.
- No repository plan/spec is removed until the corresponding archive copy exists.
- Archive verification compares relative paths, file counts, file lengths, and
  SHA-256 hashes.
- A mismatch stops cleanup before deletion.
- Existing unrelated working-tree changes are preserved.
- If a candidate's status cannot be proven, it becomes an investigation entry.
- The external archive operation requires explicit filesystem approval because
  its destination is outside the workspace write root.

## Verification

Completion requires all of the following:

- The canonical backlog exists and is tracked.
- Every genuine unresolved candidate has either a backlog entry or an explicit
  retirement decision.
- Repository searches find no live references to `docs/superpowers/plans`,
  `docs/superpowers/specs`, or the external archive.
- `docs/superpowers/plans` and `docs/superpowers/specs` contain no historical files
  in the working tree after this design spec has served its planning purpose.
- The archive manifest and repository pre-removal inventory match.
- Agent instructions identify `docs/deferred-work.md` as the sole backlog.
- Documentation-link/audit verification passes, or generated audit artifacts are
  refreshed as required by repository policy.
- `git status` contains only intended cleanup changes and pre-existing user work.

## Non-goals

- Implementing any deferred feature or debt item.
- Preserving historical plans inside another repository directory.
- Rewriting Git history to erase tracked plans.
- Treating generated audit findings or ordinary uses of the word "deferred" as
  backlog entries without evidence of unfinished work.
- Maintaining links from active docs to recovery-only historical context.
