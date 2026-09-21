param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [double]$AcceptanceWakePercentile = 0.1,
    [int]$WaitSeconds = 600
)

$ErrorActionPreference = "Stop"

if (
    [double]::IsNaN($AcceptanceWakePercentile) -or
    $AcceptanceWakePercentile -le 0.0 -or
    $AcceptanceWakePercentile -gt 100.0
) {
    throw "Acceptance wake percentile must be in (0, 100]"
}

$RadarRoot = Join-Path $RepoRoot "radar"
$Python = Join-Path $RadarRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python not found."
    }
    $Python = $PythonCommand.Source
}

$ApiKey = [Environment]::GetEnvironmentVariable(
    "OPENAI_API_KEY",
    "User"
)
if (-not $ApiKey) {
    throw "OPENAI_API_KEY unavailable in User environment."
}

$env:OPENAI_API_KEY = $ApiKey
$env:PYTHONPATH = Join-Path $RadarRoot "src"
$env:PYTHONIOENCODING = "utf-8"

$RunId = [Guid]::NewGuid().ToString("N")
$Report = Join-Path $RuntimeRoot "gpt_bridge\acceptance\$RunId.json"
$Observer = Join-Path $RadarRoot "scripts\accept_one_gpt_event.py"
$ObservationRunner = Join-Path (
    Join-Path $RadarRoot "scripts\windows"
) "run_observation_history_windows.ps1"

if (-not (Test-Path $Observer)) {
    throw "accept_one_gpt_event.py unavailable."
}
if (-not (Test-Path $ObservationRunner)) {
    throw "run_observation_history_windows.ps1 unavailable."
}

$ObserverArgs = @(
    $Observer,
    "--runtime-root", $RuntimeRoot,
    "--output", $Report,
    "--wait-seconds", "$WaitSeconds"
)

$ObserverProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList (($ObserverArgs | ForEach-Object { '"{0}"' -f $_ }) -join " ") `
    -PassThru `
    -WindowStyle Hidden

$PreviousTransportEnabled = $env:CRT_GPT_TRANSPORT_ENABLED
try {
    # The observer owns this invocation's single transport attempt.
    $env:CRT_GPT_TRANSPORT_ENABLED = "0"
    $ReadyDeadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not (Test-Path -LiteralPath $Report)) {
        if ($ObserverProcess.HasExited -or [DateTime]::UtcNow -gt $ReadyDeadline) {
            throw "Acceptance observer did not establish its baseline."
        }
        Start-Sleep -Milliseconds 100
    }
    & $ObservationRunner `
        -RepoRoot $RepoRoot `
        -RuntimeRoot $RuntimeRoot `
        -AcceptanceWakePercentile $AcceptanceWakePercentile `
        -ConfirmAcceptanceWakeOverride

    if ($LASTEXITCODE -ne 0) {
        throw "One-shot observation cycle failed."
    }

    $ObserverProcess.WaitForExit(
        [Math]::Max(1000, ($WaitSeconds + 10) * 1000)
    ) | Out-Null

    if (-not $ObserverProcess.HasExited) {
        Stop-Process -Id $ObserverProcess.Id -Force
        throw "Acceptance observer exceeded wait window."
    }

    if (-not (Test-Path $Report)) {
        throw "Acceptance report unavailable."
    }

    $Result = Get-Content -Raw -LiteralPath $Report |
        ConvertFrom-Json

    $Result | ConvertTo-Json -Depth 12

    if ($ObserverProcess.ExitCode -ne 0 -or $Result.state -ne "LIVE_ACCEPTANCE_PASS" -or
        $Result.acceptance_override_used -ne $true -or
        $Result.acceptance_wake_operational_percentile -ne $AcceptanceWakePercentile -or
        $Result.production_wake_operational_percentile -notin @(90, 95) -or
        $Result.persistent_configuration_changed -ne $false) {
        throw "GPT transport live acceptance did not PASS."
    }

    Write-Host "GPT_TRANSPORT_LIVE_ACCEPTANCE_PASS" -ForegroundColor Green
}
finally {
    $env:CRT_GPT_TRANSPORT_ENABLED = $PreviousTransportEnabled
    if (-not $ObserverProcess.HasExited) {
        Stop-Process -Id $ObserverProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
