# Tech-Debt Campaign Design

**Status:** Approved portfolio design
**Date:** 2026-07-21
**Backlog authority:** `docs/deferred-work.md`
**Lifecycle:** This document and its implementation plans are active execution aids,
not a second backlog. Remove them from the repository and place them in the external
plan archive when the campaign is completed, rejected, or superseded.

## Goal

Reduce the debt that makes future feature development and the later V5 GUI rewrite
riskier. The campaign prioritizes behavioral safety, recovery correctness, bounded
architecture seams, and targeted typing improvements. It does not use debt cleanup as
a pretext to add metadata, AutoMux, persistence, or GUI features.

The consolidated backlog proved that every active item had a current code, test, or
audit footprint. It did not prove that every proposal still had enough product value
to implement. This campaign therefore selects only work that protects subsequent
development or resolves a concrete correctness gap.

## Design principles

1. **Isolate behavior changes from refactors.** Provider error semantics, parser
   behavior, and confidence calibration receive their own plans and commits.
2. **Characterize before extracting.** Recovery and resolution seams get
   discriminating tests before code is moved or divided.
3. **Pay typing debt where context is already loaded.** Pyright work is organized by
   subsystem and coordinated with nearby debt work, not attempted as a repository-wide
   sweep.
4. **Let baselines shrink only.** Quality-baseline updates may prune resolved entries;
   campaign work must not accept new or enlarged debt.
5. **Avoid disposable GUI refactoring.** The current GUI is expected to receive a V5
   rewrite after feature work. Preserve its behavioral contracts now, but defer
   `ARCH-003` unless the coordinator directly blocks intervening feature development.
6. **Keep plans disposable.** Completed plans are archived outside the repository so
   agents see only current execution context.

## Campaign compartments

### 1. Quality-gate hardening

**Backlog:** `AUDIT-001`, `AUDIT-003`, and the closely related documentation contract
in `AUDIT-002`.

Add exact expected-debt authorization to `--accept-enlarged`, pin the existing
argparse guard message, and document the `build_baseline` caller precondition. This
compartment comes first because later campaigns will repeatedly exercise the quality
baseline. It must be impossible for a broad refresh to enroll more debt than the
operator reviewed.

This is one implementation plan because the three changes share the same CLI boundary
and test surface. `AUDIT-004` and `AUDIT-005` remain opportunistic cosmetic cleanup.

### 2. Provider-map correctness

**Backlog:** `MATCH-002`.

Introduce explicit, testable states for a valid empty season map, provider failure,
and malformed/unusable provider data. Propagate failures to scan/review results so an
unavailable map cannot silently auto-approve or queue a show.

This is an isolated implementation plan because it intentionally changes behavior and
touches provider-to-engine contracts. It must not be combined with provider feature
work or structural scanner refactors.

### 3. Job rollback recovery

**Backlog:** `ARCH-002`.

First characterize rollback order, boundary checks, missing files, partial failures,
and every supported job kind. Then extract operation-specific undo handlers while
retaining a small orchestration function and the existing `(success, errors)` contract.

Use two implementation plans if characterization exposes missing behavior:

1. recovery characterization and any independently justified correctness fixes;
2. behavior-preserving seam extraction and complexity reduction.

Combining them is allowed only when characterization passes without requiring a
behavior decision.

### 4. Current-GUI behavioral contract

**Backlog:** `GUI-001`.

Restore end-to-end reassign assertions through the live Qt workspace. The tests must
cover selection, service dispatch, reprojection, visible row state, and failure when
dispatch or refresh is disconnected.

This is a small standalone plan. Do not perform the `ARCH-003` coordinator extraction
now. Preserve `ARCH-003` in the backlog for V5 planning or for an earlier revisit only
if the current coordinator becomes a demonstrated blocker.

### 5. Targeted typing campaigns

**Backlog:** `QUAL-001` and the strict-enrollment portion of `QUAL-002`.

