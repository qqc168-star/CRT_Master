param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [int]$PhoneL4MaxAgeSeconds = 300
)

$ErrorActionPreference = "Stop"

$RadarRoot = Join-Path $RepoRoot "radar"
$Registry = Join-Path $RadarRoot "CONFIG\SOURCE_REGISTRY_V1.2.json"
$PhoneL4 = Join-Path $RuntimeRoot "incoming\l4\latest.json"
$ObservationDb = Join-Path $RuntimeRoot "observations.sqlite3"
$EvidenceOutput = Join-Path $RuntimeRoot "evidence\latest.json"
$PrivateProfile = Join-Path $RuntimeRoot "private\portfolio.json"
$WakeOutput = Join-Path $RuntimeRoot "wake\latest.json"
$NoticeOutput = Join-Path $RuntimeRoot "notifications\latest.json"
$HandoffOutput = Join-Path $RuntimeRoot "gpt_handoff\latest.json"
$HandoffLedger = Join-Path $RuntimeRoot "gpt_handoff\ledger.jsonl"
$BridgeOutbox = Join-Path $RuntimeRoot "gpt_bridge\outbox"
$TransportBoundary = Join-Path $RuntimeRoot "gpt_bridge\transport_boundary"
$MaturityLedger = Join-Path $RuntimeRoot "maturity\attempts.jsonl"
$MaturityStatus = Join-Path $RuntimeRoot "maturity\status.json"
$CollectorRunner = Join-Path $RadarRoot "scripts\windows\run_liquidation_collector_windows.ps1"
$CollectorRuntime = Join-Path $RuntimeRoot "l4_collector"
$EtpCaptureIfDue = Join-Path $RadarRoot "scripts\windows\run_etp_capture_if_due_windows.ps1"
$IssuerAnnouncementRegistry = Join-Path $RadarRoot "CONFIG\ISSUER_ANNOUNCEMENT_REGISTRY_V1.json"
$IssuerAnnouncementState = Join-Path $RuntimeRoot "issuer_announcements\state.json"
$IssuerAnnouncementLedger = Join-Path $RuntimeRoot "issuer_announcements\events.jsonl"
$IssuerAnnouncementOutput = Join-Path $RuntimeRoot "issuer_announcements\latest.json"
$MstrAsstMarketHealth = Join-Path $RuntimeRoot "market-health\latest.json"

if (-not (Test-Path $RadarRoot)) {
    throw "CRT Radar repo not found: $RadarRoot"
}
if (-not (Test-Path $Registry)) {
    throw "Source Registry not found: $Registry"
}

New-Item -ItemType Directory -Force (Split-Path $ObservationDb -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $EvidenceOutput -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $PhoneL4 -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $PrivateProfile -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $WakeOutput -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $NoticeOutput -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $HandoffOutput -Parent) | Out-Null
New-Item -ItemType Directory -Force $BridgeOutbox | Out-Null
New-Item -ItemType Directory -Force $TransportBoundary | Out-Null
New-Item -ItemType Directory -Force (Split-Path $MaturityStatus -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $IssuerAnnouncementOutput -Parent) | Out-Null

$Python = Join-Path $RadarRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python not found. Run radar\scripts\windows\setup_windows.ps1 first."
    }
    $Python = $PythonCommand.Source
}

$env:PYTHONPATH = Join-Path $RadarRoot "src"

# The existing hourly task also acts as a watchdog for the continuous, read-only
# liquidation collector. It starts a hidden worker only when no matching worker exists.
if (Test-Path $CollectorRunner) {
    $CollectorProcess = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains("crt_radar.liquidation_collector") -and
            $_.CommandLine.Contains($CollectorRuntime)
        } |
        Select-Object -First 1
    if (-not $CollectorProcess) {
        $CollectorArguments = (
            '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -RepoRoot "{1}" -RuntimeRoot "{2}" -MaxRuntimeSeconds 0' -f
            $CollectorRunner, $RepoRoot, $RuntimeRoot
        )
        Start-Process -FilePath "powershell.exe" -ArgumentList $CollectorArguments -WindowStyle Hidden
    }
}

if (Test-Path -LiteralPath $IssuerAnnouncementRegistry) {
    $IssuerAnnouncementArgs = @(
        "-m", "crt_radar.issuer_announcement_runner",
        "--registry", $IssuerAnnouncementRegistry,
        "--state", $IssuerAnnouncementState,
        "--ledger", $IssuerAnnouncementLedger,
        "--output", $IssuerAnnouncementOutput
    )
    & $Python @IssuerAnnouncementArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Issuer announcement radar requires attention."
    }
}

$RunnerArgs = @(
    "-m", "crt_radar.daily_evidence_runner",
    "--registry", $Registry,
    "--liquidation-snapshot", $PhoneL4,
    "--observation-db", $ObservationDb,
    "--output", $EvidenceOutput,
    "--private-profile", $PrivateProfile,
    "--wake-output", $WakeOutput,
    "--notice-output", $NoticeOutput,
    "--handoff-output", $HandoffOutput,
    "--handoff-ledger", $HandoffLedger,
    "--bridge-outbox-dir", $BridgeOutbox,
    "--maturity-ledger", $MaturityLedger,
    "--maturity-status", $MaturityStatus,
    "--phone-l4-freshness-path", $PhoneL4,
    "--phone-l4-max-age-seconds", "$PhoneL4MaxAgeSeconds"
)

if (Test-Path -LiteralPath $MstrAsstMarketHealth) {
    $RunnerArgs += @(
        "--mstr-asst-market-health",
        $MstrAsstMarketHealth
    )
    Write-Host "MSTR_ASST_MARKET_HEALTH_RUNTIME_INPUT_READY" -ForegroundColor Green
}
else {
    Write-Host "MSTR_ASST_MARKET_HEALTH_WAITING_FOR_VALIDATED_SNAPSHOT" -ForegroundColor Yellow
}

& $Python @RunnerArgs
$EvidenceExit = $LASTEXITCODE
if ($EvidenceExit -ne 0) {
    exit $EvidenceExit
}

$TransportBoundaryArgs = @(
    "-m", "crt_radar.gpt_transport_boundary",
    "sync",
    "--outbox-dir", $BridgeOutbox,
    "--state-dir", $TransportBoundary
)
& $Python @TransportBoundaryArgs
$TransportBoundaryExit = $LASTEXITCODE
if ($TransportBoundaryExit -ne 0) {
    exit $TransportBoundaryExit
}

if (Test-Path -LiteralPath $EtpCaptureIfDue) {
    try {
        & $EtpCaptureIfDue -RepoRoot $RepoRoot -RuntimeRoot $RuntimeRoot
    }
    catch {
        Write-Warning "ETP prospective capture caller requires attention: $($_.Exception.Message)"
    }
}

exit 0
