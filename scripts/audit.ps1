param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AuditArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Python environment not found at '$python'."
    exit 1
}

$scriptsDir = Join-Path $repoRoot "scripts"
$pythonPathParts = @()
if ($env:PYTHONPATH) { $pythonPathParts = $env:PYTHONPATH -split ";" }
if ($pythonPathParts -notcontains $scriptsDir) {
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = $scriptsDir + ";" + $env:PYTHONPATH
    } else {
        $env:PYTHONPATH = $scriptsDir
    }
}
if ($null -eq $AuditArgs) { $AuditArgs = @() }
& $python -m audit @AuditArgs
exit $LASTEXITCODE
