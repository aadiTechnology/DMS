# Backblaze B2 Operations Runbook

Never paste key values into tickets, chat or logs. Say only "configured / not configured".

## First-time setup (per environment)
1. Create a **private** bucket dedicated to the DMS (not an ERP bucket).
2. Create an application key restricted to that bucket with: listBuckets, listFiles, readFiles, writeFiles, deleteFiles, shareFiles.
3. Put `STORAGE_PROVIDER=backblaze`, `DMS_B2_KEY_ID`, `DMS_B2_APP_KEY`, `DMS_B2_BUCKET_NAME` in the environment's secret store.
4. Run the live test (docs/testing/B2_INTEGRATION_TESTS.md) against a **test** bucket before relying on it.

## Startup failures and what they mean
| Message (safe, no secrets) | Meaning | Fix |
|---|---|---|
| `Backblaze storage needs: ...` | A required setting is empty | Set the named variable |
| `DMS_B2_BUCKET_NAME must be a DMS-only bucket` | An ERP bucket name was used | Use the DMS bucket |
| `cannot use the configured bucket (Unauthorized/...)` | Key invalid, revoked, or not allowed for the bucket | Check the key, its bucket restriction and capabilities (including listBuckets) |
| `the DMS bucket must be private (allPrivate)` | Bucket is public | Set it to private in the B2 console; the app will not run against a public bucket |
| `storage ... failed (ClassName)` at runtime | A Backblaze call failed | See the logs for the class; transient errors are retried by the SDK; persistent ones need a look at Backblaze status |

## Credential rotation
1. Create the new key (same restrictions). 2. Update the secret store. 3. Restart the API (a 401 from B2 also makes the adapter reconnect on the next call). 4. Delete the old key in the B2 console. 5. Record the date.

## Suspected key exposure
Delete the key in the B2 console immediately, create a replacement, update the secret store, restart, then review the audit log and B2 access for the period. Keys committed to Git (see the ERP `BACKBLAZE_STATUS.txt`) count as exposed: rotate, then purge history.

## Not yet available (planned)
Orphan reconciliation job, usage reconciliation against B2, backup/restore drill, monitoring alerts. Until then, deletions only happen through approved lifecycle code paths; never delete objects by hand without checking the database first.
