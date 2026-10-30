# Implementation Status

Working context file. Updated at the end of every sprint.

## Decisions in force
- PRD v1.0 is the accepted baseline (header says Draft). See ADR-0001.
- Storage: native `b2sdk` behind a `StorageProvider` interface; new DMS bucket and key; 5-minute download URLs.
- Hosting and region: **Unknown / open**. Local dev only.
- Local Postgres: `docker compose up -d postgres` (host port 15432).
- Standing policy (2026-10-30): Product Owner authorizes autonomous sprint execution and local commits; approval needed for destructive/production/paid/PRD-scope/major-architecture changes; no push or deploy. D6 resolved: RLS adopted (Sprint 2).
- Open: D2 (B2 bucket/region facts), D7 (malware scanner), D8 (job queue), D9 (email provider), D11 (revocation SLA), D12 (SSO account linking). See `DMS_IMPLEMENTATION_BASELINE.md` section 11.

## Sprint 0: Repo scaffold (done)
**Changed:** monorepo skeleton: `services/api` (FastAPI health endpoint, settings), `packages/domain` (classification/state constants), CI workflow, `.gitignore`, `.env.example` (names only), ADR-0001. PRD and B2 audit copied to `docs/product` and `docs/audits`.

**Requirements touched:** STO-001 (default size constant), STO-008 (TTL bounds); no feature requirement completed.

**Tests executed (observed):**
| Command | Result |
|---|---|
| `uv run ruff check .` (services/api) | All checks passed |
| `uv run pytest -q` (services/api) | 3 passed, 1 deprecation warning (starlette TestClient/httpx) |
| `npm run build` (packages/domain, `tsc --noEmit`) | Succeeded |
| `npm test` (packages/domain, vitest) | 3 passed |

**Not verified:** CI workflow has not run on GitHub; no database, no B2 contact.

**Known issues:** `npm install` reported audit advisories (not triaged); starlette deprecation warning suggests `httpx2` for the test client.

Committed as `ac04630` on branch `dms-mvp-build`.

## Sprint 1: Database foundation (done)
**Changed:** `docker-compose.yml` (Postgres 16, host port **15432**; 5433 is used by another local process and 55432 is in a Windows reserved range), SQLAlchemy 2 base/models/session (`app/db`), Alembic (`services/api/migrations`, revision `0001`), `tenants`, `users`, `tenant_memberships` tables, CI Postgres service.

**Design notes:** UUID primary keys (`gen_random_uuid()`), `timestamptz` UTC, case-insensitive unique email (`lower(email)` index), `ON DELETE RESTRICT` on membership FKs (ORG-008), status CHECK constraints. Credentials and IdP links are deliberately not in `users` yet (Sprint 3/6). Migration directory is `migrations/` so it does not shadow the `alembic` package.

**Requirements touched:** foundation for ORG-008, I18N-005; Tenant/User/TenantMembership entities from PRD section 16. No feature requirement complete.

**Tests executed (observed, against local Postgres 16 container):**
| Command | Result |
|---|---|
| `uv run ruff check .` / `ruff format` | All checks passed |
| `uv run pytest -q` (services/api) | 12 passed, 1 warning (starlette/httpx deprecation) |

Covered: upgrade/downgrade/upgrade round trip, no drift between ORM models and migration, defaults and tz-aware timestamps, case-insensitive email uniqueness, one membership per tenant+user, user in multiple tenants, FK enforcement, no hard delete of referenced tenant, status CHECK. Each test uses a fresh throwaway database that is dropped afterwards.

**Not verified:** CI run on GitHub; behavior on PostgreSQL versions other than 16; production DB hosting (open).

**Next recommended:** Sprint 2, tenant isolation core (tenant-context dependency, tenant-scoped repository base, RLS, cross-tenant negative tests).

## Sprint 2: Tenant isolation core (done)
**Changed:** migration `0002` (role `dms_app`, RLS on `tenants` and `tenant_memberships`), `app/db/{rls,tenant_session,repository}.py`, `app/repositories/memberships.py`, `app/core/tenancy.py` (Principal, deny-by-default `get_principal`, `get_tenant_db`), `GET /api/v1/memberships` (tenant-scoped, paginated), `docs/architecture/AUTHORIZATION_MODEL.md`.

