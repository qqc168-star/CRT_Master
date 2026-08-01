$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "尚未建立 .venv。請先執行 setup_windows.ps1。"
}
$env:PYTHONPATH = Join-Path $Root "src"
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "UNIT_TEST_FAIL" }
& $Python -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { throw "COMPILE_FAIL" }
& $Python scripts\validate_program_registry.py
if ($LASTEXITCODE -ne 0) { throw "REGISTRY_VALIDATION_FAIL" }
& $Python scripts\assert_read_only_surface.py
if ($LASTEXITCODE -ne 0) { throw "READ_ONLY_SURFACE_FAIL" }
& $Python -m json.tool CONFIG\SOURCE_REGISTRY_V1.2.json | Out-Null
& $Python -m json.tool CONFIG\LIVE_SHADOW_POLICY_V1.json | Out-Null
Write-Host "OFFLINE_TEST_PASS" -ForegroundColor Green
