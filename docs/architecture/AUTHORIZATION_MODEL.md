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

## 6. Single sign-on and two-step verification (Sprint 7, implemented and tested)

- **SSO (Google, Microsoft).** The web/mobile client signs the person in with the provider and sends us the ID token; the server verifies signature (provider keys), audience (our client id), issuer, expiry and optional nonce. SSO **never creates accounts**: people join by invitation or approved registration. Links are keyed on (provider, stable subject), never email; one link per provider per user and a different subject can never be re-bound. First link needs a *trusted* email matching an active account that already belongs to an organization (or holds a valid invitation): Google `email_verified`; Microsoft `xms_edov` (the plain Entra `email` claim is not trusted because tenants can set it freely). An invitation can be accepted by SSO instead of a password; such a person has no password at all.
- **MFA (TOTP, RFC 6238).** Optional per person, for password sign-in. SSO relies on the provider's own MFA. Secrets are encrypted at rest (Fernet, key from `MFA_ENCRYPTION_KEY` or derived from `SECRET_KEY`; if the key changes, affected people fail verification until an admin resets them, no crash). A code works once (replay blocked) with +/-30 s clock tolerance. 8 single-use recovery codes are stored hashed. Wrong codes count toward the same lockout as wrong passwords. Turning it off needs password plus a code. Admins with `admin.manage_users` can reset a lost device (audited as privileged).
- **Not built / limits:** tenant-wide "MFA required" policy (PRD allows stronger policy later), MFA for SSO users, WebAuthn, provider logout, SSO account unlinking UI/endpoint, real provider app registrations (you must create Google and Microsoft OAuth clients and set `SSO_GOOGLE_CLIENT_ID` / `SSO_MICROSOFT_CLIENT_ID`). Verification was tested against locally generated keys and tokens, **not** against live Google/Microsoft.

## 7. Document access policy (Sprint 12, implemented and tested)

`app/services/access.py: decide()` answers "may this person view metadata / preview / download this document right now?". It runs on every protected request; hiding a button is never the control.

Evaluation order:
1. **Role ceiling.** The person's roles must grant `document.view_metadata`, `document.preview` or `document.download`. Shares never exceed this (a user whose role cannot download cannot be given download by a share; answer 403).
2. **Publication state.** Draft, submitted, under review and rejected documents are visible only to their uploader and owner (reviewers join with the approval workflow). Approved and archived documents follow the classification rules.
3. **Classification (PRD 7.1)**

| Level | Who |
|---|---|
| Public, Internal | every active employee of the organization |
| Confidential | owner; uploader; direct share; managers and members of the associated departments; managers and members of the associated projects |
| Highly Confidential | owner; managers of the associated departments; direct share. The uploader (if not the owner) may see metadata to follow the upload but not open the file |

4. **Direct shares** (`document_access_grants`): `can_view` covers metadata and preview, `can_download` is separate (viewing never implies downloading). Revoked or expired shares stop working on the next request. The endpoints that create shares arrive in the sharing sprint; the policy already honors them.
5. **Privileged access.** Holders of `document.access_all` (only the organization administrator role template has it) may reach any document, including pending and Highly Confidential ones. That path is flagged privileged and **every use is audited** (`document.privileged_access`, `privileged = true`, with the action, classification and version). An administrator who is also the owner uses the normal path and is not flagged. Platform staff have no such permission.

**Refusals** answer 404 (403 only when the role itself lacks the right), so a document's existence is not revealed; each refusal is audited (`document.access_denied` with the reason). **Links:** `GET /documents/{id}/versions/{n}/download-url` and `/preview-url` issue a 5-minute (configurable, max 15) link only after the policy check; every issue is audited without storing the link. Download forces an attachment; preview is inline and only for PDF, PNG and JPEG (verified by file signature at upload); everything else downloads. A link already issued works until it expires even if access is revoked in the meantime (residual window = link lifetime).

**Decisions to review (Product Owner):** (a) "Confidential" is interpreted as owner/uploader plus managers and members of the associated departments and projects plus direct shares; a stricter reading (managers only) is a one-line change. (b) The uploader of a Highly Confidential document they do not own cannot open it after upload, following the PRD list literally. (c) Administrator privilege is a permission (`document.access_all`), not a role name, so a tenant could withhold it; the default template grants it, as the PRD requires.

**Measured:** one access decision, including opening the tenant transaction and loading roles: p50 8.8 ms, p95 10.8 ms (400 decisions, 500 documents, 300 members, local Postgres, single client). Target p95 <= 200 ms.

**Next:** the same rules as a SQL filter for lists, search, counts and exports (search sprint), with a test that compares it with `decide()` so they cannot drift; reviewers for pending documents (approval sprint).

## 8. Search and lists (Sprint 13, implemented and tested)

