# DMS Implementation Baseline

**Date:** 2026-10-30 · **Phase:** Assessment only (no application code written) · **Status:** Awaiting approval

Labels: **Verified** (observed in files/commands this session) · **Inferred** · **Recommended** · **Unknown** (not verified).
Companion file: [PRD_TRACEABILITY_MATRIX.md](PRD_TRACEABILITY_MATRIX.md).

---

## 1. Executive summary

| # | Finding | Label |
|---|---|---|
| 1 | The DMS repository (`C:\Users\lenovo\AadiTech\Product\DMS`) is **greenfield**: one commit, one file (`README.md`, content `# DMS`). There is no code, schema, test, build, CI or docs to reuse. | Verified (`git ls-files`) |
| 2 | Every one of the 70 numbered PRD requirement IDs (plus the unnumbered cross-cutting ones) is therefore **Not implemented** in the DMS repo (2 of them, STO-002 and STO-008, also need a product decision). Nothing is "existing and reusable" at feature level. | Verified |
| 3 | The "existing application" the brief calls the reference is the **school/preschool ERP** at `C:\Users\lenovo\AadiTech\Product\code` (separate git repo). It is a FastAPI + **SQL Server** + React 18/MUI 6 system. It is a source of *patterns*, not of DMS functionality. | Verified |
| 4 | The ERP's B2 integration is native `b2sdk` (not S3-compatible), server-proxied uploads, one shared bucket, 60-min bearer download tokens. `b2sdk` is **not installed** in the ERP's own venv. The live bucket, its privacy, key capabilities and region are unverified. | Verified / Unknown |
| 5 | **Security issue outside DMS scope but urgent:** the ERP repo tracks `apps/fastapi/BACKBLAZE_STATUS.txt`, which the audit says holds a plaintext B2 key ID and key. I did **not** open it. Treat the key as exposed and rotate it. | Verified (`git ls-files`, commit `ba80497`) |
| 6 | The PRD says "S3-compatible private object storage" (STO-002); the ERP uses native B2. This needs a decision before storage work. | Conflict |
| 7 | Several inputs named in the brief do not exist at the stated paths (`docs/product/*.docx`, `docs/audits/*.md` in the DMS repo). They are in `Downloads` and in the ERP repo respectively. | Verified |

**Bottom line:** this is a 0→1 build. The ERP offers reusable *conventions* (JWT + refresh, MUI design-system layering, Alembic, axios token refresh, notification scheduler, B2 wrapper shape). Treat the schedule accordingly: the PRD's M0–M7 milestones are all ahead.

---

## 2. Source inventory

| Input | Location | Notes |
|---|---|---|
| PRD v1.0 | `C:\Users\lenovo\Downloads\DMS_MVP_Product_Requirements_Document_v1.0.docx` | Header status is **"Draft for product and engineering review"**, not "approved". The brief calls it approved. Confirm. |
| B2 audit | `C:\Users\lenovo\AadiTech\Product\code\docs\audits\BACKBLAZE_B2_INTEGRATION_AUDIT.md` | Untracked in the ERP repo (`git status`: `?? docs/`). Read in full; I spot-checked its claims against source (section 5). |
| B2 brief | `C:\Users\lenovo\Downloads\CLAUDE_BACKBLAZE_B2_DMS_IMPLEMENTATION_BRIEF.md` | Governance for storage work. Its "execute B2-S0 only" instruction is superseded by your latest instruction (whole-DMS assessment first). No separate `DMS_B2_IMPLEMENTATION_PLAN.md` was produced; its content is in section 5. |
| ERP source | `C:\Users\lenovo\AadiTech\Product\code` | Reference only. |

---

## 3. Repository structure and technology (Baseline items 1–2)

### 3.1 DMS repo (target)
Verified: only `README.md` and `.git`. Branch `main`, commit `9bebcfc first commit`.

PRD §18.1 suggests: `apps/web`, `apps/mobile`, `services/api`, `services/workers`, `packages/{domain,api-client,validation,authorization-contracts,localization,ui-tokens}`. None exist.

### 3.2 ERP repo (reference), versions Verified from manifests

