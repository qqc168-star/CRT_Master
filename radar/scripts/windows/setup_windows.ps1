$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$Py = Get-Command py -ErrorAction SilentlyContinue
if (-not $Py) {
    throw "找不到 Windows Python Launcher（py）。請先安裝 Python 3.13，並勾選 Add Python to PATH。"
}

& py -3.13 --version
if ($LASTEXITCODE -ne 0) {
    throw "找不到 Python 3.13。請安裝 Python 3.13 後再執行。"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py -3.13 -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install --requirement requirements.txt
Write-Host "SETUP_PASS" -ForegroundColor Green
