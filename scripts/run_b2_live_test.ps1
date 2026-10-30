# Runs the opt-in live Backblaze test against a dedicated NON-PRODUCTION bucket.
# Values are typed at the prompt, kept only in this process's environment, and never written to disk.
param([switch]$Diagnose)
$ErrorActionPreference = "Stop"

$keyId = Read-Host "Backblaze key ID (test key, restricted to the DMS test bucket)"
$secure = Read-Host "Backblaze application key (hidden)" -AsSecureString
$bucket = Read-Host "DMS test bucket name"
if (-not $keyId -or -not $bucket -or $secure.Length -eq 0) {
    Write-Host "FAIL: key ID, application key and bucket name are all required." -ForegroundColor Red
    exit 2
}
$appKey = [System.Net.NetworkCredential]::new("", $secure).Password

$env:DMS_B2_LIVE_TEST = "1"
$env:STORAGE_PROVIDER = "backblaze"
$env:DMS_B2_KEY_ID = $keyId
$env:DMS_B2_APP_KEY = $appKey
$env:DMS_B2_BUCKET_NAME = $bucket

$exit = 1
Push-Location (Join-Path $PSScriptRoot "..\services\api")
try {
    if ($Diagnose) { uv run python ..\..\scripts\diagnose_b2_download.py }
    else { uv run pytest -q -p no:cacheprovider -rs tests/test_storage_b2_live.py }
    $exit = $LASTEXITCODE
}
finally {
    Pop-Location
    foreach ($name in "DMS_B2_LIVE_TEST", "STORAGE_PROVIDER", "DMS_B2_KEY_ID", "DMS_B2_APP_KEY", "DMS_B2_BUCKET_NAME") {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $appKey = $null
}

if ($exit -eq 0) { Write-Host "`nRESULT: PASS" -ForegroundColor Green }
else { Write-Host "`nRESULT: FAIL (exit code $exit). Share the failing test name and error text, never the keys." -ForegroundColor Red }
exit $exit
