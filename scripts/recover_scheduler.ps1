param(
    [string]$Country = "mk",
    [int]$IntervalMinutes = 15,
    [switch]$NoEmail,
    [switch]$SkipInitialRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pidFile = Join-Path $root "data\scheduler.pid"

if (Test-Path -LiteralPath $pidFile) {
    $storedPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $running = $false
    if ($storedPid -match "^\d+$") {
        $running = Get-Process -Id ([int]$storedPid) -ErrorAction SilentlyContinue
    }
    if ($running) {
        Write-Host "Scheduler is already running (PID $storedPid)."
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host "Removed stale scheduler PID $storedPid."
}

$arguments = @{
    Country = $Country
    IntervalMinutes = $IntervalMinutes
}
if ($NoEmail) {
    $arguments["NoEmail"] = $true
}
if ($SkipInitialRun) {
    $arguments["SkipInitialRun"] = $true
}

& (Join-Path $root "scripts\start_scheduler.ps1") @arguments
