# GUI V4 Implementation Roadmap

> **For agentic workers:** this is the index, not an executable plan. Execute the per-milestone plan files listed below (REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans). Write each missing plan file with superpowers:writing-plans **when its predecessor lands**, so plans are authored against real code, not stale predictions.

**Spec:** [2026-07-03-gui-v4-design.md](../specs/2026-07-03-gui-v4-design.md) — approved design is the source of truth.
**Branch:** `dev/GUI4`. **Gate:** cleared 2026-07-03 — user approved spec + Plan 1 and confirmed the app name "NameScraper".

## Plan sequence

| # | Plan file | Spec sections | Status |
|---|---|---|---|
| 1 | [2026-07-03-gui-v4-plan1-theme-foundation.md](2026-07-03-gui-v4-plan1-theme-foundation.md) | §8 theme tokens/palette/de-Plex, §14 shortcuts + recent-menus + About | **Landed** 2026-07-03 (commits 6c82086..d421d37, review clean) |
| 2 | [2026-07-03-gui-v4-plan2-roster.md](2026-07-03-gui-v4-plan2-roster.md) | §3.1 roster panel, §4 roster chips, §7 roster model/delegate | **Landed** 2026-07-03 (commits 9e366bb..e3bb6de + carry-overs, review clean) |
| 3 | [2026-07-03-gui-v4-plan3-work-panel.md](2026-07-03-gui-v4-plan3-work-panel.md) | §3.2 work panel, §3.3 movie parity, §4 season strip, §5 info removal, §7 episode table model/delegate/expansion | **Landed** 2026-07-03 (commits d8552ce..e3e7f57, review clean) |
| 4 | [2026-07-03-gui-v4-plan4-bulk-assign.md](2026-07-03-gui-v4-plan4-bulk-assign.md) | §6 bulk assign + unassign-all treatment, §15.7 MVP scope | **Landed** 2026-07-04 (commits 5ae5c96..eb8ee91, review clean) |
| 5 | [2026-07-04-gui-v4-plan5-async-perf.md](2026-07-04-gui-v4-plan5-async-perf.md) | §7 async guide build, BusyOverlay, warm-cache deletion, perf guard test | **Landed** 2026-07-04 (commits 53ba242..3765d5a, review clean) |
| 6 | [2026-07-04-gui-v4-plan6-toasts-loading.md](2026-07-04-gui-v4-plan6-toasts-loading.md) | §9 toasts, §10 loading screen | **Landed** 2026-07-04 (commits eb5ea11..6793ccf, review clean) |
| 7 | `gui-v4-plan7-queue-history.md` (to write) | §11 queue/history restyle + companion surfacing | not written |
| 8 | `gui-v4-plan8-settings-seams.md` (to write) | §12 settings restyle, §13 mkvmerge UI seams | not written |
| 9 | `gui-v4-plan9-final-pass.md` (to write) | §18 DPI pass (100/150/200%), real-library validation, string/perf sweep re-run | not written |

Milestone mapping vs spec §19: plans 2 and 3 absorb milestone 4 (chips/strip/footer render inside the roster and work-panel builds); plan 8 merges milestones 9's settings work with §13 seams; menu/shortcut fixes from milestone 9 were pulled forward into Plan 1 because they are independent, small, and de-risk daily use immediately (dangerous Ctrl+Z).

## Standing rules for every plan

- No engine/controller behavior changes; view-layer + read-model helpers only (spec §16).
- All colors/radii through `gui_qt/theme.py` — guard tests from Plan 1 enforce this repo-wide; never reintroduce hex literals in `gui_qt` code.
- All sizing through `gui_qt/_scale.py` (`px`, `row_height`, `margins`) — HiDPI is a release gate.
- Tests: fast sweep `scripts\test-fast.cmd`, Qt smoke `scripts\test-smoke.cmd` (writes `.pytest_cache/smoke/latest.log`). Both must pass at the end of every task; each plan includes its test migration.
- Update [the handoff file](2026-07-03-gui-v4-handoff.md) + this table's Status column when a plan is written, started, or landed.