| Area | Finding | Source |
|---|---|---|
| Backend | FastAPI 0.136.0, Starlette 1.0.0, Uvicorn 0.44.0, SQLAlchemy 2.0.49, Pydantic 2.13.2, Alembic 1.18.4, python-jose 3.5.0, passlib 1.7.4 + bcrypt 4.0.1 | `apps/fastapi/venv/.../*.dist-info`, `requirements.txt` (unpinned in file) |
| Python | 3.12 (`__pycache__/*.cpython-312`); dev machine also has 3.14.3 | Inferred / Verified |
| DB | **SQL Server** via `pyodbc` (`DB_DRIVER` default `ODBC Driver 18 for SQL Server`) | `app/core/config.py`, audit §2.5 |
| Migrations | Alembic, 32 versions | `apps/fastapi/alembic/versions` |
| Web | React 18.3.1, TypeScript 5.5, Vite 5.3, MUI 6, TanStack Query 5.90, react-router 6.23, axios 1.7, react-hook-form 7.53, zod 3.23, Capacitor 8.4 (wrapper, not RN) | `apps/web/package.json` |
| Mobile | Expo ~54.0.33, React Native 0.81.5, **React 19.1.0**; only `App.tsx`, `index.ts` in the app (skeleton) | `apps/mobile/package.json` |
| i18n | **None** (`i18next`/`react-i18next` absent; no matches in `src`) | `package.json`, grep |
| Tests | Playwright E2E (`apps/QA-Automation`, `apps/web/tests/login.spec.ts`); **no** pytest suite (one `scripts/test_token.py`), **no** vitest/jest/RTL | find/ls |
| Design system | `apps/web/src/design-system/{form,patterns,primitives,semantic,validation}` + `theme`, `tokens` | ls |
| Deploy | GitHub Actions → Azure Web App; web Dockerfile (Node 22 + nginx); no FastAPI Dockerfile, no Compose, no Coolify | audit §7 |

**Version-skew risk (Verified):** ERP web is React 18, ERP mobile is React 19. PRD requires shared TS packages across web and RN; pick one React major for the DMS monorepo up front.

---

## 4. Authentication, authorization, tenancy (Baseline items 3, 5)

Evidence in ERP `apps/fastapi/app/core/dependencies.py`, `core/config.py`, `routers/auth.py`, `routers/rbac.py`:

- **Verified:** JWT (HS256, python-jose), access 30 min, refresh 30 days, revoked-token and refresh-token tables (`models/revoked_token.py`, `refresh_token.py`). Single `SECRET_KEY`.
- **Verified:** Tenant resolved from the authenticated user (`CurrentUser.tenant_id`), integer ids; platform admins have `tenant_id is None`; cross-tenant query param is rejected for tenant users (`dependencies.py` lines 164–195).
- **Verified:** Authorization is **menu/route permission based** (`RoleMenuPermission`, `_enforce_menu_permission`), tied to a school ERP menu model.
- **Verified absent:** Google/Microsoft SSO, MFA, rate limiting/lockout (grep of `routers/auth.py` found none).
- **Gap vs PRD §7:** the PRD needs document-level hybrid RBAC+ABAC (classification, ownership, explicit grants, workflow state, legal hold, admin-privilege auditing). The ERP model cannot be extended into this; it must be designed new. Reusable only as a *pattern* for dependency-injected current user and tenant resolution.

---

## 5. Existing Backblaze B2 integration (Baseline item 6)

### 5.1 Audit claims I re-verified in source

| Claim | Result |
|---|---|
| Native B2 via `b2sdk.v2`, `authorize_account("production", ...)` | Verified: `services/backblaze_blob_service.py:76` |
| `STORAGE_PROVIDER` default `azure`; `BACKBLAZE_KEY_ID/APP_KEY/BUCKET_NAME` | Verified: `core/config.py:100-117`; bucket default `attachmentserp-b2` |
| Functions: `upload_bytes`, `download_bytes`, `delete_blob`, `blob_exists`, `generate_authorized_download_url`, `ensure_bucket_exists` | Verified: lines 136, 209, 192, 183, 245, 111 |
| Download token via `get_download_authorization` | Verified: line 269 |
| `b2sdk>=2.0.0` unpinned in requirements | Verified |
| `.env`, `.env.*` ignored; status file is tracked | Verified: `.gitignore:18-19`; `git ls-files` lists `BACKBLAZE_STATUS.txt` |
| Alembic migrations; SQL Server | Verified |

**New finding not in the audit:** `b2sdk` is **not installed** in `apps/fastapi/venv` (only `azure_storage_blob-12.30.0` is). So the installed SDK version is unknown and the local B2 path has likely never run in this venv. (Verified by listing site-packages.)

