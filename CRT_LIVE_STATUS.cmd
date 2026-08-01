@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0radar\scripts\windows\live_shadow_gate_windows.ps1" -Mode Status
echo.
pause