**Decision (simple terms):** every request runs inside a database "room" locked to one customer. Even if application code forgot a filter, the database itself refuses to show or change another customer's rows.

**Requirements touched:** tenant isolation (PRD section 4, 7.4, success metric "no cross-tenant access"); partial ORG-002 (membership listing only).

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 28 passed (16 new isolation tests incl. HTTP layer); `ruff check` and `ruff format` clean.

**Not verified:** CI on GitHub; behavior with a non-superuser owner role (production-like setup) and `GRANT dms_app` permissions there; performance of RLS predicate at scale.

**Next recommended:** Sprint 3, authentication I (email/password, JWT + refresh, revocation, lockout and rate limit), replacing the 401 stub in `get_principal`.

## Sprint 3: Authentication I (done)
**Changed:** migration `0003` (password/lockout columns on `users`, `user_sessions`, role `dms_auth`), `app/core/{security,ratelimit,config,tenancy}.py`, `app/services/auth.py`, `app/api/auth.py` (`POST /api/v1/auth/login|refresh|logout`, `GET /api/v1/auth/me`), real `get_principal` replacing the 401 stub. New deps: `argon2-cffi`, `pyjwt`.

**Decisions (simple terms):** passwords are stored only as strong one-way hashes; sign-in gives a 15-minute pass plus a rotating renewal token; the server checks on every request that the session and the person's membership are still valid, so removing someone locks them out immediately.

