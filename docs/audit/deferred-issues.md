# Deferred Issues

Consolidated backlog of known-but-deferred work. Each entry names its origin so the
context can be recovered. Remove entries when the work lands; add new entries when a
campaign defers something instead of fixing it.

Last updated: 2026-07-18 (ruff burndown closeout, `dev/ruff-burndown` at `92823e8`).

## Code debt

### Dead code: `_rename_execution.execute_rename` (and `check_duplicates`)

- `plex_renamer/engine/_rename_execution.py` — `execute_rename` has zero callers
  anywhere in `plex_renamer/` or `tests/` (verified twice: ruff-burndown Tasks 4 and 7).
  It is still imported and re-exported via `plex_renamer/engine/_core.py` `__all__`.
  `check_duplicates` in the same file is also suspected dead.
- Why it matters: its uncovered lines caused both `--accept-enlarged` coverage
  acceptances during the ruff burndown; removing it restores changed-lines coverage
  honesty for that region.
- Origin: ruff-burndown Task 4; already chip-flagged as a spin-off task (`task_304aef8e`).

### Accepted-debt SIM residue (decision-covered, revisit when ratchets allow)

Both live in `scripts/audit/decisions.toml` with `reason_code = "accepted-debt"`:

- SIM103 in `plex_renamer/_parsing_tv.py` (`looks_like_tv_episode` if/return shape):
  the ruff rewrite would shrink the covered-statement pool and trip the package
  coverage floor for reasons unrelated to correctness.
- SIM117 in `tests/test_qt_main_window.py` (nested `with` blocks): the parenthesized
  multi-context form costs 2 lines against that file's frozen LOC ceiling.
- Origin: ruff-burndown Task 8. Revisit if the coverage floor or LOC ceiling for these
  files moves.

## Audit-harness hardening

### `--accept-enlarged` expected-entries guard

- `scripts/audit.cmd --update-quality-baseline --accept-enlarged` currently blanket-accepts
  every enlarged entry in the run, with stdout as the only record. An optional
  expected-entries (or expected-count) argument would make a refresh fail if it would
  accept more than the operator anticipated, preventing unrelated debt from riding a
  refresh into the baseline.
- Origin: ruff-burndown final whole-branch review recommendation.

### `build_baseline` / `gate_refresh_debt` coupling undocumented

- `scripts/audit/_ratchets.py` (~line 110): `build_baseline(accept_enlarged=True)`
  skips the coverage gate and is only safe because `run_quality_baseline_update` runs
  `gate_refresh_debt` first. Add a one-line docstring note ("callers must gate
  violations before passing accept_enlarged=True") next time the file is touched.
- Origin: ruff-burndown Task 1 review, confirmed by final review (leave-for-merge,
  fix opportunistically).

### Weak accept-enlarged guard test

- `tests/audit/test_quality_baseline_accept.py` (~lines 115-120): the guard test
  asserts bare `SystemExit(2)`, which argparse also raises for an unrecognized
  argument, so it cannot distinguish "flag requires --update-quality-baseline" from
  "flag does not exist". Assert the specific stderr message to pin the guard.
- Origin: ruff-burndown Task 1 review, confirmed by final review.

## Remaining ratcheted-debt campaigns (from the burndown plan's deferred section)

- **Pyright cluster campaign** — 1,028 baseline findings remain (down from 1,220; the
  ruff import cleanup retired 192 for free). Top clusters are Qt test files
  (`tests/test_qt_media_workspace.py`, `tests/test_qt_main_window.py`,
  `tests/test_qt_job_detail_panel.py`, `tests/test_episode_table_delegate.py`).
  Needs its own plan with a per-file strategy (typed fakes vs decisions).
- **LOC ceilings and legacy typing** — 37 LOC ceilings and 354 legacy non-strict
  typing files, held by the touched-file ratchet; burn down opportunistically.
- **Vulture residue** — 85 findings, mostly framework callbacks; decision-covered as
  files get touched.
- Pending deferred-debt plans already written (local-only, gitignored):
  [2026-07-17-coverage-floors.md](../superpowers/plans/2026-07-17-coverage-floors.md),
  [2026-07-17-extract-episode-seam.md](../superpowers/plans/2026-07-17-extract-episode-seam.md).

## Notes for the eventual `dev/ruff-burndown` merge/PR description

Recorded here so the acceptance record outlives terminal sessions:

- Four `--accept-enlarged` refresh points enrolled LOC-ceiling enlargements — wave A
  `7db3b08` (13 prod files), wave B `d25eeb1` (15 test files),
  `b7763ef` (1 file), SIM wave `3c6c25f` (`_tv_scanner_consolidated.py` 685→720) —
  30 entries total, all verified pure ruff-format reflow (AST-equivalent) by the final
  review. A refreshed ceiling equals current LOC, so no slack was introduced.
- `pyproject.toml` gained `[tool.ruff.lint.isort] combine-as-imports = true` — an
  unplanned but benign lint-style enabler for the I001 wave; no runtime surface.
- Final commit `92823e8` is an intentional `--allow-empty` marker carrying the
  closeout evidence (before: ruff 492 of 1,797 at `148f4d5`; after: 0 undecided).
  If squash-merging, fold its body into the squash message.
