param(
    [switch]$VerbosePytest,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $PSScriptRoot "test_fast_runner.py"

if (-not (Test-Path $python)) {
    Write-Error "Python environment not found at '$python'. Create or select the repo venv before running fast tests."
    exit 1
}

$runnerArgs = @($runner)
if ($VerbosePytest) {
    $runnerArgs += "--verbose-pytest"
}
if ($null -ne $PytestArgs -and $PytestArgs.Count -gt 0) {
    $runnerArgs += $PytestArgs
}

& $python @runnerArgs
exit $LASTEXITCODE
