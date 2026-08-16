[CmdletBinding()]
param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [int]$CaptureHourNewYork = 20
)

$ErrorActionPreference = "Stop"

if ($CaptureHourNewYork -lt 0 -or $CaptureHourNewYork -gt 23) {
    throw "CaptureHourNewYork must be between 0 and 23."
}

$Eastern = [TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
$NewYorkNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, $Eastern.Id)
if ($NewYorkNow.DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)) {
    Write-Output "ETP_CAPTURE_NOT_DUE_WEEKEND"
    exit 0
}
if ($NewYorkNow.Hour -lt $CaptureHourNewYork) {
    Write-Output "ETP_CAPTURE_NOT_DUE_TIME"
    exit 0
}

$ArchiveRoot = Join-Path $RuntimeRoot "etp_prospective_capture"
$ScheduleRoot = Join-Path $ArchiveRoot "schedule"
$MarkerPath = Join-Path $ScheduleRoot "last_successful_attempt.json"
$SessionDate = $NewYorkNow.ToString("yyyy-MM-dd")
if (Test-Path -LiteralPath $MarkerPath) {
    try {
        $Marker = Get-Content -LiteralPath $MarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($Marker.session_date -eq $SessionDate) {
            Write-Output "ETP_CAPTURE_ALREADY_ATTEMPTED"
            exit 0
        }
    }
    catch {
        throw "ETP capture schedule marker is invalid: $MarkerPath"
    }
}

$Runner = Join-Path $RepoRoot "radar\scripts\windows\run_etp_prospective_capture_windows.ps1"
if (-not (Test-Path -LiteralPath $Runner)) {
    throw "ETP capture runner not found: $Runner"
}

& $Runner -ArchiveRoot $ArchiveRoot
if ($LASTEXITCODE -ne 0) {
    throw "ETP capture attempt requires retry."
}

New-Item -ItemType Directory -Force -Path $ScheduleRoot | Out-Null
$Marker = [ordered]@{
    schema_version = "CRT_ETP_CALLER_SCHEDULE_MARKER_V1"
    session_date = $SessionDate
    attempted_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    action_output = "NONE"
    external_action_authority = "NONE"
    external_action_performed = $false
}
$Marker | ConvertTo-Json | Set-Content -LiteralPath $MarkerPath -Encoding UTF8
Write-Output "ETP_CAPTURE_DAILY_ATTEMPT_RECORDED"