- **One policy, two forms.** `access_sql.visible_clause()` is the SQL version of `access.decide(..., "view_metadata")` used by search, lists, totals and facets. `tests/test_search.py::test_sql_visibility_equals_the_policy_engine_for_every_viewer` builds 108 documents (every classification, state, association and ownership mix, plus valid/expired/revoked shares) and proves both give identical results for 14 kinds of viewer (owner, stranger, department manager and member, project manager and member, reviewer, no-role user, administrator, exited employee, ended project member, share holders). If either side changes, that test fails.
- **The index holds no permissions.** It stores only text vectors. Who may see a result is decided at query time, so revoking a share, deactivating a membership or changing a role takes effect on the next request; there is no stale-index window to manage. Archived documents remain searchable to authorized users.
- **No leakage through side channels.** Results, `total` and facet counts cover only visible documents; an unauthorized caller searching for a word that exists only inside a hidden document gets zero results; pending documents are visible to their uploader only; administrators' searches are flagged and audited (`document.privileged_search`, one entry per search with the term count, not the document list). Search is rate limited per user.
- **Text extraction** runs in a separate, time-limited process (never inside the API), with caps on pages, part sizes and characters, hardened XML parsing (entity bombs are refused) and reason codes instead of error text. Supported: PDF, DOCX, XLSX, PPTX, TXT, CSV. Not supported (reported as `unsupported`, still findable by title, file name and metadata): legacy DOC/XLS/PPT and images (OCR is outside the MVP). Failures are visible to administrators with a retry button.
- **Languages:** PostgreSQL `simple` configuration: Hindi, Marathi and English words are indexed whole and found by prefix; there is no stemming (searching "report" does not match "reports").
- **Measured (30,000 documents in one organization, local Postgres, one client, synthetic data):** employee list with facets p50 349 ms, max 765 ms; title/prefix/content searches p50 133-300 ms; administrator list p50 115 ms. PRD targets are 2-3 s p95 at 100,000 documents per organization; 100,000 and concurrent load are not yet measured.

## 9. Versions and edits (Sprint 14, implemented and tested)

- **Who may change a document** (`access.can_modify`, on top of the role permission `document.upload_version` / `document.edit_metadata`): the owner; the uploader, except for a Highly Confidential document they do not own; or an administrator with `document.access_all` (flagged privileged and audited). Everyone else gets "not found" and a `document.access_denied` entry.
- **Version-level access** (`access.decide_version`): a published version (available and not awaiting approval) follows the document rules; any other version (uploading, awaiting approval, rejected, quarantined, abandoned) is visible only to its uploader, the owner, and privileged administrators. A historical version is judged by **today's** authorization: revoking a share removes access to every version at once.
- **No silent overwrite:** adding or restoring a version requires `based_on_version`; editing requires `row_version`. A mismatch is a 409 that carries the current number, and nothing is changed. Only one upload may be in progress per document, and only one version may await approval at a time.
- **Approval gate (rules in place, decisions arrive next sprint):** in a category that needs approval a later version is stored but not served (`review_status = pending`); readers keep the last approved version and the search index keeps pointing at it. The first version of such a document stays unpublished as before. Approvals are decided through the workflow in section 10.
- **Restore** copies the bytes server-side into a new object (Backblaze `copy`, verified size and SHA-1, never overwrites) and records `restored_from_version`; the old object is not shared and can be retired independently later.
- **Tag links** can now be removed (the one new DELETE grant, on `document_tags`); the change is recorded in the audit event, which lists the names of changed fields, not values.

## 10. Approval workflow (Sprint 15, implemented and tested)

- **Steps:** a category version may list up to 5 review steps (`approval_steps`): a named person (`user`), everyone holding a role (`role`) or the manager of the document's associated department (`department_manager`). With none listed there is one default step: anyone holding `document.approve`. Steps are copied into the request when it is created, so later category edits never change a review in progress.
- **Who is assigned:** active employees who hold `document.approve` and match the step, minus the submitter. A step may be satisfied by **any one** assigned reviewer (decision recorded in the first version of this feature; "all must approve" is not offered).
- **Self-approval is impossible:** the submitter cannot decide their own submission, administrators included (403). A step that has nobody eligible waits; only an administrator with `document.access_all` may decide it, flagged `privileged` in the event and the audit log, and listed in `GET /approvals/pending`.
- **Reviewer access:** an assigned reviewer on the current step may see the document and open the version under review (view and preview; download still needs `document.download`). The right ends when the request is decided. Everyone else keeps seeing the last approved version only.
- **Release:** approving the last step marks the version approved, sets the document approved if it was not yet published, moves `current_version_number` to the newest approved version and refreshes search. A rejected later version leaves the published one untouched; a rejected first version leaves the document rejected until resubmitted.
- **Rejection** needs a written reason. The uploader may fix metadata and call `resubmit`; the earlier request and its decisions stay on record and the new request points back to it.
- **Privacy:** a review (comments, reasons, reviewers) is visible to the submitter, owner, assigned reviewers and privileged administrators only. Refusals are answered "not found" (403 when the role lacks the permission) and audited as `approval.access_denied`.
- **Notification hooks:** every step start and decision is an `approval_events` row and an `approval.*` audit event; the notification sprint will read these.

## 11. Planned
RBAC roles/permissions, document-level policy (classification, ownership, grants, workflow state, legal hold), admin-privilege audit: Sprint 5 onward.
