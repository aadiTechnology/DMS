# Storage Configuration

Names only. Never put real values in this repository, in chat, in logs or in screenshots. Backend only: nothing here may use a `VITE_`, `EXPO_PUBLIC_` or other client-exposed prefix.

| Variable | Purpose | Secret? | Used in | Source |
|---|---|---|---|---|
| `STORAGE_PROVIDER` | `local` (development/tests) or `backblaze`. Production **must** be `backblaze`; the app refuses to start otherwise | No | all | env / deployment settings |
| `STORAGE_LOCAL_DIR` | Folder for the local adapter (default `.storage`, git-ignored) | No | dev/test only | env |
| `API_BASE_URL` | Public base URL of the API; used to build local signed URLs | No | dev/test | env |
| `DMS_B2_KEY_ID` | Backblaze application key id of the **DMS** key | Treat as sensitive | production, staging | secret store |
| `DMS_B2_APP_KEY` | Backblaze application key secret (held as a protected value, hidden from logs and `repr`) | **Yes** | production, staging | secret store |
| `DMS_B2_BUCKET_NAME` | The DMS-only private bucket for this environment | No | production, staging | env |
| `DMS_DOWNLOAD_URL_TTL_SECONDS` | Lifetime of download links (default 300, allowed 30-900) | No | all | env |
| `DMS_MAX_UPLOAD_BYTES` | Maximum file size (default 104857600 = 100 MB) | No | all | env |

Status: the Backblaze variable names are provisional until Sprint 9 verifies them against a real test bucket.

## Rules enforced by the application at startup (tested)
- `ENVIRONMENT=production` requires `STORAGE_PROVIDER=backblaze`.
- `backblaze` requires all three `DMS_B2_*` values.
- The bucket name may not be one of the existing ERP buckets (`attachmentserp-b2`, `aaditech-erp-test-v2`).
- The local-storage download/upload route (`/api/v1/dev-storage`) is mounted only for `local` storage outside production.

## What you must provide before Sprint 9 (tell me only "configured" / "not configured")
1. A **new private** bucket for development/test, and later one each for staging and production. Never reuse an ERP bucket.
2. An application key per environment, restricted to that one bucket, with only the capabilities the DMS uses (list/read/write/delete files; no key management).
3. The key stored only in your secret store (local untracked `.env`, or the hosting platform's encrypted settings), never in Git.
4. Rotate the ERP key that is committed in the ERP repository (`BACKBLAZE_STATUS.txt`); it must not be reused anywhere.
