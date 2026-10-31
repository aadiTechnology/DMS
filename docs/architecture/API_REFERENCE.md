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

| GET `/approvals/queue` | signed in | Reviews waiting for your decision, oldest first (`limit`, `offset`) |
| GET `/approvals/pending` | document.access_all | Every pending review including ones with nobody assigned (`reviewers_on_step`); audited |
| GET `/approvals/{id}` | submitter, owner, assigned reviewer or privileged admin | Steps, assignments, full event history, `can_decide` |
| GET `/documents/{id}/approvals` | same as above | Every submission of a document with its decisions, newest first |
| POST `/approvals/{id}/approve` | document.approve + assigned (or privileged) | Optional `comment`. Last step releases the version. Not for your own submission (403). Repeating is harmless; 409 once the request is decided |
| POST `/approvals/{id}/reject` | document.reject + assigned (or privileged) | Body `reason` (required). 409 once decided |
| POST `/approvals/{id}/comments` | anyone who can view the review | Body `comment`; 201 |
| POST `/documents/{id}/resubmit` | document.upload + owner/uploader | After a rejection; 201 with the new request; 409 if nothing was rejected |

| POST `/documents/{id}/shares` | document.share + owner/uploader/privileged admin | Body `grantee_membership_id`, `can_view` (default true), `can_download`, optional `expires_at`. 201 new, 200 updated; 409 if not released; 422 if the recipient's role does not allow it |
| DELETE `/documents/{id}/shares/{membership_id}` | same | Revokes; 404 if no active share |
| GET `/documents/{id}/shares` | same | Active shares (`history=true` adds expired and revoked) |
| GET `/shares/with-me`, GET `/shares/by-me` | signed in | Active shares to you (only for documents you can still see) or made by you, with title and classification |

| GET `/documents/{id}/lifecycle` | document.view_metadata + access policy | State, retention end, review date, archive time, active legal hold, pending deletion request, deletion blockers |
| POST `/documents/{id}/archive`, POST `/documents/{id}/unarchive` | document.archive / document.restore + may-modify | 409 unless released (archive) or archived (unarchive); archive also 409 while a version awaits review |
| POST/DELETE `/documents/{id}/legal-hold` | document.approve_delete | Body `reason` (required). 409 if already held; DELETE 404 if none |
| POST `/documents/{id}/deletion-requests` | document.request_delete + may-modify | Body `reason`. 409 while a hold, retention period, pending review or pending request applies |
| GET `/deletion-requests` | document.approve_delete | Pending requests for documents you can see |
| POST `/deletion-requests/{id}/approve` / `reject` / `cancel` | approve_delete (not the requester) / approve_delete, `reason` required / requester | Approve removes the files (502 if storage is down; nothing changes). 403 for your own request |
| GET `/lifecycle/due?days=30` | document.archive | Documents with retention ending or review due within `days` |

| GET `/ui-templates/available` | signed in | Published designs you may choose (platform templates and your organization's own), with `is_selected` and `is_default` flags. Drafts and archived designs are never listed |
| GET `/ui-templates/available/{id}` | signed in | One design with its full configuration, for previewing. 404 if not published or not yours |
| GET `/me/ui-preferences` | signed in | Your saved choice and `effective`: `{source: user\|tenant\|product\|system, template}` (template is null for the built-in theme) |
| PUT `/me/ui-preferences` | signed in | Body `{"template_id": uuid\|null}`; null resets. Affects only your own account; the choice persists across sessions and devices |
| GET/PUT `/ui-templates/tenant-default` | admin.manage_organization | The organization's default design for people who have not chosen |

Categories accept `policy.approval_steps` (list of `{type: user|role|department_manager, ref}`), only together with `approval_required`.

Login with MFA on: `POST /auth/login` answers `401 {"detail":{"code":"mfa_required"}}` after a correct password; resend with `mfa_code` (authenticator or recovery code). Wrong codes count toward lockout.

Planned groups follow the PRD section 17 list as each sprint ships.
