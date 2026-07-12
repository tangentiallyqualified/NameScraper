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

$env:PYTHONPATH = Join-Path $repoRoot "scripts"
if ($null -eq $AuditArgs) { $AuditArgs = @() }
& $python -m audit @AuditArgs
exit $LASTEXITCODE
