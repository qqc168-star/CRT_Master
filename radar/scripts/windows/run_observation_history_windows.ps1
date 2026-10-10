param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [int]$PhoneL4MaxAgeSeconds = 300,
    [Nullable[double]]$AcceptanceWakePercentile = $null,
    [switch]$ConfirmAcceptanceWakeOverride,
    [ValidateSet("ISOLATION_ONLY", "OBSERVATION")]
    [string]$RunMode = "ISOLATION_ONLY"
)

$ErrorActionPreference = "Stop"

# Decide before resolving paths, starting processes, or touching Runtime.
# A successful standby exit is not a completed observation cycle.
if ($RunMode -eq "ISOLATION_ONLY") {
    if (
        $PSBoundParameters.ContainsKey("AcceptanceWakePercentile") -or
        $PSBoundParameters.ContainsKey("ConfirmAcceptanceWakeOverride")
    ) {
        throw "ISOLATION_ONLY rejects acceptance wake override parameters"
    }
    Write-Output "ISOLATED_ALIGNMENT_STANDBY"
    Write-Output "NO_OBSERVATION_CYCLE"
    Write-Output "NO_CAPITAL_REFRESH"
    Write-Output "NO_GPT_DELIVERY"
    Write-Output "NO_NOTIFICATION_DELIVERY"
    exit 0
}

if ($null -ne $AcceptanceWakePercentile) {
    if (-not $ConfirmAcceptanceWakeOverride) {
        throw "Acceptance wake override requires -ConfirmAcceptanceWakeOverride"
    }
    if (
        [double]::IsNaN([double]$AcceptanceWakePercentile) -or
        [double]$AcceptanceWakePercentile -le 0.0 -or
        [double]$AcceptanceWakePercentile -gt 100.0
    ) {
        throw "Acceptance wake percentile must be in (0, 100]"
    }
}



$RadarRoot = Join-Path $RepoRoot "radar"
$Registry = Join-Path $RadarRoot "CONFIG\SOURCE_REGISTRY_V1.2.json"
$PhoneL4 = Join-Path $RuntimeRoot "incoming\l4\latest.json"
$ObservationDb = Join-Path $RuntimeRoot "observations.sqlite3"
$EvidenceOutput = Join-Path $RuntimeRoot "evidence\latest.json"
$PrivateProfile = Join-Path $RuntimeRoot "private\portfolio.json"
$CapitalIntent = Join-Path $RuntimeRoot "private\capital-intent.json"
$CapitalDecisionInputs = Join-Path $RuntimeRoot "private\capital-decision-inputs.json"
$CapitalSourceOutput = Join-Path $RuntimeRoot "private\capital-decision-source.json"
$CapitalSourceDir = Join-Path (Split-Path $CapitalSourceOutput -Parent) "sources"
$WakeOutput = Join-Path $RuntimeRoot "wake\latest.json"
$NoticeOutput = Join-Path $RuntimeRoot "notifications\latest.json"
$HandoffOutput = Join-Path $RuntimeRoot "gpt_handoff\latest.json"
$HandoffLedger = Join-Path $RuntimeRoot "gpt_handoff\ledger.jsonl"
$BridgeOutbox = Join-Path $RuntimeRoot "gpt_bridge\outbox"
$TransportBoundary = Join-Path $RuntimeRoot "gpt_bridge\transport_boundary"
$PostGptNotifications = Join-Path $RuntimeRoot "gpt_bridge\notifications"
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
$TreasuryValuationInputs = Join-Path $RuntimeRoot "treasury\valuation-inputs.json"
$IssuerCtArchive = Join-Path $RuntimeRoot "issuer_ct\archive"
$TreasuryCompanyCtInputs = Join-Path $RuntimeRoot "treasury\company-ct-inputs.json"
$PortfolioAllocationInputs = Join-Path $RuntimeRoot "private\portfolio-allocation-inputs.json"
$FixedIncomeInputs = Join-Path $RuntimeRoot "private\fixed-income-inputs.json"

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
New-Item -ItemType Directory -Force $PostGptNotifications | Out-Null
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
$env:PYTHONIOENCODING = "utf-8"

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

$IssuerAnnouncementReady = $false
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
    else {
        $IssuerAnnouncementReady = $true
    }
}

