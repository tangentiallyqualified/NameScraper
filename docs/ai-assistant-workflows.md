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
- `automessage=y`: do not require you to write a commit message first; instead, inspect what will be pushed, generate a proposed commit message in chat, and ask you to approve or replace it before the publish script is run
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
3. Assess the staged or selected changes using repo tools or git diff output.
4. Propose a commit message in chat.
5. Wait for you to reply with `approve` or `use this message: ...`.
6. Run [../scripts/git-publish.cmd](../scripts/git-publish.cmd) one time with the approved message.
7. Report the resulting commit hash and push result.

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
- For `automessage=y`, the assistant should inspect the intended publish scope before calling the script, then run the script once after you approve a message in chat.
- If the script is ever run without `-Message`, it only prints a staged summary and stops. It is not waiting for terminal input.

---

## Terminal Hygiene

To reduce noisy output and wasted retries:

- use the shared terminal only for lightweight exploration
- use fresh/background terminal sessions for git-critical commands and output-sensitive commands
- in chat-driven tools that require manual command approval, run publish commands in a self-terminating PowerShell session
- for PowerShell assistant tooling, prefer commands that end with `exit $LASTEXITCODE` after `scripts/git-publish.cmd` finishes
- avoid relying on shared-terminal output after long or noisy test runs
- do not leave an idle PowerShell publish session open while waiting for a chat approval reply
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