### 5.2 Still unresolved (cannot be verified from files)
Live bucket name and privacy; key capabilities and bucket restriction; account region/cluster; whether production uses Backblaze at all; B2 file-versioning/lifecycle; where production secrets live (Azure App Settings vs Coolify); S3-endpoint availability for the account.

### 5.3 Reuse assessment

| Reuse directly | Adapt | Do not reuse |
|---|---|---|
| Lazy `b2sdk` import and typed config errors pattern | Download-authorization call with an explicit short TTL, exact-key scope | Shared ERP bucket and key; the committed key |
| Server-side-only credentials | Key scheme (audit §9.3 `tenants/{tenant_id}/...` vs brief `{tenant_id}/...`; pick one) | Whole-file in-memory upload/download (100 MB limit) |
| `persistable_document_path` idea: store key, never a URL | Metadata: add checksum, size, B2 file id, scan status | Azure/B2 mixed locator (`blob_storage_factory.py`) |
| Auth-before-token ordering | Delete: surface errors, no silent swallow | Image recompression, icon uploader, unauthenticated icon route |

**Storage configuration is not yet verified**, so per your instruction storage implementation is **blocked** until section 11 decisions D1–D4 are answered. The rest of the DMS is not blocked.

---

## 6. Architecture gap analysis (PRD §18 vs reality)

| Capability | PRD target | Current state | Gap |
|---|---|---|---|
| Monorepo, shared TS packages | Yes | None | Create from scratch |
| API | FastAPI `/api/v1`, OpenAPI | ERP has FastAPI but unversioned, SQL Server | New service; reuse conventions only |
| Database | PostgreSQL | ERP is SQL Server | New schema, new migrations; **Alembic reusable as tool** |
| Tenant model | `tenant_id` on all rows, opaque ids | ERP int `tenant_id` | New design; enforce in repository layer + Postgres RLS (Recommended, needs decision D6) |
| Identity | Email/password, Google, Microsoft SSO, optional MFA, invites, self-registration approval | ERP: email/password only | SSO, MFA, invites, account-linking rules all new |
| RBAC/ABAC | Document-level policy engine, explicit grants, admin-privilege auditing | ERP: menu permissions | New policy engine |
| Object storage | Private S3-compatible, presigned, multipart, checksums | ERP: native B2, proxied, single bucket | New storage module (see §5) |
| Workers/queue | Scan, extract, index, notify, expiry, metering, cleanup | ERP: in-process `notification_scheduler.py` | Need a real queue/worker; technology not chosen (D8) |
| Malware scan | Required before publication | None | Engine unchosen (D7) |
| Search | Postgres FTS acceptable initially; permission-aware | None | New; extraction libraries to select |
| Preview | Browser-native or server conversion | None | Office conversion approach undecided (PRD §20.2) |
| Notifications | In-app + email, localized, idempotent | ERP has notification model/router; email provider unknown | Provider undecided (D9) |
| i18n | en/hi/mr, externalized | None in ERP | New (`i18next`) |
| Web UI | React+TS, accessible, responsive | ERP MUI 6 design-system layering is a good template | New app; may copy structure, not code |
| Mobile | RN + Expo, shared logic | ERP mobile is a skeleton | New |
| Observability, backup/restore, load test | Required release gates | None | New |
| Tests | Unit, API, authz, tenant, E2E | ERP: Playwright only | Establish pytest + vitest + Playwright + Expo test stack |

---

## 7. Cross-source conflicts (recorded, none silently resolved)

| ID | Conflict | Sources | Needed from you |
|---|---|---|---|
| C1 | "S3-compatible" storage vs native-B2 reference implementation | PRD STO-002 / ERP code | D1 |
| C2 | PostgreSQL vs SQL Server in the "existing application" | PRD §18 / ERP | Confirm DMS is standalone Postgres (assumed) |
| C3 | PRD "approved" (brief) vs "Draft" (PRD header) | Brief / PRD | D10 |
| C4 | Object key: `tenants/{tenant_id}/documents/{doc}/versions/{n}/{object_id}/{file}` vs `{tenant_id}/documents/{doc}/versions/{version_id}/{file}` | Audit §9.3 / prompt §4 | D3 |
| C5 | Deployment: brief mentions Coolify; ERP deploys to Azure App Service; PRD wants India region | Brief / audit / PRD | D5 |
| C6 | Brief says use "existing repository tests/migrations/architecture docs"; DMS repo has none | Prompt / repo | Informational |
| C7 | Org admins see all documents incl. Highly Confidential (PRD §7) vs "platform staff get no automatic access" (PRD §7.1) | PRD internal | Not a conflict; both must be implemented. Needs a tenant-admin vs platform-operator role split in schema |
| C8 | ERP download token default (60 min) vs PRD "short expiry" (STO-008) | Audit / PRD | D4 |

