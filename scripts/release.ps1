<#
.SYNOPSIS
    Bump version, update CHANGELOG.md, commit, and tag.

.DESCRIPTION
    Reads the current version from pyproject.toml, computes the next version
    (via -Bump or -Version), prepends a dated changelog entry with commit
    subjects since the last tag, updates pyproject.toml, commits, and tags.

    Does NOT push by default — pass -Push to push the commit and tag.

.EXAMPLE
    .\scripts\release.cmd -Bump patch
    .\scripts\release.cmd -Version 1.0.0 -Push
#>

[CmdletBinding()]
param(
    # Explicit version string (e.g. "0.2.0").  Mutually exclusive with -Bump.
    [string]$Version,

    # Semver component to increment.  Mutually exclusive with -Version.
    [ValidateSet("major", "minor", "patch")]
    [string]$Bump,

    [string]$Remote = "origin",

    # Push the release commit and tag after creating them.
    [switch]$Push
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Parse-Semver([string]$v) {
    if ($v -match '^\d+\.\d+\.\d+$') {
        $parts = $v -split '\.'
        return @([int]$parts[0], [int]$parts[1], [int]$parts[2])
    }
    throw "Cannot parse version '$v' - expected MAJOR.MINOR.PATCH"
}

function Bump-Semver([int[]]$parts, [string]$kind) {
    switch ($kind) {
        "major" { return "$($parts[0]+1).0.0" }
        "minor" { return "$($parts[0]).$($parts[1]+1).0" }
        "patch" { return "$($parts[0]).$($parts[1]).$($parts[2]+1)" }
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot

try {
    # Validate parameters
    if ($Version -and $Bump) {
        throw "Pass -Version or -Bump, not both."
    }
    if (-not $Version -and -not $Bump) {
        throw "Pass -Version <semver> or -Bump major|minor|patch."
    }

    # Ensure clean working tree
    $status = git status --porcelain
    if ($status) {
        throw "Working tree is not clean - commit or stash changes first."
    }

    # Read current version from pyproject.toml
    $tomlPath = Join-Path $repoRoot "pyproject.toml"
    $tomlText = Get-Content $tomlPath -Raw
    if ($tomlText -match 'version\s*=\s*"(\d+\.\d+\.\d+)"') {
        $currentVersion = $Matches[1]
    } else {
        throw "Could not find version in pyproject.toml"
    }

    # Compute next version
    if ($Version) {
        $null = Parse-Semver $Version  # validate format
        $nextVersion = $Version
    } else {
        $parts = Parse-Semver $currentVersion
        $nextVersion = Bump-Semver $parts $Bump
    }

    Write-Host "Current version: $currentVersion"
    Write-Host "Next version:    $nextVersion"
    Write-Host ""

    # Gather commit subjects since last tag (or all if no tags)
    $lastTag = git describe --tags --abbrev=0 2>$null
    if ($lastTag) {
        $logRange = "$lastTag..HEAD"
        Write-Host "Changelog since tag: $lastTag"
    } else {
        $logRange = "HEAD"
        Write-Host "Changelog: all commits (no previous tag found)"
    }
    $subjects = git log $logRange --format="- %s" --no-merges
    if (-not $subjects) {
        $subjects = @("- No changes since last tag")
    }
    Write-Host ""

    # Build changelog entry
    $date = (Get-Date).ToString("yyyy-MM-dd")
    $entry = "## $nextVersion -- $date`n`n"
    $entry += ($subjects -join "`n") + "`n"

    # Prepend to CHANGELOG.md
    $changelogPath = Join-Path $repoRoot "CHANGELOG.md"
    if (Test-Path $changelogPath) {
        $existing = Get-Content $changelogPath -Raw
        # Insert after the "# Changelog" header
        if ($existing -match '^# Changelog\r?\n') {
            $header = $Matches[0]
            $rest = $existing.Substring($header.Length)
            $newContent = "$header`n$entry`n$rest"
        } else {
            $newContent = "# Changelog`n`n$entry`n$existing"
        }
    } else {
        $newContent = "# Changelog`n`n$entry"
    }
    Set-Content -Path $changelogPath -Value $newContent.TrimEnd() -NoNewline -Encoding utf8

    # Update pyproject.toml
    $tomlText = $tomlText -replace ('version\s*=\s*"' + [regex]::Escape($currentVersion) + '"'), "version = `"$nextVersion`""
    Set-Content -Path $tomlPath -Value $tomlText.TrimEnd() -NoNewline -Encoding utf8

    # Commit and tag
    git add $tomlPath $changelogPath
    git commit -m "Release v$nextVersion"
    if ($LASTEXITCODE -ne 0) { throw "git commit failed." }

    git tag "v$nextVersion"
    if ($LASTEXITCODE -ne 0) { throw "git tag failed." }

    Write-Host ""
    Write-Host "Created commit and tag v$nextVersion"

    # Push if requested
    if ($Push) {
        $currentBranch = (git branch --show-current).Trim()
        Write-Host ""
        Write-Host "Pushing to $Remote/$currentBranch..."
        git push -u $Remote "HEAD:$currentBranch"
        if ($LASTEXITCODE -ne 0) { throw "git push failed." }
        git push $Remote "v$nextVersion"
        if ($LASTEXITCODE -ne 0) { throw "git push (tag) failed." }
        Write-Host "Pushed commit and tag."
    } else {
        Write-Host ""
        Write-Host "Run with -Push to push, or manually:"
        Write-Host "  git push -u $Remote HEAD"
        Write-Host "  git push $Remote v$nextVersion"
    }
} finally {
    Pop-Location
}
