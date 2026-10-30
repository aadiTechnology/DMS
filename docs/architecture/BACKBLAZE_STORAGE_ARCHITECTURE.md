# Storage Architecture

Status: interface, key scheme, local adapter and configuration safety are implemented and tested (Sprint 8). The Backblaze adapter, upload workflow and download authorization are later sprints (9-11) and are described here only as intent.

## Principle
PostgreSQL holds metadata and authorization state; object storage holds only the bytes. DMS business logic talks to a small `StorageProvider` interface (`app/storage/base.py`) and never imports a vendor SDK (ADR-0001).

## Interface (verified in code)
`create_upload_target`, `stat`, `read_stream`, `create_download_url`, `delete`, `health`. Contract: private objects; short-lived exact-key links issued only after the API's own authorization; keys validated before every call; no overwrite of existing objects; errors raised, never swallowed, and free of credentials or signed URLs.

## Object keys (`app/storage/keys.py`)
`tenants/{tenant_id}/documents/{document_id}/versions/{version_number}/{object_id}/{filename}`
- All ids are server-generated UUIDs; the filename is sanitized (no separators or control characters, no traversal, no Windows reserved names, length bounded) but keeps Unicode, so Hindi and Marathi names work.
- Providers call `assert_valid_key` first, so a key supplied by a client can never reach storage.
- Prefixes are hygiene, not security: tenant isolation is enforced by authorization and database rules.

## Local adapter (development and tests only)
Same contract on disk: signed links bound to one key, one method and an expiry; upload size must equal the authorized size; uploads stream to a temporary file and are published atomically; an existing object is never overwritten; partial files are removed; responses carry `Cache-Control: private, no-store` and `nosniff`. Refused in production by configuration validation.

## Decisions made in this sprint
- Single-request uploads (maximum 100 MB) are enough for the PRD limit, so no multipart-upload code is built; STO-009's "abandoned multipart" cleanup reduces to cleaning up abandoned pending uploads (upload sprint). Revisit if the file limit is raised.
- Integrity: providers report SHA-1 (what Backblaze natively exposes). The upload sprint will additionally compute and store SHA-256 in a worker by streaming the object (`read_stream`).

## Planned (not yet built)
Backblaze adapter (Sprint 9), pending-upload records, malware scan, finalize step (Sprint 10), permission-checked download URLs and access audit (Sprint 11), orphan reconciliation and operations runbook (hardening).
