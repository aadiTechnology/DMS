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
| GET `/auth/sso/providers` | none | Configured providers and their public client ids |
| POST `/auth/sso/{google\|microsoft}` | none (ID token) | Body: `id_token`, optional `nonce`, `tenant_id`, `invite_token`. Existing accounts only. 401 `Sign-in failed` for every rejection; 404 if the provider is not configured; 409 `tenant_required` |
| GET `/auth/mfa` | signed in | Is two-step verification on |
| POST `/auth/mfa/setup`, POST `/auth/mfa/enable` | signed in | Get a secret + `otpauth_uri`; confirm with a code, receive 8 one-time recovery codes (shown once) |
| POST `/auth/mfa/disable` | signed in | Needs password and a code or recovery code |
| POST `/employees/{membership_id}/mfa/reset` | admin.manage_users | Lost-device recovery; audited as privileged |

| GET `/metadata/field-types` | signed in | The 14 supported metadata field types |
| GET `/categories?status=` | signed in | Flat list with `path` ("HR > Employee Records") and `depth`, sorted by path |
| POST `/categories` | admin.manage_taxonomy | Create with `name`, `parent_id`, `default_classification`, and optionally `policy` + `fields` (becomes version 1) |
| GET `/categories/{id}?version=` | signed in | Category plus a version's policy and fields (default: current) |
| PATCH `/categories/{id}` | admin.manage_taxonomy | Rename, move (`parent_id`, null = top level), default classification, `status`. No DELETE |
| GET `/categories/{id}/versions` | signed in | All versions, newest first |
| POST `/categories/{id}/versions` | admin.manage_taxonomy | Publish a new immutable version (`policy` + `fields`); documents keep the version they were created under |
| GET `/tags?kind=&status=` | signed in | Standard, employee and system tags |
| POST `/tags` | standard: admin.manage_taxonomy; employee: upload or edit-metadata right + org policy | 201 created, 200 if a tag with that name already exists (returned, no duplicate) |
| PATCH `/tags/{id}` | admin.manage_taxonomy | Rename or switch on/off; system tags (Pending, Approved, Archived) cannot be changed |
| GET/PUT `/tags/policy` | admin.manage_taxonomy | `allow_employee_tags` (default true) |

Category policy fields: `approval_required`, `required_dimensions` (department, branch, project, employee), `allowed_extensions`, `retention_days`, `review_interval_days`, `expiry_action` (archive only), `reminder_days`. Metadata field rules per type are described at the top of `app/services/metadata.py`. Field errors answer `422 {"detail": {"fields": {"<key>": "<message>"}}}`.

| POST `/documents/uploads` | document.upload | Step 1, reserve an upload. Body: `category_id`, `filename`, `content_type`, `size_bytes`, optional `title`, `classification` (not below the category default), `owner_membership_id`, `associations` (`department`/`branch`/`project`/`employee` lists), `tag_ids`, `metadata`, `comment`. Optional `Idempotency-Key` header. 201 new, 200 replay. 415 type, 413 size, 422 rules/metadata (`{"fields": {...}}`) |
| PUT `/documents/uploads/{version_id}/content` | document.upload (uploader only) | Step 2, raw file bytes as the body with `Content-Length` equal to the declared size. 200 `available`; repeat is harmless. 422 `signature_mismatch`/`malware_detected`, 400 `size_mismatch`, 409 wrong state, 410 reservation expired, 502 storage error and 503 `scan_unavailable` (both retryable) |
| GET `/documents/mine` | signed in | Documents you uploaded or own, including pending ones |
| GET `/documents/{id}` | document.view_metadata + access policy | Metadata, versions, associations, tags and `access: {preview, download}` flags. 404 if you may not see it (never reveals existence) |
| GET `/documents/{id}/versions/{n}/download-url` | document.download + access policy | `{url, expires_in_seconds, filename, content_type, size_bytes}`; link forces download; audited; `Cache-Control: no-store` |
| GET `/documents/{id}/versions/{n}/preview-url` | document.preview + access policy | Same, inline; 415 `preview_unavailable` for anything but PDF, PNG, JPEG |

| POST `/documents/{id}/versions/uploads` | document.upload_version + owner, uploader (not for Highly Confidential non-owners) or privileged admin | Reserve a new version. Body: `filename`, `content_type`, `size_bytes`, **`based_on_version`** (newest number you saw), optional `comment`; optional `Idempotency-Key`. Send bytes to the returned `upload_url`. 409 `stale` (with `latest_version`) if someone added a version meanwhile, 409 if an upload is in progress or a version awaits approval, 409 for archived documents |
| GET `/documents/{id}/versions` | document.view_metadata + access policy | Version history, newest first. Unpublished versions (awaiting approval, rejected, failed) are shown only to their uploader, the owner and privileged admins |
| POST `/documents/{id}/versions/{n}/restore` | document.upload_version + same rule | Body `{"based_on_version": n}`. Creates a NEW version from a server-side copy of version `n` (history preserved). Needs download rights on `n` |
| PATCH `/documents/{id}` | document.edit_metadata + same rule | Body: **`row_version`** (required), optional `title`, `metadata` (partial; null removes a value), `tag_ids` (replaces non-system tags). 409 `stale` with the current `row_version` if the document changed since you loaded it. Metadata is checked against the schema version the document was created under |
| GET `/search` | document.view_metadata | Search and list documents you may see. Text `q` (up to 8 words, each matched as a prefix, all must match in title/file name/searchable metadata/tags or extracted content); filters `category_id` (+ `include_subcategories`), `department_id`, `branch_id`, `project_id`, `employee_id`, `owner_id`, `uploader_id`, `status`, `classification`, `tag_id`, `date_field` (created, modified, uploaded) with `date_from`/`date_to`; `sort` relevance, date or title; `limit` 1-100, `offset`. Returns `items`, `total` and `facets` (category, classification, status, department) counted only over visible documents. Rate limited per user. Without `q` it is the filtered document list |
| GET `/search/index/status` | admin.manage_organization | Extraction counts (pending, processing, indexed, failed, unsupported) and failures with reason codes (no titles or content) |
| POST `/search/index/retry`, POST `/search/index/run` | admin.manage_organization | Re-queue failed extractions; process queued extractions now |

Login with MFA on: `POST /auth/login` answers `401 {"detail":{"code":"mfa_required"}}` after a correct password; resend with `mfa_code` (authenticator or recovery code). Wrong codes count toward lockout.

Planned groups follow the PRD section 17 list as each sprint ships.
