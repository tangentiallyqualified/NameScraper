# Audit findings review

This is the curated manual triage of the static-analysis findings generated at commit `486aaef`. The review was performed at `e5f4f40`; no production source under `plex_renamer/` changed between those commits, so the generated locations and reviewed implementations match.

## Outcome

The audit emitted 345 records. Of those, 142 are Radon cyclomatic-complexity measurements. They are factual measurements rather than unused-code or architecture claims, so they are recorded as `MEASURED` and were not forced into a false-positive verdict.

The remaining 203 actionable claims were each traced through source, tests, framework contracts, dynamic access patterns, exports, serialization, and relevant history.

| Verdict | Count | Meaning |
|---|---:|---|
| `FALSE_POSITIVE` | 95 | The reported binding or dependency is used, required by a framework/protocol, or intentionally retained as a supported/test-facing API. |
| `CONFIRMED` | 108 | The binding is genuinely unused, or the reported architecture violation is real. |
| `UNCERTAIN` | 0 | The repository evidence was insufficient to decide safely. |
| `MEASURED` | 142 | Radon reported a computed complexity threshold; this is not a dead-code false-positive question. |
| **Total** | **345** | All raw audit records are accounted for. |

Slightly fewer than half of the actionable findings are false positives: 95 of 203 (46.8%). The generated headline remains accurate that there are no high-confidence dead symbols, but manual triage still confirms 108 cleanup or architecture findings across Vulture, Ruff, and the layer-contract checker.

## Verdicts by analyzer

| Analyzer | False positive | Confirmed | Measured | Total |
|---|---:|---:|---:|---:|
| Vulture | 93 | 94 | - | 187 |
| Ruff | 2 | 12 | - | 14 |
| Layer contracts | 0 | 2 | - | 2 |
| Radon | - | - | 142 | 142 |
| **Total** | **95** | **108** | **142** | **345** |

The two Ruff false positives are intentional TMDB exception re-exports. Both layer-contract findings are confirmed: `engine` currently imports `app.services` through `_batch_orchestrators.py` and `_movie_scanner.py`, contrary to the declared bottom-layer direction.

## Detailed reviews

Each actionable raw record has exactly one evidence row in one of these non-overlapping reviews:

| Partition | False positive | Confirmed | Detail |
|---|---:|---:|---|
| Non-GUI | 37 | 36 | [Non-GUI findings](findings-review-non-gui.md) |
| GUI core and early widgets | 27 | 30 | [GUI core and early-widget findings](findings-review-gui-core-early-widgets.md) |
| Late widgets | 31 | 42 | [Late-widget findings](findings-review-late-widgets.md) |
| **Total** | **95** | **108** | **203 actionable records** |

The source checklist remains in the generated [audit overview](maps/overview.md). Regenerating the audit may change that checklist; these curated verdicts are intentionally stored outside its generated marker.

## Cross-cutting conclusions

- Qt virtual dispatch, required callback parameters, model/delegate hooks, event handlers, and layout ownership account for many false positives. These need narrow, framework-aware allowlisting rather than deletion.
- Dataclass fields, SQLite protocols, serialization fields, compatibility re-exports, public service methods, and deliberate test/introspection seams also evade ordinary static name-reference analysis.
- Coordinator and service extractions left real debris: private forwarding wrappers, stale imports, write-only aliases, redundant constructor assignments, and obsolete helper surfaces.
- Repeated findings for one symbol are not always duplicates. Separate assignments can have different verdicts when one write is overwritten and another is observed.
- Some confirmed widget findings concern only an unnecessary `self._name =` binding. The widget creation, signal connection, and layout insertion must remain.
- The 108 confirmed records do not imply 108 independent edits. Ruff/Vulture duplicates, repeated field writes, and class-plus-method findings should be remediated as grouped changes with tests.

## Recommended follow-up

1. Add narrowly scoped allowlist entries or explicit export declarations for the 95 false positives, favoring qualified Qt/framework patterns over broad symbol suppression.
2. Turn the 108 confirmed records into grouped cleanup tasks, preserving the cautions and exact evidence in the detailed tables.
3. Treat the two confirmed layer violations as architectural work: move discovery orchestration above `engine` or inject the required service without reversing the declared dependency direction.
4. Rerun the audit after remediation and compare the generated checklist against these verdicts; do not edit the generated checklist by hand.

## Review limits

This review establishes usage within this repository and the intent evidenced by exports, documentation, tests, and history. It cannot discover untracked third-party consumers. Public compatibility surfaces were therefore retained when the repository provides affirmative evidence of that intent.

## 2026-07-17 postscript

All 108 `CONFIRMED` records above, including both confirmed layer-contract violations, were remediated on `dev/audit-debt3` (PRs #20-#23). The generated checklist ([maps/overview.md](maps/overview.md)) has been regenerated since; these verdicts remain the unmodified historical record of the original triage and are not rewritten.
