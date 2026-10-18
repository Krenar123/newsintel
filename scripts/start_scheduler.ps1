param(
    [string]$Country = "mk",
    [int]$IntervalMinutes = 15,
    [switch]$NoEmail,
    [switch]$SkipInitialRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $root "venv\Scripts\python.exe"
$logDir = Join-Path $root "data"
$outLog = Join-Path $logDir "scheduler.out.log"
$errLog = Join-Path $logDir "scheduler.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$arguments = @(
    "scripts\scheduler.py",
    "--country", $Country,
    "--interval-minutes", $IntervalMinutes
)

if ($NoEmail) {
    $arguments += "--no-email"
}
if ($SkipInitialRun) {
    $arguments += "--skip-initial-run"
}

$env:PYTHONIOENCODING = "utf-8"

$process = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Write-Host "NewsIntel scheduler launch requested for country '$Country' every $IntervalMinutes minutes (PID $($process.Id))."
Write-Host "Logs:"
Write-Host "  $outLog"
Write-Host "  $errLog"
