# Starts everything needed to browse the demo: the local database container, the API and the web app.
# Demo only: uses the local demo database (dms_demo) and local file storage. Run from the repository root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$state = docker inspect -f "{{.State.Running}}" dms-postgres-1 2>$null
if ($state -ne "true") {
    Write-Host "Starting the database container (Docker Desktop must be running)..."
    docker start dms-postgres-1 | Out-Null
}
for ($i = 0; $i -lt 30; $i++) {
    if ((docker inspect -f "{{.State.Health.Status}}" dms-postgres-1) -eq "healthy") { break }
    Start-Sleep -Seconds 2
}

$api = "`$env:DATABASE_URL='postgresql+psycopg://dms:dms_dev@localhost:15432/dms_demo'; " +
       "`$env:STORAGE_LOCAL_DIR='$root\services\api\.storage\demo'; `$env:API_BASE_URL='http://localhost:8000'; " +
       "Set-Location '$root\services\api'; uv run uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $api -WindowStyle Minimized
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\apps\web'; npx vite --host 127.0.0.1" -WindowStyle Minimized

Write-Host "Waiting for the web app..."
for ($i = 0; $i -lt 40; $i++) {
    try { Invoke-WebRequest "http://127.0.0.1:5173/api/v1/health" -UseBasicParsing | Out-Null; break } catch { Start-Sleep -Seconds 2 }
}
Write-Host "Ready: http://localhost:5173  (accounts and password: docs\demo\DMS_DEMO_ACCESS.md)"
Start-Process "http://localhost:5173"