**Requirements touched:** PRD 15.1 (password hashing, lockout, rate limiting), 7.4 (revocation invalidates sessions), email/password login (App.A #13). Audit logging of auth events is NOT done (Sprint 5).

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 52 passed (24 new auth tests: login, enumeration resistance, lockout and recovery, multi-tenant choice, disabled/inactive, tampered/expired/unknown-session tokens, refresh rotation and theft detection, logout, instant revocation, hashed storage, role privileges, rate limit, production secret guard); `ruff` clean.

**Not verified:** login p95 <= 2 s (no load test yet; Argon2 default cost is a tunable); CI on GitHub; behavior behind a proxy (rate limit uses socket IP; trusted-proxy handling needed at deployment).

**Next recommended:** Sprint 4, organization structure (departments, branches, projects, designations, employee assignments; ORG-001..008).

## Sprint 4: RBAC engine and audit base (done) — reordered ahead of organization structure
**Why reordered:** organization-structure writes need permission checks, so RBAC and audit come first; organization structure is now Sprint 5, everything after shifts by one only in order, not in content.

**Changed:** migration `0004` (roles, role_permissions, user_role_assignments, append-only audit_events, RLS, grants), `app/core/permissions.py`, `app/services/{rbac,audit,tenants}.py`, `require_permission` in `app/core/tenancy.py`, endpoints `GET /api/v1/me/permissions`, `GET /api/v1/roles`, `GET|POST /api/v1/role-assignments`, `DELETE /api/v1/role-assignments/{id}`, `GET /api/v1/audit-events`; auth events now audited; TS `PERMISSIONS` contract.

**Decision (simple terms):** what people may do is stored as editable roles in the database, checked on every request, and every permission change, denial and sign-in is written to a tamper-resistant log the application cannot edit or delete.

**Requirements touched:** PRD 7.2-7.4 (data-driven RBAC, deny by default, revocation), success metric "100% of permission changes create audit events", partial audit (PRD 15.1). Not complete: resource-level policy (documents sprints).

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 68 passed (16 new RBAC/audit tests); `ruff` clean; `npm run build` ok, `npm test` 3 passed. Benchmark: permission evaluation p95 6.5 ms (see AUTHORIZATION_MODEL.md section 3).

**Not verified:** non-superuser owner role in production-like setup (provisioning sets tenant context to satisfy RLS, but only a superuser was exercised); CI on GitHub.

**Next recommended:** Sprint 5, organization structure with permission-checked writes (departments, branches, projects, designations, employee assignments; ORG-001..008), including scoped role assignments and gating `GET /memberships`.

## Sprint 5: Organization structure (done)
**Changed:** migration `0005` (departments, branches, projects, designations, employee_profiles, project_memberships; RLS; no DELETE grants), `app/services/org.py`, `app/api/org.py` (generic `/org/{kind}`, `/employees`, project members), IntegrityError -> 409 handler, `docs/architecture/API_REFERENCE.md`. Removed the Sprint 2 demo `/memberships` endpoint and `MembershipRepository` (the base `TenantRepository` is still tested via a test-local subclass). New dep: `email-validator`.

**Decision (simple terms):** the company's structure (departments, branches, projects, job titles) and each employee's place in it are stored per organization; items are switched off, never erased, so old documents keep making sense. Anyone can read the structure; only organization admins change it, and every change is logged.

**Requirements touched:** ORG-001, ORG-002 (audited; authorization effect arrives with document policy), ORG-005, ORG-006, ORG-008 done at data/API level. ORG-003, ORG-004, ORG-007 pending later sprints. No UI yet.

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 74 passed (11 new org tests); `ruff` clean.

**Not verified:** CI on GitHub; performance of directory listing at 500 employees (not measured); non-superuser owner role.

**Next recommended:** Sprint 6, authentication II and onboarding (employee invitations that create memberships and profiles, self-registration requests with admin approval, password set/reset via email token, Google/Microsoft SSO, optional MFA). Needs decisions already recorded as open: D9 email provider and D12 account-linking; I will build email behind an interface with a development console sender and propose provider/linking defaults.

## Sprint 6: Onboarding and recovery (done) — SSO and MFA split into Sprint 7
**Why split:** Google/Microsoft sign-in cannot be verified without real provider credentials, and the combined scope exceeded the sprint limits.

**Changed:** migration `0006` (tenant `slug` + `self_registration_enabled`, `auth_tokens`, `registration_requests`), `app/services/{email,onboarding}.py`, `app/api/onboarding.py`, public routes in `app/api/auth.py` (`accept-invite`, `forgot-password`, `reset-password`, `register`), `acting_as` role switching, email-after-commit in `get_tenant_db`, password policy, tenant slug at provisioning, EMAIL_* settings.

**Decision (simple terms):** people join by an emailed one-time link or by asking to join (admin approves); forgotten passwords are reset by a one-time emailed link that also signs the person out everywhere. The system never reveals whether an email or organization exists.

**Requirements touched:** invitations and self-registration with admin approval (PRD App.A #13), password reset (PRD 15.1, 17), WF-006-style no-duplicate delivery partly (retry/history pending). Not complete: SSO, MFA.

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 88 passed (14 new onboarding tests incl. email-after-commit proof, password never overwritten, tenant isolation, uniform public answers, single-use and expiry); `ruff` clean.

**Not verified:** SMTP delivery against a real server (only message construction tested); production database roles; CI on GitHub. Reminder: the dev `console` backend logs links, so use it only on a developer machine.

**Next recommended:** Sprint 7: Google/Microsoft sign-in (OIDC verification built against recorded test tokens, account-linking default: link only when the provider reports a verified email matching an existing active account) and optional TOTP MFA. Real provider app registrations will be needed from you before it can be used live.

## Sprint 7: SSO and optional MFA (done)
**Changed:** migration `0007` (`identity_links`, `mfa_recovery_codes`, MFA columns on `users`), `app/services/{sso,mfa}.py`, `app/api/{sso,mfa}.py`, login refactor (`finish_login`, MFA step), `activate_invitation` extracted for reuse. New deps: `pyjwt[crypto]`, `cryptography`.

**Decisions (simple terms):** "Sign in with Google/Microsoft" only works for people who already have an account in the system; it never creates one. Authenticator-app codes are optional per person, can't be reused, and are locked out like wrong passwords. Microsoft sign-in only trusts the email when Microsoft confirms the company owns that email domain.

**Requirements touched:** Google and Microsoft sign-in, optional MFA (PRD App.A #13, 15.1). Account-linking rule resolves open decision D12 (as recommended and unobjected).

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 113 passed (25 new: RFC 6238 vectors, replay/window, recovery codes, lockout, admin reset, encryption, SSO rejection matrix, link rebinding, Microsoft rules, multi-tenant choice, SSO invitation); `ruff` clean.

**Not verified:** live Google/Microsoft tokens and JWKS fetching (tests use locally generated RSA keys and patch the key lookup); behavior with real authenticator apps (RFC vectors only); CI on GitHub. **You must register OAuth apps** before SSO can be used live.

**Next recommended:** Sprint 8, storage abstraction (StorageProvider interface, local dev adapter, object-key scheme from ADR-0001, config validation). Sprint 9 then adds the real Backblaze adapter and needs a DMS-specific private test bucket and key from you (only "configured / not configured" status needed, never the values).

## Sprint 8: Storage abstraction (done)
**Changed:** `app/storage/{base,keys,local,__init__}.py` (interface, key scheme, local adapter, factory), dev-only `app/api/dev_storage.py`, storage settings with production validation (`config.py`), `docs/deployment/STORAGE_CONFIGURATION.md`, `docs/architecture/BACKBLAZE_STORAGE_ARCHITECTURE.md`. No new dependencies.

**Decision (simple terms):** the rest of the system will talk to "a storage" through one small set of operations, so Backblaze can be plugged in without changing document logic. Files get a fixed, safe address that includes the organization, document and version, and a stored file can never be replaced. In production the system refuses to start unless it is configured for Backblaze with a DMS-only bucket.

**Requirements touched:** STO-002 (private storage, via ADR-0001), STO-003 groundwork, STO-008 (short exact-key links), I18N-003 (Unicode file names). Not complete until Sprints 9-11.

**Tests executed (observed):** `uv run pytest -q` 149 passed (36 new storage tests: key scheme and sanitizing incl. Hindi/Marathi, invalid keys, round trip, immutability, size enforcement, signed-link binding/expiry/tampering, config rules, secret hiding); `ruff` clean. A test found and I fixed a real bug (invalid key inside a signed link caused a 500 instead of a 403).

**Not verified:** anything against Backblaze (no adapter yet); large-file streaming performance; CI on GitHub.

**Needed from you before Sprint 9:** a new private DMS-only B2 bucket + restricted key for dev/test (report only "configured"/"not configured"); see `docs/deployment/STORAGE_CONFIGURATION.md`. Also pending and urgent: rotate the exposed ERP key. If these are not ready I can still build and test the Backblaze adapter against a faked B2 API and leave live verification marked "not verified".

**Next recommended:** Sprint 9 (Backblaze adapter), or, if the bucket is not ready, Sprint 9b: taxonomy (categories, metadata schemas, tags, classifications) which has no storage dependency.

## Sprint 9: Backblaze adapter on native b2sdk (done; live connectivity NOT verified)
**Product Owner direction followed:** native `b2sdk` kept, no boto3/S3, dedicated DMS bucket and key only, ERP untouched, no simulated-only final adapter (the adapter is real; only its automated tests use the SDK's own `RawSimulator`).

**Changed:** `app/storage/backblaze.py` (adapter), `app/storage/base.py` (interface is now `put_file`/`stat`/`read_stream`/`create_download_url`/`delete`/`health`; `create_upload_target` removed), local adapter and dev router aligned, factory builds `BackblazeStorage`, dependency `b2sdk>=2.8,<3` (installed 2.13.2), ADR-0002, operations runbook, test doc, storage docs. The audit findings were checked against the installed SDK rather than repeating the audit.

**Decision to note (explained; not a change of direction):** the audit recommended direct browser-to-B2 uploads. In native B2 the upload token is bucket-wide and lasts 24 hours, so a client would hold a token able to write any key (ADR-0002). The API therefore streams uploads to disk, hashes once, and uploads with `b2sdk`; downloads remain direct via exact-key, 5-minute, attachment-forcing links. S3 presigned uploads would also solve this but were judged not worth leaving the native API.

**Improvements over the ERP code:** private bucket verified at connect; ERP bucket names refused; key capability and bucket-restriction check; immutable objects; SHA-1 verified by B2 and re-checked, SHA-256 recorded; file id recorded to detect substitution; all versions deleted and errors raised; sanitized errors; 5-minute links; `Cache-Control: private, no-store`.

**Requirements touched:** STO-002 (private storage, native B2 per ADR), STO-008 (short exact-key links), STO-005 groundwork (checksums recorded per version in the upload sprint). Not complete: upload workflow, metering, retention.

**Tests executed (observed):** `uv run pytest -q` 164 passed, 2 skipped (the live test, which needs your bucket); `ruff` clean. 14 adapter tests run the real adapter against `b2sdk.RawSimulator`.

**Findings while testing (fixed):** large (multi-part) files report their SHA-1 in file info, so the adapter reads it with `get_content_sha1()`. The simulator rejects uploads made with bucket-restricted keys, so least-privilege behavior can only be proven live.

**Not verified:** everything against real Backblaze (connect, `listBuckets` behavior with a bucket-restricted key, upload/download/delete, forced `b2ContentDisposition` on authorized links, SDK retry/timeouts, 100 MB memory and time).

**Needed from you to verify live:** a new private DMS test bucket plus a bucket-restricted key with the six capabilities in `docs/deployment/STORAGE_CONFIGURATION.md`, set through your own secret store; then run the command in `docs/testing/B2_INTEGRATION_TESTS.md` and tell me the PASS/FAIL text only. Also still pending: rotate the exposed ERP key.

**Next recommended:** taxonomy (categories, metadata schemas, tags, classifications), then the upload pipeline on top of `put_file`.

## Sprint 10: Taxonomy (done)
**Changed:** migration `0008` (`categories`, `category_versions`, `metadata_field_definitions`, `tags`, tenant flag `allow_employee_tags`, system-tag backfill), `app/services/{metadata,taxonomy}.py`, `app/api/taxonomy.py`, `require_any_permission`, system tags seeded at tenant provisioning, shared TypeScript constants (`METADATA_FIELD_TYPES`, `REQUIRED_DIMENSIONS`), `CATEGORY_MAX_DEPTH` setting, `docs/architecture/DATABASE_DESIGN.md`, API reference.

**Decision (simple terms):** an organization builds its own folder-like tree of categories. Each category carries rules (needs approval? which department/branch/project must be filled in? allowed file types, how long to keep, when to remind) and a list of extra fields to fill in (text, numbers, dates, choices, people, labels). Changing the rules or fields never alters old documents: it publishes a new numbered version, and old versions are locked in the database so they cannot be edited, even by mistake.

**Requirements touched:** CAT-001, CAT-002, CAT-004, TAG-001, TAG-002, TAG-003, TAG-004 (permission-aware search later), and the configuration half of CAT-003/ORG-003 (enforcement happens at upload), WF-001 (approval flag), retention policy settings (PRD 8.4). Classifications: four fixed levels per PRD 7.1 with a per-category default. Not complete: enforcing rules at upload, metadata values on documents, applying tags to documents, approval stages and reviewers (workflow sprint), expiry jobs.

**Tests executed (observed, local Postgres 16):** `uv run pytest -q` 210 passed, 2 skipped (live B2); `ruff` clean; `npm run build` and `npm test` pass. New: 24 metadata engine tests (all 14 types, rules, Unicode, defaults, required/draft handling), 20 taxonomy API tests (tree, depth/cycle/uniqueness, deactivation rules, policy validation, versions kept immutable at database level, permissions, tenant isolation, tags incl. policy and Unicode names).

**Notes:** employee tag requests that match an existing tag return that tag (no near-duplicates); duplicate detection beyond exact name (TAG-005) is deferred (P1). `tags.created_by` is kept for audit.

**Not verified:** performance with very large category trees (the tree is assembled in memory per request; fine for thousands of nodes, to be measured in hardening); CI on GitHub.

**Next recommended:** Sprint 11, document model and upload pipeline: pending upload records, streamed upload to disk with SHA-1/SHA-256, size/extension/MIME/signature checks, malware-scan hook (scanner choice D7 open: I will build the interface and a quarantine state, with a development scanner), metadata/dimension/classification validation against the category version, then `put_file`. Storage metering ledger follows.
