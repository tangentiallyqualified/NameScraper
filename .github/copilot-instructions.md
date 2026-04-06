# Repository Instructions

- This repository is developed primarily on Windows using PowerShell.
- Prefer PowerShell-native commands and path handling when running terminal commands.
- Use the shared terminal for lightweight exploration only.
- For commands where exact stdout matters, or after a noisy command has run, prefer a fresh/background terminal session instead of the shared shell.
- For git-critical operations such as `status`, `commit`, and `push`, prefer a fresh PowerShell session so stale terminal output does not contaminate the result.
- Prefer `scripts/test-smoke.cmd` for Qt smoke runs instead of raw `pytest tests/test_gui_qt_smoke.py`; the wrapper captures the full output to `.pytest_cache/smoke/latest.log` and prints a concise summary plus exit code.
- Before committing, verify the changed file set with tooling such as `get_changed_files` when available.
- Prefer `scripts/git-publish.cmd` for Windows commit/push flows, with `scripts/git-publish.ps1` as the underlying implementation.
- If the user does not supply a commit message, run `scripts/git-publish.cmd` without `-Message`, use its staged summary to draft a commit message, and ask the user to approve it or provide a replacement before the final publish run.
- After drafting the proposed message, rerun `scripts/git-publish.cmd` with `-ProposedMessage` so the same proposal is visible in the terminal before asking for chat approval.
- After capturing output from a publish prep or `-ProposedMessage` run, close that temporary terminal session before waiting for the user's chat reply.
- Present the proposed commit message in chat, not in terminal instructions. The expected user replies are `approve` or `use this message: ...`.
- Recognize shorthand publish prompts documented in `docs/ai-publish-workflow.md`, for example `publish branch=dev/GUI3 automessage=y stage=task`.
- When pushing, prefer a fresh/background terminal session and wait for the explicit completion result before reporting success.
- Keep commits focused; do not stage unrelated files by default.
