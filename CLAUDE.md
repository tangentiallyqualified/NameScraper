# Claude Notes

For Windows git publish workflows in this repository, use the instructions in [docs/ai-publish-workflow.md](docs/ai-publish-workflow.md).

- Prefer PowerShell for terminal commands.
- Use the shared terminal only for lightweight exploration.
- For git-critical or output-sensitive commands, use a fresh PowerShell session.
- Prefer [scripts/test-smoke.cmd](scripts/test-smoke.cmd) for Qt smoke runs instead of raw `pytest tests/test_gui_qt_smoke.py`; it writes the full output to `.pytest_cache/smoke/latest.log` and prints a concise summary plus exit code.
- Prefer [scripts/git-publish.cmd](scripts/git-publish.cmd) for commit/push flows, with [scripts/git-publish.ps1](scripts/git-publish.ps1) as the implementation.
- In chat-driven terminal approval UIs, run publish commands in a self-terminating PowerShell session, for example by ending the command with `exit $LASTEXITCODE`.
- The script commits staged changes by default.
- If no commit message is provided, inspect the intended publish scope directly, propose a commit message in chat, and ask the user to approve or replace it before running the script once with the final message.
- In the publish happy path, keep chat output minimal: proposed commit message only, then approval prompt only.
- Do not include a scope summary, diff summary, or reasoning unless the user asked for it or the staged file set is ambiguous.
- Do not use `scripts/git-publish.cmd` as a preview step for `automessage=y`; reserve it for the final commit/push run after chat approval.
- Do not leave an idle publish terminal open while waiting for the user's chat reply.
- Present the proposed commit message in chat, not as a terminal prompt. The expected user replies are `approve` or `use this message: ...`.
- Recognize shorthand publish prompts documented in [docs/ai-publish-workflow.md](docs/ai-publish-workflow.md), for example `publish branch=dev/GUI3 automessage=y stage=task`.
- After starting a background publish command, prefer `await_terminal` to capture full stdout before reporting the result, and use `get_terminal_output` as a fallback because the initial terminal-wrapper response may not include complete stdout.
- Use `-StageAll` only when the user explicitly wants all current changes staged.

## Environment and tests

- This repo uses a venv at `.venv`; run Python and pytest through `.venv\Scripts\python.exe` (e.g. `.venv\Scripts\python.exe -m pytest tests\test_episode_resolution.py -q`).
- Fast unit-test sweep: [scripts/test-fast.cmd](scripts/test-fast.cmd) (accepts extra pytest args); Qt smoke: [scripts/test-smoke.cmd](scripts/test-smoke.cmd).
- Reusable tests use `tmp_path` and synthetic fixtures — never hardcode `P:\` media paths in anything that runs as part of the test suite. The real-library path belongs only in `scripts/scan_real_library.py`, which is run on request.

## TV batch engine iteration (real-library debugging)

- Real-library validation harness: `.venv\Scripts\python.exe scripts\scan_real_library.py [--targets frieren catdog] [--discover-only]`. It runs the real `BatchTVOrchestrator` discover + scan_all against `P:\data\downloads\in progress files` and dumps per-show evidence (preview items, assignment table with evidence tags, conflicts, unclaimed slots, TMDB slots) plus `discovery.txt` (show confidences + thresholds) to `.scan-dumps\` (gitignored). Requires the `P:` drive and a TMDB key via `plex_renamer.keys.get_api_key("TMDB")`; a full run takes several minutes of live TMDB calls. The `P:` drive is NOT always mounted — the script exits cleanly (code 2) when the root is missing; if so, report that validation is blocked rather than substituting another directory.
- Read the dumps, don't re-derive: `discovery.txt` answers "why does this show need review" (thresholds line + confidence); per-show files answer "why did this file map there" (evidence tags per assignment).
- Key engine layout: resolution rules + ALL episode-confidence constants in `plex_renamer/engine/_episode_resolution.py`; per-season scan path `engine/_tv_scanner_normal.py`; flat/mixed-folder path `engine/_tv_scanner_consolidated.py`; preview status strings minted only in `engine/_episode_projection.py`; show scoring in `engine/matching.py`; filename parsing in `plex_renamer/_parsing_*.py`.
- Thresholds: episode auto-accept 0.85 and show auto-accept 0.82 come from the user's settings.json (engine default 0.55) — check the harness thresholds line before interpreting `needs_review`.
- Root-cause history: [docs/superpowers/plans/2026-07-01-batch-tv-bug-investigation.md](docs/superpowers/plans/2026-07-01-batch-tv-bug-investigation.md) (RC1–15, fixed) and [docs/superpowers/plans/2026-07-02-batch-tv-bug-investigation-round2.md](docs/superpowers/plans/2026-07-02-batch-tv-bug-investigation-round2.md) (RC16–29); fix plan: [docs/superpowers/plans/2026-07-02-batch-tv-round2-fixes.md](docs/superpowers/plans/2026-07-02-batch-tv-round2-fixes.md).
