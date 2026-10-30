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
