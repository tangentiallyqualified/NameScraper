# AI Publish Workflow

Use [scripts/git-publish.ps1](scripts/git-publish.ps1) for the underlying Windows PowerShell commit/push flow, and prefer [scripts/git-publish.cmd](scripts/git-publish.cmd) as the Windows-friendly entry point when an AI assistant is driving commands.

For a user-facing overview of shorthand prompts and future helper-script conventions, see [ai-assistant-workflows.md](ai-assistant-workflows.md).

## Purpose

This script makes commit/push steps more reliable on Windows by running the git-critical flow in one clean PowerShell execution instead of reusing a noisy shared terminal session.

## Windows Entry Point

- Prefer [scripts/git-publish.cmd](scripts/git-publish.cmd) from chat-driven workflows on Windows.
- The `.cmd` wrapper launches PowerShell with a process-scoped execution-policy bypass, so the repo does not depend on machine-wide policy changes.
- The `.ps1` file remains the implementation source of truth.

## Default Behavior

- The script commits only staged changes by default.
- It pushes `HEAD` to the target branch.
- It does not stage unrelated files unless `-StageAll` is passed.
- If `-Message` is omitted, the script prints a staged-change summary and stops without committing or pushing.
- Approval happens in chat. The recommended AI workflow is to inspect the intended publish scope first and run the script only after the user has approved a commit message.

## Recommended AI Workflow

1. Verify the changed file set.
2. Stage only the files intended for the commit, unless the user explicitly wants everything staged.
3. Inspect the staged or selected diff directly using repo tools or git diff output.
4. Have the AI assistant propose a commit message in chat from that diff.
5. Wait for the user to reply with `approve` or `use this message: ...`.
6. Run the publish script once with the approved commit message and target branch.
7. Report the resulting commit hash and push result.

## Happy-Path Token Budget

When the publish request is straightforward and the staged file set is already clear:

- propose only the commit message and the approval prompt in chat
- do not include a scope summary, diff summary, or reasoning unless the user asked for it
- after publish, report only the commit hash and push result unless the user asked for more detail
- expand only when there is ambiguity, risk of staging unrelated files, or a publish failure

## Commands

Stage selected files first, then publish:

```powershell
git add -- path/to/file1 path/to/file2
.\scripts\git-publish.cmd -Message "Your commit message" -Branch dev/GUI3
```

Stage selected files, ask the AI to propose a message, then publish:

```powershell
git add -- path/to/file1 path/to/file2
git diff --cached --stat
git diff --cached --name-status
.\scripts\git-publish.cmd -Message "Approved commit message" -Branch dev/GUI3
```

Stage everything, then publish:

```powershell
.\scripts\git-publish.cmd -Message "Your commit message" -Branch dev/GUI3 -StageAll
```

Publish to the current branch:

```powershell
.\scripts\git-publish.cmd -Message "Your commit message"
```

## Terminal Hygiene

- Do not rely on a reused shared shell for commands where exact stdout matters after a noisy command has already run.
- Use fresh/background terminal sessions for git-critical operations, publish flows, and any test command whose captured output will be summarized back to the user.
- In chat-driven environments that require manual terminal approval, run publish commands in a self-terminating PowerShell session so the shell exits immediately after the command finishes.
- For PowerShell-based assistant tooling, prefer a command form that ends with `exit $LASTEXITCODE` after `scripts/git-publish.cmd` completes.
- Do not leave an idle PowerShell publish session open while waiting for a chat approval reply.
- For background publish commands, do not trust the initial terminal-wrapper response as the complete result. Prefer waiting for terminal completion with terminal-await tooling, and fall back to terminal-output retrieval if needed, before reporting success or failure.
- Prefer direct tools such as changed-file and error inspectors over terminal output when those tools can answer the question.
- Keep the shared shell for lightweight exploration only.

## Prompt Templates For Any AI Assistant

Use one of these prompt patterns directly in chat.

## Shorthand Prompt Convention

