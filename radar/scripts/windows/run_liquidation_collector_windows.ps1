param(
    [string]$RepoRoot = "$env:USERPROFILE\CRT_EvidenceRunner",
    [string]$RuntimeRoot = "$env:USERPROFILE\CRT_Runtime",
    [int]$MaxRuntimeSeconds = 0
)

$ErrorActionPreference = "Stop"

if ($MaxRuntimeSeconds -lt 0 -or ($MaxRuntimeSeconds -gt 0 -and $MaxRuntimeSeconds -lt 300)) {
    throw "MaxRuntimeSeconds must be 0 for continuous duty or at least 300."
}

$RadarRoot = Join-Path $RepoRoot "radar"
$Registry = Join-Path $RadarRoot "CONFIG\SOURCE_REGISTRY_V1.2.json"
$CollectorRuntime = Join-Path $RuntimeRoot "l4_collector"
$Snapshot = Join-Path $RuntimeRoot "incoming\l4\latest.json"

if (-not (Test-Path $Registry)) {
    throw "Source Registry not found: $Registry"
}

New-Item -ItemType Directory -Force $CollectorRuntime | Out-Null
New-Item -ItemType Directory -Force (Split-Path $Snapshot -Parent) | Out-Null

$Python = Join-Path $RadarRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python not found."
    }
    $Python = $PythonCommand.Source
}

$env:PYTHONPATH = Join-Path $RadarRoot "src"

$CollectorArguments = @(
    "-m",
    "crt_radar.liquidation_collector",
    "collect",
    "--registry",
    $Registry,
    "--runtime-root",
    $CollectorRuntime,
    "--snapshot-path",
    $Snapshot
)
if ($MaxRuntimeSeconds -gt 0) {
    $CollectorArguments += @("--max-runtime-s", $MaxRuntimeSeconds)
}

& $Python @CollectorArguments

exit $LASTEXITCODE
