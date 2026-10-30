@echo off
rem Live Backblaze connectivity test for the DMS storage adapter (non-production bucket only).
rem Run from the repository root. You will be prompted for the values; nothing is saved.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_b2_live_test.ps1"
set RC=%ERRORLEVEL%
pause
exit /b %RC%