---

## 8. Dependencies and risk assessment

| ID | Risk / dependency | Severity | Mitigation (Recommended) |
|---|---|---|---|
| R1 | B2 key exposed in ERP git history | Critical (not DMS code) | Rotate now; purge history; use new key/bucket for DMS |
| R2 | Storage target unverified (bucket, privacy, region, S3 vs native) | High | Gate storage sprints on D1–D4; build against a storage interface + in-memory fake first |
| R3 | Permission complexity causes leakage (PRD top risk) | High | Central policy engine first; deny-by-default; negative test matrix per endpoint and per search path |
| R4 | Search/export/snippet leakage | High | Permission filter in SQL, not post-filter; tests per PRD §19.1 |
| R5 | Scope: 70 numbered P0/P1 requirements from zero, plus web, mobile, workers | High | Micro-sprints in §10; defer P1; use Postgres FTS |
| R6 | Unchosen infra: queue, malware scanner, email, Office preview, hosting | High | Decisions D6–D9 |
| R7 | React 18/19 skew across web/mobile in shared packages | Medium | Standardize before scaffolding |
| R8 | Commercial inputs missing (plans, allowance, overage rate) | Medium | Build metering ledger; leave pricing as plan config |
| R9 | 100 MB uploads: ERP path buffers fully in memory | Medium | Direct-to-storage presigned/multipart; never buffer |
| R10 | Admin all-document access is an explicit audit liability | Medium | Distinct `privileged_access` audit action; admin-access review report |
| R11 | Revocation consistency undefined for search, caches, issued URLs | Medium | D11; default: new URL issuance blocked immediately, issued URLs ≤ 5 min TTL |
| R12 | Windows dev host, Python 3.14 vs 3.12 | Low | Pin Python 3.12 in `.python-version`/CI |
| R13 | Testing on a real B2 bucket could touch prod data | Medium | Dedicated test bucket and key, mocked storage by default |

---

## 9. Recommended technology decisions (Recommended, pending approval)

- Python 3.12, FastAPI, SQLAlchemy 2 (sync or async: decide in sprint 0), Alembic, PostgreSQL 16, pytest.
- React 18.3 + TS 5.x + Vite + MUI 6 + TanStack Query, mirroring the ERP so the team's patterns carry over; Expo/RN on the same React major (pin the version that Expo SDK supports) , `i18next` for both.
- Modular monolith in `services/api`; separate `services/workers` process using a Postgres-backed job queue (no new infra) unless D8 picks otherwise.
- Storage behind a `StorageProvider` interface; first adapter chosen by D1.
- Postgres row-level security as defense-in-depth beside application-level tenant filtering.

---

## 10. Recommended micro-sprint plan

Each sprint ≤20 new / ≤10 modified files, one objective, green tests before close, report then wait for approval. Order follows dependencies; B2 work is intentionally late (after the domain exists) per your priority statement.

