param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [int]$IntervalMinutes = 60,
    [int]$PhoneL4MaxAgeSeconds = 300,
    [string]$TaskName = "CRT-Observation-History"
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 5) {
    throw "IntervalMinutes must be at least 5."
}
if ($PhoneL4MaxAgeSeconds -le 0) {
    throw "PhoneL4MaxAgeSeconds must be positive."
}

$Runner = Join-Path $RepoRoot "radar\scripts\windows\run_observation_history_windows.ps1"
if (-not (Test-Path $Runner)) {
    throw "Observation runner not found: $Runner"
}

$ActionArguments = (
    '-NoProfile -ExecutionPolicy Bypass -File "{0}" -RepoRoot "{1}" -RuntimeRoot "{2}" -PhoneL4MaxAgeSeconds {3}' -f
    $Runner, $RepoRoot, $RuntimeRoot, $PhoneL4MaxAgeSeconds
)

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArguments
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "CRT read-only Evidence Runner -> permanent Observation History" `
    -Force | Out-Null

Write-Host "OBSERVATION_HISTORY_TASK_READY" -ForegroundColor Green
Write-Host "TaskName = $TaskName"
Write-Host "IntervalMinutes = $IntervalMinutes"
Write-Host "RuntimeRoot = $RuntimeRoot"
Write-Host "PhoneL4MaxAgeSeconds = $PhoneL4MaxAgeSeconds"
