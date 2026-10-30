# Database Design (living document)

PostgreSQL 16, Alembic migrations in `services/api/migrations` (0001-0008 so far). Verified by tests: every migration upgrades and downgrades cleanly, and ORM models match the migrations (no drift).

## Conventions
- Opaque UUID primary keys (`gen_random_uuid()`); timestamps are `timestamptz` in UTC.
- Every tenant-owned table has `tenant_id`, row-level security (`FORCE`), and a policy tying rows to the request's tenant. Tenant code runs as role `dms_app`; authentication code as `dms_auth`.
- **Nothing is deleted:** `dms_app` has no DELETE on any table. Entities are deactivated (`status`). Immutable history tables (`category_versions`, `metadata_field_definitions`, `audit_events`) also have no UPDATE.
- Constraint names follow a naming convention; names over 63 characters get explicit shorter names.

## Tables
| Area | Tables |
|---|---|
| Identity and access | `tenants` (slug, self-registration and employee-tag flags), `users` (credentials, lockout, MFA), `tenant_memberships`, `user_sessions`, `auth_tokens`, `identity_links`, `mfa_recovery_codes`, `registration_requests` |
| Authorization and audit | `roles`, `role_permissions`, `user_role_assignments`, `audit_events` |
| Organization | `departments`, `branches`, `projects`, `designations`, `employee_profiles`, `project_memberships` |
| Taxonomy | `categories` (tree), `category_versions` (policy snapshot), `metadata_field_definitions`, `tags` |
| Documents | `documents` (title, category + category version, classification, lifecycle state, owner, validated metadata, optimistic `row_version`), `document_versions` (file name, declared/real type and size, SHA-1/SHA-256, object key, storage file id, scan status, status, reservation expiry, idempotency key), `document_associations` (one row per department/branch/project/employee link), `document_tags` |

## Taxonomy details
- `categories`: sibling names unique case-insensitively (expression index handles top-level nodes); maximum depth is a setting (`CATEGORY_MAX_DEPTH`, default 8).
- `category_versions`: one row per published configuration (approval, required organization dimensions, allowed extensions, retention, review interval, reminder days). `categories.current_version_number` points at the live one.
- `metadata_field_definitions`: typed definitions (14 field types) with validation rules and defaults stored as JSON, keyed by `(category_version_id, key)`. Values are validated by `app/services/metadata.py`; document values arrive with the documents sprint.
- `tags`: kinds `standard`, `employee`, `system`; names unique per tenant case-insensitively; system tags (Pending, Approved, Archived) are seeded for every tenant.

## Document version states
`pending` (reserved) -> `receiving` -> `available` | `quarantined` (virus) | `rejected` (failed validation); unfinished reservations become `abandoned`. Only `available` versions are usable. Version rows keep the object key and Backblaze file id so substitution can be detected.

## Planned
Sharing grants; approvals; retention and legal hold; notifications; storage-usage ledger; search index state.