For a shorter cross-assistant prompt, use key-value tokens.

Recommended compact form:

```text
publish branch=dev/GUI3 automessage=y stage=task
```

Meaning:

- `publish`: use the repo publish workflow via [scripts/git-publish.cmd](scripts/git-publish.cmd)
- `branch=dev/GUI3`: push `HEAD` to `dev/GUI3`
- `automessage=y`: inspect what will be pushed, propose a commit message in chat, ask for approval or replacement, then run the publish flow once with the approved message
- `stage=task`: stage only files related to the current task; if the correct file set is ambiguous, stop and ask before staging unrelated changes

Other supported staging modes:

- `stage=all`: use `-StageAll`
- `stage=staged`: use the currently staged file set only and do not add more files automatically

Examples:

```text
publish branch=dev/GUI3 automessage=y stage=task
publish branch=main automessage=y stage=staged
publish branch=dev/GUI3 automessage=n stage=all message="Polish queue UI"
```

### Stage specific files and publish

```text
Stage only these files:
- path/to/file1
- path/to/file2

Inspect the staged diff.
Use that diff to suggest a commit message in chat, ask me to approve it or replace it, and then run the script once with the approved message to push to dev/GUI3.
Before committing, verify the changed file set and do not stage unrelated files.
```

### Publish all current changes

```text
Stage all current changes, inspect what will be pushed, suggest an AI-generated commit message in chat, ask me to approve or replace it, and then run scripts/git-publish.cmd once with the approved message to push all current changes to dev/GUI3.
Before pushing, confirm what files will be included.
```

Approval reply format:

```text
approve
```

or

```text
use this message: Your replacement commit message
```

### Safe commit when unrelated changes may exist

```text
Check the repo status.
If there are unrelated changes, stage only these files:
- path/to/file1
- path/to/file2

Then inspect the staged diff.
Suggest a commit message from that diff and ask me to approve it or provide a replacement.
After I approve it, run scripts/git-publish.cmd with the approved message and push to dev/GUI3.
If the staged file set does not match this list, stop and tell me.
```

### Short prompt for AI-assisted publish

```text
Stage only the files for this task.
Inspect the staged diff.
Suggest a commit message based on that diff and ask me to approve it or replace it.
Once I approve, run scripts/git-publish.cmd with the approved message and push to dev/GUI3.
Do not include unrelated changes.
```

## Guidance For AI Agents

- Prefer a fresh PowerShell session for running the publish flow, and prefer [scripts/git-publish.cmd](scripts/git-publish.cmd) as the default Windows entry point.
- Prefer the staged-only flow unless the user explicitly asks for `-StageAll`.
- Confirm the branch target in the prompt when it matters.
- If the user says "commit and push" without naming files, verify the changed file set before staging.
- If the user does not provide a commit message, inspect the intended publish scope directly, draft a commit message in chat, and ask the user to approve or replace it before the final publish run.
- In the happy path, keep the chat output minimal: proposed commit message only, then approval prompt only.
- Do not add a scope summary or reasoning unless the user asked for it or the staged file set needs clarification.
- Do not use the publish script as a preview step for `automessage=y`; reserve it for the final commit/push run after approval.
- When operating through chat or Claude Code approval prompts, invoke publish commands in a self-terminating shell command so the approval text cannot be pasted into an idle PowerShell prompt.
- Do not leave an idle PowerShell publish session open while waiting for the user's chat reply so the reply cannot land in PowerShell.
- After starting a background publish command, prefer terminal-await tooling to capture the full output before reporting the result, and use terminal-output retrieval as a fallback because the initial background terminal response may omit stdout.
- Do not tell the user to inspect the terminal for the proposed message or to answer in PowerShell. Present the proposal in chat and wait for a chat reply.
- Avoid the shared shell for output-sensitive commands once a long or noisy command has already run in it.
- Recognize shorthand prompts such as `publish branch=dev/GUI3 automessage=y stage=task` using the meanings defined above.
