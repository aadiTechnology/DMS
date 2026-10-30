# ADR-0001: Native b2sdk behind a StorageProvider interface

**Status:** Accepted by the product owner on 2026-10-30 ("proceed with recommendations").

## Context
PRD STO-002 says "private S3-compatible object storage". The only verified existing integration (ERP audit, `backblaze_blob_service.py`) is native B2 via `b2sdk`. Native B2 supports direct upload (upload URLs), large-file parts and download authorizations.

## Decision
- The first adapter uses native `b2sdk`, behind a `StorageProvider` interface so DMS logic never imports SDK types.
- This is a recorded deviation from the PRD wording, not a PRD change. An S3 adapter can be added later without domain changes.
- A new private DMS bucket and restricted key per environment. The ERP bucket and its (exposed) key are not reused.
- Object key: `tenants/{tenant_id}/documents/{document_id}/versions/{version_number}/{object_id}/{sanitized_filename}` (audit section 9.3). Keys are never authorization.
- Download URL TTL default 300 s (config maximum 900 s), scoped to the exact key. The residual window for already-issued URLs equals the TTL.
- Hosting target and region: **Unknown**, still open. Local development only until decided.
- PRD treated as accepted baseline v1.0 although its header says Draft.

## Consequences
B2 variable names in `.env.example` are provisional until Sprint 8/9 verifies them against a real test bucket.
