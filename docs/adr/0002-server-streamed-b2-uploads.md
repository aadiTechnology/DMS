# ADR-0002: Server-streamed uploads on the native B2 API

**Status:** Accepted (Sprint 9). Product Owner direction: keep native `b2sdk`, no boto3/S3, no simulated-only adapter.

## Context
The ERP audit (section 9.4) recommended direct browser-to-B2 uploads. Checking the installed `b2sdk` 2.13.2 and the B2 native model shows a limit that matters for tenant isolation:
- `b2_get_upload_url` returns a token that is **bucket-wide and valid for 24 hours**; the uploader chooses the object name. A client holding one could write to any key in the shared DMS bucket (including another tenant's prefix, if the UUIDs were known), and the token cannot be shortened.
- `b2sdk`'s download-authorization call can be scoped to one key prefix and a short lifetime (we use it), but there is no equivalent for uploads. The S3-compatible API would solve this with per-key presigned PUT, but that is **not** a compelling enough reason to leave the native API, because the same goal is reachable without it.

## Decision
- The API receives the upload (streamed to temporary disk, never held in memory), computes SHA-1 and SHA-256 in one pass, validates the file, and calls `put_file`, which uploads with `b2sdk` (`upload_local_file`, which switches to multi-part automatically for large files and retries internally). Clients never receive any B2 credential or upload token.
- Consequences: all upload bytes pass through the API process (acceptable at the PRD scale of 100 concurrent users and 100 MB files; needs temporary disk), and the server computes the SHA-256 recorded per version (PRD STO-005) while B2 verifies the SHA-1 we send.
- The Sprint 8 `create_upload_target` and the local PUT route are removed so there is exactly one upload path.
- Downloads stay direct from B2: exact-key authorization, 5-minute default lifetime (max 15), `attachment` disposition forced, `private, no-store`.
- If load testing later shows the API is the bottleneck, direct upload can be reintroduced with documented mitigations (unguessable keys, recording the B2 file id, verifying on finalize), or by switching to S3 presigned uploads; both require a new ADR.

## Verified vs not verified
Verified: all adapter logic against `b2sdk.RawSimulator` (tests). Not verified: behavior against live Backblaze (needs the dedicated test bucket; see docs/testing/B2_INTEGRATION_TESTS.md).
