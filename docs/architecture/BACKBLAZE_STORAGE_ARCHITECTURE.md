# Storage Architecture

Status: interface, key scheme, local adapter, configuration safety (Sprint 8) and the Backblaze adapter (Sprint 9) are implemented and tested against the b2sdk simulator. **Live Backblaze behavior is not yet verified.** The upload workflow, download authorization and metering are later sprints.

## Principle
PostgreSQL holds metadata and authorization state; object storage holds only the bytes. DMS business logic talks to a small `StorageProvider` interface (`app/storage/base.py`) and never imports a vendor SDK (ADR-0001).

## Interface (`app/storage/base.py`)
`put_file`, `stat`, `read_stream`, `create_download_url`, `delete`, `health`. Contract: private objects; short-lived exact-key links issued only after the API's own authorization; keys validated before every call; no overwrite of existing objects; checksum verified on upload; errors raised (never swallowed) and free of credentials or signed URLs.

## Object keys (`app/storage/keys.py`)
`tenants/{tenant_id}/documents/{document_id}/versions/{version_number}/{object_id}/{filename}`. Ids are server-generated UUIDs; filenames are sanitized but keep Unicode (Hindi/Marathi). Providers validate the key first, so a client-supplied key can never reach storage. Prefixes are hygiene, not security: isolation is enforced by authorization and database rules.

## Backblaze adapter (`app/storage/backblaze.py`, native `b2sdk` 2.13.x, ADR-0001 and ADR-0002)
- **Reused from the ERP integration:** server-side credentials only, in-memory `b2sdk` account info, `authorize_account("production", ...)`, bucket by name, download authorization tokens.
- **Improved:**
  - Connects once per process (reused client) and verifies at connect time that the bucket is **private**; it refuses to run otherwise (the ERP never verified this).
  - Refuses ERP bucket names at startup; checks the key's capabilities and bucket restriction (`verify_capabilities`).
  - Upload: streamed by the API, SHA-1 verified by B2, size and SHA-1 re-checked afterwards (a failed check deletes the new version), SHA-256 stored in file info, `Cache-Control: private, no-store`, an existing key is refused (`ObjectExists`).
  - Records the B2 `file_id`; `stat` exposes it so a substituted newer version is detectable, and `read_stream(file_id=...)` reads the exact version.
  - Download link: scoped to the exact key, lifetime 1-900 s (default 300 s, unlike the ERP's 60 minutes), `attachment` disposition forced, no-store.
  - Delete removes every version of exactly that key and raises on failure (the ERP swallowed errors).
  - Errors expose only the operation and exception class, never details, keys or URLs; credentials are never logged.
- **Transfers:** uploads go through the API (ADR-0002) because native B2 upload tokens are bucket-wide and last 24 hours; downloads go direct from B2 via the authorized link. Large files use `b2sdk`'s multi-part path automatically (observed in the simulator for an 11 MB file; live behavior not verified). Retries and timeouts are the SDK defaults (not tuned or verified).
- **Residual risk:** an issued download link works until it expires (at most 15 minutes, default 5) even if access is revoked meanwhile. This is a documented trade-off (PRD 20.2 open decision on revocation consistency).

## Local adapter (development and tests only)
Same contract on disk with signed GET links bound to one key, one method and an expiry; atomic exclusive writes; refused in production.

## Still to build
Pending-upload records, spooling/validation/malware scan and finalize (upload sprint); permission-checked download endpoints and access audit; storage metering ledger; retention/legal-hold deletion jobs; orphan reconciliation. Operations: `docs/operations/B2_OPERATIONS_RUNBOOK.md`. Tests: `docs/testing/B2_INTEGRATION_TESTS.md`.
