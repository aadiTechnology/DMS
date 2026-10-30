# Authorization Model

Living document. Sections are added as each layer is built.

## 1. Tenant isolation (Sprint 2, implemented and tested)

Three independent layers, so one mistake cannot expose another customer's data:

1. **Server-side tenant context.** The tenant comes from the authenticated principal (`app/core/tenancy.py: Principal`), never from a request parameter or header. Until real authentication arrives (Sprint 3), `get_principal` answers 401 for everyone (deny by default).
2. **Application filter.** Every tenant-owned query goes through `TenantRepository` (`app/db/repository.py`), which filters by `tenant_id`, stamps `tenant_id` on inserts (a client-supplied value is ignored), caps page size at 200, and returns "not found" for other tenants' rows so existence is not revealed.
3. **Database row-level security.** Each request transaction runs as the unprivileged role `dms_app` with `app.tenant_id` set locally (`app/db/tenant_session.py`). Tables have `ENABLE` + `FORCE ROW LEVEL SECURITY` with a `tenant_isolation` policy (`app/db/rls.py`). With no tenant context the role sees zero rows. `dms_app` has no DELETE on memberships (deactivate instead, PRD ORG-008) and no access to the global `users` table yet.

**Rule for every future tenant-owned table:** add `tenant_id`, call `enable_tenant_rls_sql(table)` in its migration, grant only needed privileges to `dms_app`, and subclass `TenantRepository`.

**Verified by tests** (`tests/test_tenant_isolation.py`): own-tenant visibility, hand-written cross-tenant query returns nothing, no-context returns nothing, cross-tenant insert/update/move blocked, delete denied, context does not leak across pooled transactions, repository scoping, HTTP endpoint ignores client-supplied tenant, 401 when unauthenticated.

**Known limits:** the app connects as the owner role and switches with `SET LOCAL ROLE`; a code path that opens a plain session instead of `tenant_session` would bypass RLS (owner/superuser). Rule: all request code uses `get_tenant_db`. Platform-operator access will use a separate, audited path. Search indexes, caches, exports, object keys and job context carry the same tenant rule when those features are built.

## 2. Authentication and sessions (Sprint 3, implemented and tested)

- **Login:** email + password (Argon2id hashes, never stored in clear). Unknown user, wrong password, locked, disabled and no-membership all return the same `401 Invalid email or password` and spend the same hashing time, so attackers learn nothing about which accounts exist.
- **Lockout:** 5 consecutive failures lock the account for 15 minutes (configurable); success resets the counter. Plus an in-process rate limit on login/refresh (30/min/IP). *Limit:* the rate limiter is per process; move to a shared store when workers/hosting are chosen.
- **Tenant choice:** a user in several organizations gets `409 tenant_required` with their own tenant list and picks one; a session is bound to exactly one tenant.
- **Tokens:** access token is a signed JWT valid 15 minutes (carries user, tenant, session ids). Refresh tokens are random, stored only as SHA-256 hashes, valid 14 days, and **rotate on every use**. Replaying an already-used refresh token is treated as theft and revokes the whole session.
- **Immediate revocation (PRD 7.4):** every request checks the session row plus active user, active membership and active tenant. Logout, disabling a user, or deactivating a membership blocks existing access tokens on their next request, not at expiry.
- **Database roles:** `dms_auth` (users, sessions, cross-tenant read of memberships/tenants, for login only) and `dms_app` (tenant work, no access to users or sessions) are separate, so request code cannot read other people's credentials.
- **Production guard:** the app refuses to start with `ENVIRONMENT=production` and a default or short `SECRET_KEY`.
- **Not yet built (later sprints):** password reset and email verification, invitations and self-registration approval (Sprint 6), Google/Microsoft SSO and optional MFA (Sprint 6), audit events for login/logout (Sprint 5, PRD requires them), refresh-token cleanup job.

## 3. Planned
RBAC roles/permissions, document-level policy (classification, ownership, grants, workflow state, legal hold), admin-privilege audit: Sprint 5 onward.
