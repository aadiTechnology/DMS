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

## 2. Planned
RBAC roles/permissions, document-level policy (classification, ownership, grants, workflow state, legal hold), admin-privilege audit: Sprint 5 onward.