The baseline contains 1,230 pyright findings, concentrated heavily in a few Qt test
modules, plus 354 legacy-typing files. A single sweep would produce an unreviewable
diff and encourage low-quality annotations. Generate separate plans for:

1. engine orchestration production code, beginning with
   `plex_renamer/engine/_batch_orchestrators.py`;
2. GUI action/workspace tests, coordinated with the reassign behavioral contract;
3. queue and asynchronous submission tests;
4. remaining high-density test clusters, split again when a plan would touch more
   than one independently understandable fixture/fake architecture.

Each plan must identify its exact starting finding set, fix root fixture or fake types
before leaf assertions, enroll newly strict files when practical, and refresh the
baseline only to remove resolved entries. LOC reduction is welcome where natural but
is not a reason to mix unrelated modules.

### 6. Episode-resolution policy and architecture

**Backlog:** `MATCH-001`, then `ARCH-001`.

Use two plans with a hard boundary:

1. build an outcome-calibration fixture set for named confidence tiers and document
   the intended approve/review split;
2. after those fixtures are accepted, extract pure policy seams from
   `apply_confidence_adjustments` and related rescue paths without changing decisions.

Calibration is a behavior decision; extraction is debt reduction. Keeping them
separate makes regressions and review disagreements attributable. No confidence
threshold changes are justified solely by reducing complexity.

### 7. Parser correctness campaign

**Backlog:** `PARSE-001` through `PARSE-005`.

Begin with a short support-policy plan that validates each syntax against the kinds of
media the application intends to support. Retire cases that are obsolete or too
ambiguous. For approved cases, create small implementation plans grouped only where
the parser boundary and ambiguity guards are shared. Dotted versions and four-digit
seasons should remain separate from multi-episode chain parsing unless code inspection
proves that they share one safe seam.

Parser changes happen after the foundational compartments because they alter media
classification and assignment behavior. `MATCH-003` and `MATCH-004` remain feature or
discovery work unless the parser policy review produces concrete current-library
failures that justify promoting them.

## Deferred from this campaign

- `META-001` through `META-006`: provider and exported-metadata features.
- `MUX-001` through `MUX-006`: feature expansion or performance research.
- `GUI-002`: persistence feature.
- `GUI-003`: visual polish better evaluated with V5.
- `ARCH-003`: current-GUI internal refactor deferred to V5 unless it becomes a blocker.
- `QUAL-003`: opportunistic framework/dead-code decisions.
- `AUDIT-004` and `AUDIT-005`: cosmetic accepted-debt residue.
- `MATCH-003` and `MATCH-004`: feature-shaped matching expansion pending real-library
  evidence.

## Dependency order

1. Quality-gate hardening.
2. Provider-map correctness and GUI behavioral coverage; these may run independently.
3. Job rollback characterization and extraction.
4. Typing campaigns, starting with production engine code and then the test clusters
   adjacent to completed work.
5. Episode-resolution calibration, followed by episode-resolution extraction.
6. Parser support-policy review, followed by approved parser implementations.

Plans within a compartment may be executed independently only when they do not modify
the same fixtures, baseline entries, or production boundary. Every compartment closes
with focused tests and quality checks. Full coverage, smoke, audit generation, quality
ratchets, and audit verification run once at branch closeout.

## Campaign exit criteria

- Every selected backlog ID is completed, explicitly deferred with a reason, or
  rejected and recorded in `docs/deferred-work.md`.
- No implementation plan remains in the repository after its work is integrated.
- Quality-baseline refreshes contain only removals or smaller ceilings/findings.
- Recovery, provider failure, GUI reassign, and episode-resolution behavior have
  discriminating tests at their public boundaries.
- The full branch closeout cadence passes with usable full-suite coverage evidence.
- Feature-shaped entries remain parked for feature planning, and V5 receives behavior
  contracts rather than preemptive current-GUI restructuring.
