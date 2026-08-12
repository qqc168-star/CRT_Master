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
if (-not (Test-Path $ArchiveRoot -PathType Container)) {
    throw "ETP_PROSPECTIVE_CAPTURE_ARCHIVE_MISSING"
}

$Audit = Join-Path $Root "research\etp_capture_audit.py"
& $Python $Audit --archive-root $ArchiveRoot --require-complete-capture
if ($LASTEXITCODE -ne 0) {
    throw "ETP_PROSPECTIVE_CAPTURE_NOT_COMMISSIONED"
}
Write-Host "ETP_PROSPECTIVE_CAPTURE_AUDIT_PASS" -ForegroundColor Green
