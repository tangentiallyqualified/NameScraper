# Tech-Debt Campaign Execution Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the approved pre-feature/V5 debt campaign in dependency order while keeping behavior changes, refactors, typing work, and parser policies independently reviewable.

**Architecture:** Treat each linked plan as a disposable work package. Use one branch or PR per package unless the dependency table explicitly permits a paired PR. Update `docs/deferred-work.md` only as acceptance criteria land, prune quality baselines only after focused tests pass, and remove completed plan files from the repository after merge.

**Tech Stack:** Python 3.14, PySide6, pytest, Pyright, Ruff, repository audit scripts, GitHub Actions.

## Global Constraints

- `docs/deferred-work.md` remains the backlog authority; this index does not create new debt IDs.
- Start no refactor until its characterization prerequisite is green.
- Do not combine a behavior change with a behavior-preserving extraction.
- Baseline refreshes may only remove findings or lower ceilings.
- Do not implement `ARCH-003` before V5 unless a current feature is demonstrably blocked by it.
- Every merged package removes or externally archives its own implementation plan so stale instructions cannot influence agents.

## Work packages

| Order | Package | Backlog | Prerequisite | Safe parallel peer |
| --- | --- | --- | --- | --- |
| 1 | [Quality-gate hardening](2026-07-21-01-quality-gate-hardening.md) | `AUDIT-001`–`AUDIT-003` selected scope | None | None; merge first |
| 2 | [Provider-map correctness](2026-07-21-02-provider-map-correctness.md) | `MATCH-002` | Package 1 | Package 5 |
| 3 | [Rollback characterization](2026-07-21-03-rollback-characterization.md) | `ARCH-002` characterization | Package 1 | Package 5 |
| 4 | [Rollback seam extraction](2026-07-21-04-rollback-seam-extraction.md) | `ARCH-002` extraction | Package 3 | Package 6 |
| 5 | [GUI reassign contract](2026-07-21-05-gui-reassign-contract.md) | `GUI-001` | Package 1 | Packages 2–3 |
| 6 | [Engine orchestrator typing](2026-07-21-06-engine-orchestrator-typing.md) | `QUAL-001`, `QUAL-002` slice | Package 2 | Package 4 after provider merge |
| 7 | [GUI workspace test typing](2026-07-21-07-gui-workspace-test-typing.md) | `QUAL-001`, `QUAL-002` slice | Package 5 | Package 8 if separate branches avoid shared baseline edits |
| 8 | [Queue async test typing](2026-07-21-08-queue-async-test-typing.md) | `QUAL-001`, `QUAL-002` slice | Package 1 | Package 10 |
| 9 | [Main-window test typing](2026-07-21-09-main-window-test-typing.md) | `QUAL-001`, `QUAL-002` slice | Package 5 | Package 10 |
| 10 | [Job-detail test typing](2026-07-21-10-job-detail-test-typing.md) | `QUAL-001`, `QUAL-002` slice | Package 1 | Packages 8–9 |
| 11 | [Episode confidence corpus](2026-07-21-11-episode-confidence-corpus.md) | `MATCH-001` | Package 1 | Typing packages |
| 12 | [Episode resolution extraction](2026-07-21-12-episode-resolution-extraction.md) | `ARCH-001` | Package 11 | None in episode-resolution files |
| 13 | [Parenthesized batch ranges](2026-07-21-13-parenthesized-batch-ranges.md) | `PARSE-001` | Packages 1–12 closeout | Packages 14–17 only on isolated branches |
| 14 | [OVA number disambiguation](2026-07-21-14-ova-number-disambiguation.md) | `PARSE-002` | Packages 1–12 closeout | Packages 13, 15–17 only on isolated branches |
| 15 | [Dotted version guard](2026-07-21-15-dotted-version-guard.md) | `PARSE-003` | Packages 1–12 closeout | Packages 13–14, 16–17 only on isolated branches |
| 16 | [Four-digit TV seasons](2026-07-21-16-four-digit-tv-seasons.md) | `PARSE-004` | Packages 1–12 closeout | Packages 13–15, 17 only on isolated branches |
| 17 | [NxN multi-episode chains](2026-07-21-17-nxn-multi-episode-chains.md) | `PARSE-005` | Packages 1–12 closeout | Packages 13–16 only on isolated branches |