$RunnerArgs = @(
    "-m", "crt_radar.daily_evidence_runner",
    "--registry", $Registry,
    "--liquidation-snapshot", $PhoneL4,
    "--observation-db", $ObservationDb,
    "--output", $EvidenceOutput,
    "--private-profile", $PrivateProfile,
    "--observe-broker-capital",
    "--capital-source-output", $CapitalSourceOutput,
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

# Capture once inside the daily runner. Its immutable observation is reused for
# reconciliation, wake, Evidence Pack and full-decision source construction.
if (Test-Path -LiteralPath $CapitalIntent) {
    $RunnerArgs += @("--user-capital-intent", $CapitalIntent)
}
$FullCapitalDecisionRequested = Test-Path -LiteralPath $CapitalDecisionInputs
if ($FullCapitalDecisionRequested) {
    $EngineeringSourceSha = & git -C $RepoRoot rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $EngineeringSourceSha -notmatch '^[0-9a-f]{40}$') {
        throw "Engineering source commit cannot be verified"
    }
    $RunnerArgs += @(
        "--capital-decision-inputs", $CapitalDecisionInputs,
        "--source-main-sha", $EngineeringSourceSha
    )
}

if (
    $IssuerAnnouncementReady -and
    (Test-Path -LiteralPath $IssuerAnnouncementOutput)
) {
    $RunnerArgs += @(
        "--issuer-announcement-wake",
        $IssuerAnnouncementOutput
    )
    Write-Host "ISSUER_ANNOUNCEMENT_WAKE_RUNTIME_INPUT_READY" -ForegroundColor Green
}

if ($null -ne $AcceptanceWakePercentile) {
    $RunnerArgs += @(
        "--acceptance-wake-percentile",
        "$AcceptanceWakePercentile",
        "--confirm-acceptance-wake-override"
    )
    Write-Host (
        "ACCEPTANCE_WAKE_OVERRIDE_ONESHOT=" +
        "$AcceptanceWakePercentile"
    ) -ForegroundColor Yellow
}

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

if (Test-Path -LiteralPath $TreasuryValuationInputs) {
    $RunnerArgs += @("--treasury-valuation-inputs", $TreasuryValuationInputs)
}

# Read existing inputs only. Archive and direct company inputs are mutually exclusive.
if (Test-Path -LiteralPath (Join-Path $IssuerCtArchive "sec-disclosures\manifest.json")) {
    $RunnerArgs += @("--issuer-ct-archive", $IssuerCtArchive)
}
elseif (Test-Path -LiteralPath $TreasuryCompanyCtInputs) {
    $RunnerArgs += @("--treasury-company-ct-inputs", $TreasuryCompanyCtInputs)
}
if (Test-Path -LiteralPath $PortfolioAllocationInputs) {
    $RunnerArgs += @("--portfolio-allocation-inputs", $PortfolioAllocationInputs)
}
if (Test-Path -LiteralPath $FixedIncomeInputs -PathType Leaf) {
    $RunnerArgs += @("--fixed-income-inputs", $FixedIncomeInputs)
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

# Explicit local opt-in; no key or private runtime paths enter the GPT payload.
$CurrentHandoff = Get-Content -LiteralPath $HandoffOutput -Raw | ConvertFrom-Json
$CapitalWakeRequested = @($CurrentHandoff.semantic_descriptor.wake_sources) -contains "BROKER_CAPITAL_STATE"
if ($env:CRT_GPT_TRANSPORT_ENABLED -eq "1" -and -not $FullCapitalDecisionRequested -and -not $CapitalWakeRequested) {
        & $Python -m crt_radar.gpt_transport_worker `
        --outbox-dir $BridgeOutbox `
        --state-dir $TransportBoundary `
        --notification-state-dir $PostGptNotifications
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "GPT transport requires local attention; see boundary state."
    }
}

# Full-decision daily provider delivery is still separately approved and closed.
# Neither source readiness nor the existing Smoke opt-in grants that authority.

& $Python -m crt_radar.gpt_notification_boundary `
    deliver-pending `
    --transport-state-dir $TransportBoundary `
    --notification-state-dir $PostGptNotifications `
    --capital-source-dir $CapitalSourceDir `
    --capital-state $EvidenceOutput

if ($LASTEXITCODE -ne 0) {
    Write-Warning "GPT notification boundary requires local attention."
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
