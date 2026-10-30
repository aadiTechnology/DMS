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

## 3. Roles, permissions and audit (Sprint 4, implemented and tested)

- **Data-driven roles.** Tables `roles`, `role_permissions`, `user_role_assignments` (all tenant-isolated). Each new tenant is seeded with five system roles (`org_admin`, `department_manager`, `project_manager`, `reviewer`, `employee`) from templates in `app/core/permissions.py`; they are rows, not code, so they can be changed per tenant. Permission codes follow PRD 7.3 plus one addition, `admin.manage_organization` (organization structure management, not named in the PRD list). A test keeps the Python catalog identical to `packages/domain/src/permissions.ts`.
- **Permission = action ceiling.** A role grants what a person may *attempt*. Which documents it applies to (classification, ownership, department/project scope, explicit shares, workflow state, legal hold) is added by resource-level policy in the document sprints. Department/project-scoped role assignments arrive with the organization tables.
- **Evaluation.** `has_permission` is one indexed query over active membership, live assignments and active roles. Revoking a role or deactivating a membership takes effect on the next request. Endpoints declare `Depends(require_permission("..."))`; unauthenticated callers get 401, authenticated-but-unpermitted get 403.
- **Guard rails.** Assignments are idempotent; ids from another tenant answer 404; the last active org admin cannot be removed (409); revoked assignments are kept as history.
- **Audit.** `audit_events` is append-only (the app role has no UPDATE/DELETE) and tenant-isolated. Recorded now: tenant provisioning, role assigned/revoked, permission denied (403), login, logout, refresh-token reuse. Read via `GET /api/v1/audit-events` (needs `admin.view_audit`). `details` carries safe metadata only.
- **Measured:** permission evaluation including opening the tenant transaction: p50 5.2 ms, p95 6.5 ms (300 calls, 500 members x 2 roles, local Postgres 16, single client). Target is p95 <= 200 ms; production-scale and concurrent load not yet measured.
- **Not yet built:** failed-login audit (tenant unknown at that point), preview/download/upload audit (document sprints), privileged org-admin document access auditing (documents sprint), audit export and one-year retention job, custom role create/edit endpoints (admin UI sprint), department/project-scoped assignments.
- **Resolved in Sprint 5:** the unguarded Sprint 2 demo endpoint `GET /memberships` was removed; the employee directory now requires `admin.manage_organization`.

## 4. Organization structure (Sprint 5, implemented and tested)

- Departments (with optional parent and manager), branches, projects (optional manager), designations, employee profiles and project membership. All tenant-isolated; **no table grants DELETE** to the app role, so entities can only be deactivated (ORG-008). Existing assignments to a deactivated entity stay readable (ORG-005); new assignments to it are refused.
- Reading the structure is allowed to every member (upload forms and filters need it). Changing it, the employee directory and project members need `admin.manage_organization`. Every change is audited with changed-field names, not free text.
- Guards: unique name and code per tenant (409), department cycle check, manager and reporting manager must be active employees of the same tenant, ids from other tenants are indistinguishable from missing (404/422).
- Display name and work email live on `employee_profiles` so tenant code never reads the global `users` table.
- **Design decision:** department-manager and project-manager scope will be derived from `departments.manager_membership_id`, `projects.manager_membership_id` and project membership at document-policy time, instead of scoped role assignments. This avoids a second scoping mechanism; revisit if PRD 7.5 "scoped if delegated" needs per-person delegation.
- **Not yet built:** creating employees (invitations, Sprint 6), document associations (ORG-004, documents sprint), mandatory dimensions per category (ORG-003, taxonomy sprint), dashboard filters (ORG-007, dashboards sprint), a lightweight employee lookup for non-admins (needed by "owner/employee" metadata fields).

## 5. Onboarding and recovery (Sprint 6, implemented and tested)

- **Invitations.** An admin with `admin.manage_users` invites by email. The person's account, pending membership, profile, initial role and a single-use link (valid 7 days) are created in one transaction. Only a hash of the link token is stored. The link activates the membership; a **new** account sets its password there, an **existing** account (already in another organization) keeps its password, so an emailed link can never replace credentials.
- **Password reset.** Always answers the same; emails only real active accounts, at most one per minute per account. Using it sets the new password, clears lockout, ends all sessions, and is audited per organization. Passwords: 10-128 characters, no repetitive strings, must not contain the email name.
- **Self-registration.** Off by default per organization. When on, a public request (by organization slug) waits for admin approval; approval sends an invitation, rejection sends nothing. Public endpoints reveal nothing about which organizations or accounts exist.
- **Email.** Replaceable sender (`smtp` for any provider, `console` for development only, `outbox` for tests). Production refuses to start without `smtp`. Emails are queued during the request and sent only after the database commit (an automated test proves this ordering and caught a real flaw in the first design). Delivery is in-process, English only, no retry yet: retries, delivery history and localized templates arrive with the notifications and localization sprints.
- **Database roles.** Onboarding runs atomically by switching between `dms_auth` and `dms_app` inside one transaction (`acting_as`). `dms_auth` gained INSERT on `users` and access to `auth_tokens`; `dms_app` still cannot read either.
- **Not yet built:** Google/Microsoft sign-in, optional MFA, email verification beyond the invitation link, account-linking rules (Sprint 7); abuse controls beyond rate limits (captcha) for public registration.

## 6. Planned
RBAC roles/permissions, document-level policy (classification, ownership, grants, workflow state, legal hold), admin-privilege audit: Sprint 5 onward.
