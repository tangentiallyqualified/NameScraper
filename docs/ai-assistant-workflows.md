# AI Assistant Workflows

This guide is the user-facing reference for asking an AI assistant to run repo helper scripts.

Use it when you want a short prompt that still expands into a safe, repeatable workflow.

For the technical implementation details behind the publish flow, see [ai-publish-workflow.md](ai-publish-workflow.md).

---

## What This Is For

This repo now supports a small shorthand style for AI-assisted workflows.

The goals are:

- keep prompts short
- keep commit/push flows predictable
- avoid staging unrelated work by accident
- make the same prompt style understandable to different assistants such as Copilot and Claude
- provide one place to document future helper scripts and prompt conventions

---

## Current Supported Workflows

### Publish / Commit / Push

Recommended shorthand:

```text
publish branch=dev/GUI3 automessage=y stage=task
```

What it means:

- `publish`: use the repo publish workflow via [../scripts/git-publish.cmd](../scripts/git-publish.cmd)
- `branch=dev/GUI3`: push `HEAD` to `dev/GUI3`
- `automessage=y`: do not require you to write a commit message first; instead, summarize the staged changes, generate a proposed commit message, and ask you to approve or replace it
- `stage=task`: stage only the files related to the current task

Other stage modes:

- `stage=all`: include all current changes
- `stage=staged`: use only the files already staged

Other message modes:

- `automessage=n`: do not generate a commit message automatically
- `message="..."`: provide an explicit commit message

Examples:

```text
publish branch=dev/GUI3 automessage=y stage=task
publish branch=dev/GUI3 automessage=y stage=all
publish branch=main automessage=y stage=staged
publish branch=dev/GUI3 automessage=n stage=all message="Polish queue UI"
```

---

## What The Assistant Should Do

For `publish ... automessage=y`, the expected flow is:

1. Check the changed file set.
2. Stage files according to the requested stage mode.
3. Run [../scripts/git-publish.cmd](../scripts/git-publish.cmd) without `-Message`.
4. Read the staged summary printed by the script.
5. Propose a commit message.
6. Rerun [../scripts/git-publish.cmd](../scripts/git-publish.cmd) with `-ProposedMessage "..."` so the same proposed message is visible in the terminal.
7. Present that same proposed message in chat and ask you to approve it or provide a replacement.
8. Rerun the publish flow with the approved message.
9. Report the resulting commit hash and push result.

This approval step is intentional. It keeps the commit message AI-assisted without making it fully automatic.

---

### Smoke Test

Recommended shorthand:

```text
smoke
```

What it means:

- run [../scripts/test-smoke.cmd](../scripts/test-smoke.cmd)
- execute the full Qt smoke suite in [../tests/test_gui_qt_smoke.py](../tests/test_gui_qt_smoke.py)
- capture the full pytest output to `.pytest_cache/smoke/latest.log`
- print a short pass/fail summary instead of relying on integrated-terminal scrollback

This should be preferred over calling raw `pytest tests/test_gui_qt_smoke.py` from chat when the goal is simply to verify the smoke suite result.

Important: approval is a chat reply, not a terminal reply. Do not type `y` or `approve` into PowerShell unless a script explicitly prompts for terminal input.

---

## User-Friendly Prompt Examples

### Shortest useful prompt

```text
publish branch=dev/GUI3 automessage=y stage=task
```

### If you already staged the files yourself

```text
publish branch=dev/GUI3 automessage=y stage=staged
```

### If you want everything included

```text
publish branch=dev/GUI3 automessage=y stage=all
```

### If you want to supply the commit message yourself

```text
publish branch=dev/GUI3 automessage=n stage=task message="Your message"
```

### When the assistant shows a proposed commit message

Reply in chat with one of these:

```text
approve
```

```text
use this message: Your replacement commit message
```

---

## Windows Notes

- The Windows-friendly entry point is [../scripts/git-publish.cmd](../scripts/git-publish.cmd).
- That wrapper calls the PowerShell implementation with an execution-policy bypass for the current process, so you should not need to change your machine-wide PowerShell policy.
- The PowerShell implementation lives in [../scripts/git-publish.ps1](../scripts/git-publish.ps1).
- When the script runs without `-Message`, it stops after printing the staged summary. The assistant should then continue in chat. It is not waiting for terminal input.
- When the script runs without `-Message` but with `-ProposedMessage`, it prints the proposed commit message in the terminal and still waits for approval in chat.

---

## Terminal Hygiene

To reduce noisy output and wasted retries:

- use the shared terminal only for lightweight exploration
- use fresh/background terminal sessions for git-critical commands and output-sensitive commands
- avoid relying on shared-terminal output after long or noisy test runs
- prefer direct repo tools for changed files and errors when those tools are available

---

## Adding Future Script Workflows

If more helper scripts are added later, extend this file using the same structure:

### Workflow Name

- Shorthand prompt
- Meaning of each token
- Required approval points
- Example prompts
- Underlying script entry point
- Any Windows-specific notes

Suggested future sections:

- release workflow
- changelog workflow
- packaging workflow

---

## Related Docs

- [ai-publish-workflow.md](ai-publish-workflow.md)
- [README.md](README.md)
