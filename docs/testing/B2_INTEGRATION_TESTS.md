# B2 Integration Tests

## What runs automatically (no network, no credentials)
`tests/test_storage_backblaze.py` runs the real adapter against `b2sdk.RawSimulator` (the SDK's official test double): connection and private-bucket checks, safe failures without leaking secrets, put/stat/read/delete, immutability, checksum rejection, an ~11 MB file (the simulator took the multi-part path), key validation before any call, substitution detection by file id, deletion of all versions, delete failures raised, exact-key short-lived download links with forced attachment and Unicode names, capability reporting. Last run: 14 passed.

These prove our logic. They do **not** prove live Backblaze behavior.

## Opt-in live test (needs your test bucket)
`tests/test_storage_b2_live.py` is skipped unless `DMS_B2_LIVE_TEST=1`. Use a dedicated **non-production** bucket and a bucket-restricted key; set the values from your own secret store (never in chat or Git):

```powershell
$env:DMS_B2_LIVE_TEST = "1"
$env:STORAGE_PROVIDER = "backblaze"
$env:DMS_B2_KEY_ID = "<test key id>"
$env:DMS_B2_APP_KEY = "<test application key>"
$env:DMS_B2_BUCKET_NAME = "<dms test bucket>"
cd services/api; uv run pytest tests/test_storage_b2_live.py -v
```
It checks: connection, bucket private, key capabilities sufficient and bucket-restricted, round trip, exact-version read, overwrite refused, a real signed download (attachment disposition), the same URL without its token is denied, and cleanup of everything it created (random tenant prefix). Status: **NOT RUN** (no live bucket configured yet).

## What the live test cannot cover yet
Performance and memory of 100 MB transfers, SDK retry and timeout behavior under failure, B2 lifecycle/versioning settings, key rotation, and storage-usage reconciliation. These need a staging environment and are tracked for the hardening sprint.

## Running from the repository root (Windows)
`run_b2_live_test.bat` prompts for the key ID, application key (hidden) and bucket name, runs the live test and prints PASS or FAIL; nothing is written to disk. `run_b2_diagnose.bat` prints only HTTP status codes for download-link variants.

## First live run (observed)
Connection, privacy, capability and key-restriction checks passed against a real private bucket, as did upload, stat, read and the no-overwrite check. The download link returned 401 `bad_auth_token`: Backblaze only accepts `b2ContentDisposition` / `b2CacheControl` on a link when the download token was issued with the same values (the simulator does not enforce this). Fixed by issuing the token through the raw `b2_get_download_authorization` call with those values; regression test added. **Re-run pending.**
