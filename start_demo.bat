@echo off
rem Starts the local DMS demo (database container, API and web app) and opens the browser.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_demo.ps1"
pause
