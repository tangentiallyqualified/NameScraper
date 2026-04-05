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
- If `-Message` is omitted, the script enters a preparation mode: it prints a staged-change summary and stops so the AI assistant can propose a commit message and ask the user to approve or replace it.
- If `-ProposedMessage` is supplied without `-Message`, the script prints the staged summary and the proposed commit message, then stops for chat-based approval.
- Approval happens in chat after the assistant returns with the proposed message. The script is not waiting for a terminal response.

## Recommended AI Workflow

1. Verify the changed file set.
2. Stage only the files intended for the commit, unless the user explicitly wants everything staged.
3. If no approved message exists yet, run the publish script without `-Message` to print the staged summary.
4. Have the AI assistant propose a commit message from that summary.
5. Rerun the publish script with `-ProposedMessage` so the proposed message is visible in the terminal.
6. Present that same proposed message in chat and ask the user to approve it or provide a substitute.
7. Rerun the publish script with the approved commit message and target branch.
8. Report the resulting commit hash and push result.

## Commands

Stage selected files first, then publish:

```powershell
git add -- path/to/file1 path/to/file2
.\scripts\git-publish.cmd -Message "Your commit message" -Branch dev/GUI3
```

Stage selected files, ask the AI to propose a message, then publish:

```powershell
git add -- path/to/file1 path/to/file2
.\scripts\git-publish.cmd -Branch dev/GUI3
```

Show a proposed message in terminal before approval:

```powershell
.\scripts\git-publish.cmd -Branch dev/GUI3 -ProposedMessage "Proposed commit message"
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
- `automessage=y`: run the publish flow without `-Message`, summarize staged changes, propose a commit message, show that same proposal in terminal and chat, ask for approval or replacement, then rerun with the approved message
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

Then run scripts/git-publish.cmd without a commit message so it shows the staged summary.
Use that summary to suggest a commit message, ask me to approve it or replace it, and then rerun the script with the approved message to push to dev/GUI3.
Before committing, verify the changed file set and do not stage unrelated files.
```

### Publish all current changes

```text
Use scripts/git-publish.cmd with -StageAll and no commit message first.
Show me the staged summary, suggest an AI-generated commit message, ask me to approve or replace it, and then rerun the script with the approved message to push all current changes to dev/GUI3.
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

Then run scripts/git-publish.cmd without a commit message so it prints the staged summary.
Suggest a commit message from that summary and ask me to approve it or provide a replacement.
After I approve it, rerun scripts/git-publish.cmd with the approved message and push to dev/GUI3.
If the staged file set does not match this list, stop and tell me.
```

### Short prompt for AI-assisted publish

```text
Stage only the files for this task.
Run scripts/git-publish.cmd without -Message so it prints the staged summary.
Suggest a commit message based on that summary and ask me to approve it or replace it.
Once I approve, rerun scripts/git-publish.cmd with the approved message and push to dev/GUI3.
Do not include unrelated changes.
```

## Guidance For AI Agents

- Prefer a fresh PowerShell session for running the publish flow, and prefer [scripts/git-publish.cmd](scripts/git-publish.cmd) as the default Windows entry point.
- Prefer the staged-only flow unless the user explicitly asks for `-StageAll`.
- Confirm the branch target in the prompt when it matters.
- If the user says "commit and push" without naming files, verify the changed file set before staging.
- If the user does not provide a commit message, run the script without `-Message`, use the staged summary to draft a commit message, and ask the user to approve or replace it before the final publish run.
- After drafting a commit message, rerun the script with `-ProposedMessage` so the same proposal is visible in the terminal before asking for approval in chat.
- Do not tell the user to inspect the terminal for the proposed message or to answer in PowerShell. Present the proposal in chat and wait for a chat reply.
- Avoid the shared shell for output-sensitive commands once a long or noisy command has already run in it.
- Recognize shorthand prompts such as `publish branch=dev/GUI3 automessage=y stage=task` using the meanings defined above.
