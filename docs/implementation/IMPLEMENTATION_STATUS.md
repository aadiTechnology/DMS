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
