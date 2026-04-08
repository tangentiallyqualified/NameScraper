[CmdletBinding()]
param(
    [string]$Message,

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
        Write-Host "Approval does not happen in this terminal."
        Write-Host "For AI-assisted publish flows, inspect the staged changes directly in chat,"
        Write-Host "propose a commit message there, wait for approval, and then run this script"
        Write-Host "once with -Message <approved message>."
        Write-Host ""
        Write-Host "Reply in chat using one of these formats:"
        Write-Host "- CHAT APPROVAL: approve"
        Write-Host "- CHAT REPLACEMENT: use this message: <your preferred commit message>"
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
