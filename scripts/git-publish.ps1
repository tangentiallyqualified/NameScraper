[CmdletBinding()]
param(
    [string]$Message,

    [string]$ProposedMessage,

    [string]$Remote = "origin",

    [string]$Branch,

    [switch]$StageAll
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-StagedChangeSummary {
    Write-Host ""
    Write-Host "Staged change summary:"
    git diff --cached --stat
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect staged diff stats."
    }

    Write-Host ""
    Write-Host "Staged files:"
    git diff --cached --name-status
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect staged file list."
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot

try {
    $currentBranch = (git branch --show-current).Trim()
    if (-not $currentBranch) {
        throw "Unable to determine the current branch."
    }

    if (-not $Branch) {
        $Branch = $currentBranch
    }

    Write-Host "Repository: $repoRoot"
    Write-Host "Current branch: $currentBranch"
    Write-Host "Target branch: $Branch"
    Write-Host ""
    Write-Host "Working tree status:"
    git status --short
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed."
    }

    if ($StageAll) {
        Write-Host ""
        Write-Host "Staging all tracked and untracked changes..."
        git add -A
        if ($LASTEXITCODE -ne 0) {
            throw "git add failed."
        }
    }

    git diff --cached --quiet
    if ($LASTEXITCODE -ne 1) {
        if ($LASTEXITCODE -eq 0) {
            throw "No staged changes found. Stage files first or rerun with -StageAll."
        }
        throw "Unable to inspect staged changes."
    }

    if ([string]::IsNullOrWhiteSpace($Message)) {
        Show-StagedChangeSummary
        Write-Host ""
        Write-Host "No commit message was provided."
        Write-Host ""

        if (-not [string]::IsNullOrWhiteSpace($ProposedMessage)) {
            Write-Host "Proposed commit message:"
            Write-Host "  $ProposedMessage"
            Write-Host ""
            Write-Host "Approval does not happen in this terminal."
            Write-Host "Use the same proposed message shown by the AI assistant in chat."
            Write-Host ""
            Write-Host "Reply in chat using one of these formats:"
            Write-Host "- CHAT APPROVAL: approve"
            Write-Host "- CHAT REPLACEMENT: use this message: <your preferred commit message>"
            Write-Host ""
            Write-Host "AI assistant next step:"
            Write-Host "1. Capture this output, then close this temporary terminal session."
            Write-Host "2. Present this same proposed message in chat."
            Write-Host "3. Ask the user to approve it or provide a replacement."
            Write-Host "4. Rerun this script with -Message <approved message>."
            return
        }

        Write-Host "Approval does not happen in this terminal."
        Write-Host "Wait for the AI assistant to return to chat with a proposed commit message."
        Write-Host ""
        Write-Host "Reply in chat using one of these formats:"
        Write-Host "- CHAT APPROVAL: approve"
        Write-Host "- CHAT REPLACEMENT: use this message: <your preferred commit message>"
        Write-Host ""
        Write-Host "AI assistant next step:"
        Write-Host "1. Capture this output, then close this temporary terminal session."
        Write-Host "2. Summarize the staged changes."
        Write-Host "3. Propose a commit message."
        Write-Host "4. Rerun this script with -ProposedMessage <suggested message> so the proposal is visible in terminal."
        Write-Host "5. Close that temporary terminal session after capturing the proposal output."
        Write-Host "6. Present the same proposed message in chat and ask the user to approve it or provide a replacement."
        Write-Host "7. Rerun this script with -Message <approved message>."
        return
    }

    Write-Host ""
    Write-Host "Committing staged changes..."
    git commit -m $Message
    if ($LASTEXITCODE -ne 0) {
        throw "git commit failed."
    }

    Write-Host ""
    Write-Host "Pushing HEAD to $Remote/$Branch..."
    git push -u $Remote "HEAD:$Branch"
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed."
    }

    Write-Host ""
    Write-Host "Publish complete."
}
finally {
    Pop-Location
}
