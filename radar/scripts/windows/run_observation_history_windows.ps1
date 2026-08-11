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

if (-not (Test-Path $RadarRoot)) {
    throw "CRT Radar repo not found: $RadarRoot"
}
if (-not (Test-Path $Registry)) {
    throw "Source Registry not found: $Registry"
}

New-Item -ItemType Directory -Force (Split-Path $ObservationDb -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $EvidenceOutput -Parent) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $PhoneL4 -Parent) | Out-Null

$Python = Join-Path $RadarRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python not found. Run radar\scripts\windows\setup_windows.ps1 first."
    }
    $Python = $PythonCommand.Source
}

$env:PYTHONPATH = Join-Path $RadarRoot "src"

$RunnerArgs = @(
    "-m", "crt_radar.daily_evidence_runner",
    "--registry", $Registry,
    "--liquidation-snapshot", $PhoneL4,
    "--observation-db", $ObservationDb,
    "--output", $EvidenceOutput,
    "--phone-l4-freshness-path", $PhoneL4,
    "--phone-l4-max-age-seconds", "$PhoneL4MaxAgeSeconds"
)

& $Python @RunnerArgs
exit $LASTEXITCODE
