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
