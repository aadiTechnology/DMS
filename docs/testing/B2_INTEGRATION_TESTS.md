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
