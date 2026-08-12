[CmdletBinding()]
param(
    [string]$ArchiveRoot = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "PYTHON_VENV_MISSING_RUN_SETUP_WINDOWS_PS1"
}
if (-not $ArchiveRoot) {
    $ArchiveRoot = Join-Path $Root "runtime\etp_prospective_capture"
}
New-Item -ItemType Directory -Force -Path $ArchiveRoot | Out-Null

$Runner = Join-Path $Root "research\prospective_capture.py"
$Audit = Join-Path $Root "research\etp_capture_audit.py"
& $Python $Runner --archive-root $ArchiveRoot
$RunnerExit = $LASTEXITCODE
& $Python $Audit --archive-root $ArchiveRoot
$AuditExit = $LASTEXITCODE
if ($AuditExit -ne 0) {
    throw "ETP_PROSPECTIVE_CAPTURE_AUDIT_BLOCKED"
}
if ($RunnerExit -ne 0) {
    throw "ETP_PROSPECTIVE_CAPTURE_CYCLE_REQUIRES_ATTENTION"
}
Write-Host "ETP_PROSPECTIVE_CAPTURE_CYCLE_RECORDED" -ForegroundColor Green
