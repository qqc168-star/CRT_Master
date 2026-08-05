param(
    [ValidateSet("Status", "Verify")]
    [string]$Mode = "Status"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Runtime = Join-Path $Root "runtime_live_shadow"
$PidFile = Join-Path $Runtime "live_shadow.pid"
$Latest = Join-Path $Runtime "snapshots\latest.json"
$Summary = Join-Path $Runtime "evidence\live_shadow_summary.json"
$VerifyScript = Join-Path $PSScriptRoot "verify_live_shadow_windows.ps1"

$StartedAt = [DateTimeOffset]::Parse("2026-08-01T15:09:48+08:00")
$Deadline = $StartedAt.AddSeconds(86400)
$Now = [DateTimeOffset]::Now

$PidValue = $null
$Proc = $null

if (Test-Path -LiteralPath $PidFile) {
    $RawPid = ((Get-Content -LiteralPath $PidFile | Select-Object -First 1)).Trim()
    $ParsedPid = 0

    if ([int]::TryParse($RawPid, [ref]$ParsedPid)) {
        $PidValue = $ParsedPid
        $Proc = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    }
}

if ($Proc) {
    Write-Host "PROCESS=RUNNING PID=$PidValue" -ForegroundColor Green
} elseif ($PidValue) {
    Write-Host "PROCESS=NOT_RUNNING LAST_PID=$PidValue" -ForegroundColor Yellow
} else {
    Write-Host "PROCESS=NO_PID_FILE" -ForegroundColor Yellow
}

if (Test-Path -LiteralPath $Latest) {
    $LatestItem = Get-Item -LiteralPath $Latest
    $AgeSeconds = [math]::Round(
        ([DateTime]::Now - $LatestItem.LastWriteTime).TotalSeconds
    )

    if ($AgeSeconds -le 300) {
        Write-Host "SNAPSHOT=FRESH AGE_SECONDS=$AgeSeconds LAST=$($LatestItem.LastWriteTime)" -ForegroundColor Green
    } else {
        Write-Host "SNAPSHOT=STALE AGE_SECONDS=$AgeSeconds LAST=$($LatestItem.LastWriteTime)" -ForegroundColor Red
    }
} else {
    Write-Host "SNAPSHOT=MISSING" -ForegroundColor Red
}

$ElapsedHours = [math]::Round(($Now - $StartedAt).TotalHours, 2)

if ($Now -lt $Deadline) {
    $Remaining = $Deadline - $Now
    $RemainingText = "{0:00}:{1:00}:{2:00}" -f `
        [math]::Floor($Remaining.TotalHours), `
        $Remaining.Minutes, `
        $Remaining.Seconds

    Write-Host "GATE=WAITING ELAPSED_HOURS=$ElapsedHours REMAINING=$RemainingText" -ForegroundColor Yellow
    Write-Host "EARLIEST_VERIFY=$($Deadline.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
} else {
    Write-Host "GATE=TIME_REQUIREMENT_REACHED ELAPSED_HOURS=$ElapsedHours" -ForegroundColor Green
}

if ($Mode -eq "Status") {
    Write-Host "STATUS_CHECK_PASS" -ForegroundColor Green
    return
}

if ($Now -lt $Deadline) {
    throw "VERIFY_BLOCKED_BEFORE_24_HOURS"
}

if ($Proc) {
    throw "VERIFY_BLOCKED_RUNNER_STILL_RUNNING"
}

if (-not (Test-Path -LiteralPath $VerifyScript)) {
    throw "VERIFY_SCRIPT_MISSING"
}

& $VerifyScript

if ($LASTEXITCODE -ne 0) {
    throw "LIVE_SHADOW_VERIFY_COMMAND_FAILED"
}

if (-not (Test-Path -LiteralPath $Summary)) {
    throw "LIVE_SHADOW_SUMMARY_MISSING"
}

$Result = Get-Content -LiteralPath $Summary -Raw | ConvertFrom-Json
$Decision = [string]$Result.decision

Write-Host "FINAL_DECISION=$Decision"

if ($Decision -ne "LIVE_SHADOW_PASS") {
    throw "LIVE_SHADOW_NOT_PASSED"
}

Write-Host "LIVE_SHADOW_GATE_PASS" -ForegroundColor Green