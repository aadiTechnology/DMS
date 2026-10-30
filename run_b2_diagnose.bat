@echo off
rem Prints only HTTP status codes for download-link variants (no keys, no content).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_b2_live_test.ps1" -Diagnose
set RC=%ERRORLEVEL%
pause
exit /b %RC%