The parser support-policy decision is resolved by the approved campaign design: all five current corpus conventions remain supported. Each parser plan begins with its own positive/negative ambiguity contract, so no shared speculative parser refactor is authorized.

## Execution waves

### Wave 1: Make debt enrollment safe

- [ ] Execute package 1 and merge it before any baseline-changing package.
- [ ] Confirm exact expected-debt authorization, argparse guard coverage, and audit documentation are green.
- [ ] Remove/archive plan 01 after merge.

### Wave 2: Correctness and recovery contracts

- [ ] Execute packages 2, 3, and 5 as separate branches/PRs.
- [ ] Merge package 3 before starting package 4.
- [ ] Keep `ARCH-003` in `docs/deferred-work.md` for the future V5 pass.
- [ ] Remove/archive plans 02–05 as their work merges.

### Wave 3: Bounded architecture and typing burn-down

- [ ] Execute package 4 after rollback characterization.
- [ ] Execute package 6 after provider-map changes settle in `_batch_orchestrators.py`.
- [ ] Execute packages 7–10 one target file at a time; rebase before each baseline prune.
- [ ] Verify every campaign reaches zero target-file Pyright findings without blanket suppressions.
- [ ] Remove/archive plans 04 and 06–10 as their work merges.

### Wave 4: Episode decision policy before extraction

- [ ] Execute package 11 and review every approve/review disagreement as a product decision.
- [ ] Start package 12 only when the accepted outcome corpus is green.
- [ ] Confirm extraction changes no threshold or decision ordering.
- [ ] Remove/archive plans 11–12 after merge.

### Wave 5: Parser correctness

- [ ] Execute packages 13–17 independently, rebasing between merges because they share parser and corpus files.
- [ ] For each package, land negative ambiguity guards before removing the one matching strict `xfail`.
- [ ] Run the complete parsing suite after every merge.
- [ ] Remove/archive plans 13–17 after merge.

### Wave 6: Campaign closeout

**Files:**
- Modify prune-only: `scripts/audit/quality-baseline.json`
- Modify: `docs/deferred-work.md`
- Remove after external archive: `docs/current-plans/2026-07-21-*.md`

- [ ] **Step 1: Reconcile backlog IDs**

Confirm every selected ID is absent because it is completed or remains with an explicit defer/reject reason. Confirm feature-shaped META, MUX, GUI persistence/polish, and `ARCH-003` entries remain parked.

- [ ] **Step 2: Run branch-close verification**

Run: `scripts\test-smoke.cmd`
Expected: PASS.

Run: `scripts\test-fast.cmd -Coverage`
Expected: PASS; `.coverage.meta.json` records `full_suite=true` and `partial=false`.

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: exit 0; diff contains removals/lower counts only.

Run: `scripts\audit.cmd --quality-check`
Expected: `baseline current; no new or enlarged debt`.

Run: `scripts\audit.cmd --verify`
Expected: PASS.

- [ ] **Step 3: Inspect the final quality-baseline diff**

Run: `git diff -- scripts/audit/quality-baseline.json docs/deferred-work.md`
Expected: no new analyzer/rule/path identity and no enlarged count or ceiling.

- [ ] **Step 4: Archive and remove execution aids**

Copy the final approved design/index/plans to the external plan archive used by the project, then remove their tracked copies from `docs/current-plans`. Do not remove `docs/deferred-work.md`.

- [ ] **Step 5: Commit campaign closeout**

```powershell
git add docs/deferred-work.md scripts/audit/quality-baseline.json docs/current-plans
git commit -m "chore: close tech-debt campaign"
```
