$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Runtime = Join-Path $Root "runtime_live_shadow"
$PidFile = Join-Path $Runtime "live_shadow.pid"
if (-not (Test-Path $PidFile)) {
    Write-Host "NO_PID_FILE"
    exit 0
}
$PidValue = (Get-Content $PidFile | Select-Object -First 1)
$Proc = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
if ($Proc) {
    Write-Host "RUNNING PID=$PidValue STARTED=$($Proc.StartTime)" -ForegroundColor Green
} else {
    Write-Host "NOT_RUNNING LAST_PID=$PidValue" -ForegroundColor Yellow
}
$Latest = Join-Path $Runtime "snapshots\latest.json"
if (Test-Path $Latest) {
    Write-Host "LATEST_SNAPSHOT=$((Get-Item $Latest).LastWriteTime)"
}
$Summary = Join-Path $Runtime "evidence\live_shadow_summary.json"
if (Test-Path $Summary) {
    Write-Host "SUMMARY_EXISTS=$Summary"
}
