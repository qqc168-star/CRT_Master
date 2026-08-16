param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [int]$MaxRuntimeSeconds = 0,
    [string]$TaskName = "CRT-L4-Liquidation-Collector"
)

$ErrorActionPreference = "Stop"

$Runner = Join-Path $RepoRoot "radar\scripts\windows\run_liquidation_collector_windows.ps1"
if (-not (Test-Path $Runner)) {
    throw "Liquidation collector runner not found: $Runner"
}

$ActionArguments = (
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -RepoRoot "{1}" -RuntimeRoot "{2}" -MaxRuntimeSeconds {3}' -f
    $Runner, $RepoRoot, $RuntimeRoot, $MaxRuntimeSeconds
)

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "CRT read-only persistent BTC liquidation collector" `
    -Force | Out-Null

Write-Host "L4_LIQUIDATION_COLLECTOR_TASK_READY" -ForegroundColor Green
Write-Host "TaskName = $TaskName"
Write-Host "RuntimeRoot = $RuntimeRoot"
