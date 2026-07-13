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
if ($env:PYTHONPATH) {
    if ($env:PYTHONPATH -notlike "*$scriptsDir*") {
        $env:PYTHONPATH = $scriptsDir + ";" + $env:PYTHONPATH
    }
} else {
    $env:PYTHONPATH = $scriptsDir
}
if ($null -eq $AuditArgs) { $AuditArgs = @() }
& $python -m audit @AuditArgs
exit $LASTEXITCODE
