# Claude Notes

For Windows git publish workflows in this repository, use the instructions in [docs/ai-publish-workflow.md](docs/ai-publish-workflow.md).

- Prefer PowerShell for terminal commands.
- Use the shared terminal only for lightweight exploration.
- For git-critical or output-sensitive commands, use a fresh PowerShell session.
- Prefer [scripts/test-smoke.cmd](scripts/test-smoke.cmd) for Qt smoke runs instead of raw `pytest tests/test_gui_qt_smoke.py`; it writes the full output to `.pytest_cache/smoke/latest.log` and prints a concise summary plus exit code.
- Prefer [scripts/git-publish.cmd](scripts/git-publish.cmd) for commit/push flows, with [scripts/git-publish.ps1](scripts/git-publish.ps1) as the implementation.
- The script commits staged changes by default.
- If no commit message is provided, run the script once without `-Message`, use its staged summary to propose a commit message, and ask the user to approve or replace it before rerunning the script.
- After drafting the proposed message, rerun the script with `-ProposedMessage` so the same proposal is visible in the terminal before asking for chat approval.
- Present the proposed commit message in chat, not as a terminal prompt. The expected user replies are `approve` or `use this message: ...`.
- Recognize shorthand publish prompts documented in [docs/ai-publish-workflow.md](docs/ai-publish-workflow.md), for example `publish branch=dev/GUI3 automessage=y stage=task`.
- Use `-StageAll` only when the user explicitly wants all current changes staged.
