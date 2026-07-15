# Audit Harness README Guide Design

**Date:** 2026-07-14

## Goal

Give contributors a concise, accurate path for running the same audit and quality checks used by CI without turning the README into a complete CLI reference.

## Scope

Update the contributor documentation in `README.md` and correct the audit CLI's stale-baseline help text so both surfaces describe the implemented behavior consistently. Do not change audit behavior, quality thresholds, baseline contents, or generated artifact formats.

## README structure

Add `## Audit harness and quality ratchets` immediately after `## Testing` and before `## Architecture`. The section will contain:

1. A constrained development-tool installation command using `.[dev]` and `scripts/audit/constraints.txt`.
2. The CI-equivalent daily workflow:
   - `scripts\test-fast.cmd -Coverage`
   - `scripts\audit.cmd --quality-check`
   - `scripts\audit.cmd --verify`
3. A regeneration workflow using `scripts\audit.cmd --with-coverage`.
4. A safe baseline-maintenance workflow that first collects exact-digest coverage and then runs `--update-quality-baseline` after legacy debt has been removed.
5. A compact explanation of enforced ratchets, machine-readable decisions, and generated artifacts.
6. A Windows-specific warning that `test-fast.cmd` uses `-Coverage`, while `audit.cmd` uses argparse-style `--with-coverage`.

The existing Testing introduction will stop claiming that pytest is the only development dependency because the development extra also installs Ruff, Vulture, Coverage.py, Radon, and Pyright.

## Behavioral accuracy

The README will state that `--quality-check` requires current, full, unfiltered, digest-matched coverage evidence. New or enlarged debt fails the command; stale debt-baseline entries are reported as improvements and do not fail it. Stale or invalid manual decisions remain fail-closed during generation.

The `--quality-check` argparse help text will be corrected to match this behavior. This is documentation-only: the command's exit semantics will not change.

## User workflow

For normal development, contributors run coverage once, then reuse that evidence for both the quality gate and deterministic artifact verification. Contributors regenerate audit outputs only when inputs intentionally change, inspect the generated diff, and commit the outputs rather than hand-editing generated sections.

Quality-baseline refresh remains an explicit maintenance operation. It may prune resolved legacy debt, but it must not enroll new Python files or accept new or enlarged debt.

## Error guidance

The README will call out the most common failure mode: `--quality-check` does not collect coverage itself. Missing, partial, filtered, failed, or digest-mismatched coverage evidence requires rerunning `test-fast.cmd -Coverage`.

The guide will direct contributors to `scripts/audit/decisions.toml` for exact analyzer/rule/path/symbol decisions and to `docs/audit/` plus `audit.sarif` for generated review outputs.

## Verification

Verification will include:

- checking README commands against current wrapper and CLI interfaces;
- focused CLI and workflow contract tests for the corrected help text;
- `scripts\audit.cmd --quality-check` using fresh exact-digest coverage evidence;
- `scripts\audit.cmd --verify` to confirm committed generated outputs remain current;
- a clean worktree after the documentation commit.

## Non-goals

- A complete reference for every positional audit stage or legacy compatibility option.
- Changes to ratchet thresholds, analyzer versions, decision semantics, baseline schemas, or CI ordering.
- Replacing the detailed generated material under `docs/audit/`.
