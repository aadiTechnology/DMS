# API Reference (living document)

Base path `/api/v1`. Interactive OpenAPI: `/api/v1/openapi.json`. Errors use `{"detail": ...}`. Every endpoint except `health` and `auth/login|refresh` needs `Authorization: Bearer <access token>`. The tenant always comes from the token's session, never from the request. Lists are paginated with `limit` (1-200, default 50) and `offset`.

Status codes: 401 not signed in / session revoked, 403 signed in but lacking the permission, 404 not found (also used for other organizations' ids), 409 conflict, 422 invalid input, 429 rate limited.

| Method and path | Permission | Purpose |
|---|---|---|
| GET `/health` | none | Liveness |
| POST `/auth/login` | none | Email, password, optional `tenant_id` -> tokens. 409 `tenant_required` lists the user's organizations |
| POST `/auth/refresh` | none | Rotate refresh token |
| POST `/auth/logout` | signed in | Revoke session |
| GET `/auth/me` | signed in | Current user and tenant |
| GET `/me/permissions` | signed in | My effective permission codes |
| GET `/roles` | admin.manage_users | Roles with their permissions |
| GET/POST `/role-assignments`, DELETE `/role-assignments/{id}` | admin.manage_users | Assign/revoke roles (idempotent; last admin protected) |
| GET `/audit-events` | admin.view_audit | Filter by `action`, `since` |
| GET `/org/{kind}` | signed in | List departments, branches, projects or designations (`kind`); filter `status` |
| POST `/org/{kind}` | admin.manage_organization | Create. Fields: name, code (not designations), parent_id (departments), manager_membership_id (departments, projects) |
| PATCH `/org/{kind}/{id}` | admin.manage_organization | Edit or set `status` active/inactive. No DELETE exists by design (PRD ORG-008) |
| GET `/employees`, GET `/employees/{membership_id}` | admin.manage_organization | Directory; filters `department_id`, `branch_id`, `membership_status` |
| PUT `/employees/{membership_id}/profile` | admin.manage_organization | Create/update profile (only sent fields change; `full_name` required first time) |
| GET `/projects/{id}/members` | admin.manage_organization | Current project members |
| PUT/DELETE `/projects/{id}/members/{membership_id}` | admin.manage_organization | Add/update member (re-adding clears end date); DELETE ends today, history kept |
| POST `/auth/accept-invite` | none (single-use token) | Set password (new accounts only) and activate the membership; returns tokens. Invalid/expired/used/revoked links all answer 400 |
| POST `/auth/forgot-password` | none | Always 202 with the same text; emails a link only for an active account (1 per minute per account) |
| POST `/auth/reset-password` | none (single-use token) | New password; clears lockout; signs the person out everywhere |
| POST `/auth/register` | none | Request to join an organization (`tenant_slug`, email, full_name). Always 202 with the same text |
| POST `/invitations`, GET `/invitations`, POST `/invitations/{membership_id}/resend`, DELETE `/invitations/{membership_id}` | admin.manage_users | Invite by email (optional `role_id`, default employee), list pending, resend (older links stop working), revoke |
| GET `/registration-requests?status=`, POST `/registration-requests/{id}/approve` or `/reject` | admin.manage_users | Review self-registration; approve sends an invitation |
| GET/PATCH `/tenant/settings` | admin.manage_organization | Organization slug (read) and `self_registration_enabled` (default off) |

Planned groups follow the PRD section 17 list as each sprint ships.