| # | Sprint | Objective | Depends on |
|---|---|---|---|
| 0 | Repo scaffold | Monorepo, tooling, CI, lint/test harness, `.gitignore`/`.env.example` (names only), copy PRD + audit into `docs/` | D10 |
| 1 | DB foundation | Postgres schema base, Alembic, tenant + user + membership tables, id strategy, migration test | 0 |
| 2 | Tenant isolation core | Tenant-context dependency, repository base class with mandatory tenant filter, RLS, cross-tenant negative tests | 1 |
| 3 | Auth I | Email/password, JWT + refresh, revocation, lockout/rate limit | 2 |
| 4 | Org structure | Departments, branches, projects, designations, memberships (ORG-001..008) | 2 |
| 5 | RBAC engine | Roles, permissions, assignments, policy evaluator, effective-access explain, audit event base | 3, 4 |
| 6 | Auth II | Invitations, self-registration approval, Google/Microsoft SSO, optional MFA | 3, D12 |
| 7 | Taxonomy | Categories, category versions, metadata schemas, tags, classifications (CAT, TAG) | 5 |
| 8 | Storage abstraction + fake | Interface, in-memory/local-disk dev adapter, key scheme, config validation | D1, D3 |
| 9 | B2 adapter | Real adapter, presigned/multipart, live test against test bucket | 8, D1–D4 |
| 10 | Upload pipeline | Upload session, validation (ext/MIME/signature), quarantine, checksum, worker scan | 7, 9, D7, D8 |
| 11 | Documents + versions | Document/version model, optimistic concurrency, restore, download authz | 10 |
| 12 | Approvals | Workflow states, reviewer queue, comments, resubmission (WF) | 11 |
| 13 | Sharing | Grants, revocation, shared-with-me/by-me, escalation guard (SHR) | 11 |
| 14 | Search | Extraction, Postgres FTS, permission-aware filters/facets/snippets, leakage tests (SRCH) | 11, 13 |
| 15 | Retention | Expiry, archive, legal hold, deletion approval, disposal jobs | 12 |
| 16 | Notifications | In-app, email, digest, idempotency (NOT) | 12, D9 |
| 17 | Metering | Usage ledger, plan config, overage calc, org-admin usage view (STO-006/7, BILL) | 11 |
| 18 | Web app shell + core flows | Layout, i18n, login, browse, upload, view, download, share, history, pending approvals | 11–13 |
| 19 | Web admin + dashboards | Org/dept/project/employee dashboards, CSV/XLSX export, audit viewer, admin screens | 15–17 |
| 20 | Mobile | Expo app: login, search, preview, upload, camera, download, shared-with-me | 14, 18 |
| 21 | Localization | hi/mr resources, Unicode round-trip tests | 18 |
| 22 | Hardening | Performance/load, security review, accessibility, backup/restore drill, runbooks | all |

Sprints 18–20 may be split further. Feature docs under `docs/user-guide/` land in the sprint that delivers each feature.

---

## 11. Missing decisions and inputs required before implementation

**Blocking storage work**
- **D1.** Storage protocol: S3-compatible API (PRD STO-002; presigned PUT/multipart natural; new client) or native B2 `b2sdk` (existing wrapper; needs upload-authorization/large-file code)? *Recommendation: S3-compatible via B2's S3 endpoint, because it matches the PRD and avoids bespoke upload tokens. Confirm the account supports it.*
- **D2.** Non-secret B2 facts (you may state `configured`/`not configured` for secrets): new DMS bucket name per environment, B2 region/endpoint, confirmation bucket is private, whether a dedicated test bucket and restricted key exist. Please do not paste key values.
- **D3.** Object key scheme (C4).
- **D4.** Download URL TTL (Recommended 5 min) and revocation SLA (D11).

**Blocking platform choices**
- **D5.** Hosting target and region for the DMS (Azure App Service like the ERP, Coolify, or other; India region).
- **D6.** Confirm PostgreSQL-only and RLS as defense-in-depth; confirm new, separate database (not the ERP's SQL Server).
- **D7.** Malware scanner (e.g., ClamAV container vs a SaaS API).
- **D8.** Background job mechanism (Postgres-backed queue vs Redis/Celery/RQ).
- **D9.** Email provider for NOT-002.
- **D10.** Is the PRD now approved? Header says Draft. Also confirm I may copy the PRD and audit into `DMS/docs/product` and `docs/audits` (the audit holds no secrets per its own statement).
- **D11.** Revocation consistency target for search/caches/issued URLs (PRD §20.2).
- **D12.** Account-linking rules for password vs Google/Microsoft identities (PRD §20.2); which Google/Microsoft tenants/apps exist.

**Product/commercial (not blocking sprints 0–7)**
Plans, included storage, overage rate, rounding, grace/failed-payment policy; supported preview formats and Office conversion approach; whether a category may have multiple dept/branch/project associations and how policies combine; audit retention semantics; tenant export/offboarding.

**Operational (outside DMS, high urgency)**
Rotate the B2 key referenced by the ERP's tracked `BACKBLAZE_STATUS.txt` and purge it from history.

---

## 12. What I did and did not do

Did: read the PRD (all 20 sections and appendices), the brief and the audit; inspected the DMS repo and the ERP repo manifests, config, dependencies and B2 service symbols (read-only); checked `.gitignore` and tracked files.

Did not: open any `.env*` or `BACKBLAZE_STATUS.txt`; call Backblaze; run ERP tests or builds; connect to any database; modify the ERP repo; write application code. No test or build was run, so no test or performance result is claimed.

**Awaiting your approval and answers to section 11 (at minimum D1, D5, D10) before Sprint 0.**
