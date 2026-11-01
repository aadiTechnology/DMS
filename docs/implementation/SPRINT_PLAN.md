# DMS sprint plan: what exists and what remains

Status on 2026-11-01. **Scope decision by the owner: no further features except dashboards and Coolify deployment readiness. Sprints 18 (notifications), 20 (storage metering), 21 (localization) and the mobile app are set aside, not cancelled. Two small web gaps (tag editing on a document, administrator's list of pending reviews) are accepted as not built.** Web sprints W1 to W2c are approved. Backend: Sprints 0-17 done and tested (346 passed). Web: W1, W2a, W2b, W2c done. Legend: Done = built and tested; Partial = some actions only; None = not built.

## 1. Feature status by area

| # | Area | API | Web | Remaining |
|---|---|---|---|---|
| 1 | Sign-in, sessions, lockout, rate limit | Done | Done (sign in, code, organization chooser, accept invitation, reset password, ask to join) | None |
| 2 | Google / Microsoft sign-in | Done (needs OAuth client ids from owner) | Done (buttons appear when ids are set; real round trip untested) | Client ids |
| 3 | Two-step verification | Done | Done (setup with QR, recovery codes, turn off) | None |
| 4 | Password change (signed in) | Done | Done (Account page) | None |
| 5 | Users, invitations, registration requests | Done | Done (People: employees, invitations, join requests, two-step reset) | None |
| 6 | Roles and permissions | Done | Done (People: give and remove roles; your own permissions page) | None |
| 7 | Organization (departments, branches, projects, designations, employees) | Done | Done (add, edit, switch off, managers, project people, employee details) | None |
| 8 | Categories, metadata fields, tags | Done | Done (categories with review steps, rules and fields; rename or move; tags and tag policy) | None |
| 9 | Upload and security scan | Done | Done | In-page upload progress for large files (hardening) |
| 10 | Document library, search, filters | Done | Done | "My documents", more filters (department, project, tag, dates) |
| 11 | Document detail, preview, download | Done | Done (preview opens inside the page) | None |
| 12 | Edit title, metadata, tags | Done | Partial: title and extra fields | Tag editing |
| 13 | Versions (add, restore, history) | Done | Done | None |
| 14 | Classification and access rules | Done | Done (applied everywhere) | None |
| 15 | Approvals | Done | Partial: queue, decisions, comments, resubmit | Administrator overview of all pending reviews |
| 16 | Sharing | Done | Done (share dialog, revoke, lists) | None |
| 17 | Retention, archive, legal hold, deletion | Done | Done (archive, hold, deletion request and approval, due list) | None |
| 18 | Audit log | Done | Done (Activity: filter by action and date, names shown) | None |
| 19 | Search index administration | Done | Done (Activity: counts, process queue, retry failed) | None |
| 20 | Notifications (in-app, email, digest, reminders) | None | None | Backend and web |
| 21 | Dashboards and reports (CSV / XLSX) | None | None | Backend and web |
| 22 | Storage usage metering and billing ledger | None | None | Backend and web |
| 23 | Hindi / Marathi (and English) text | None | None | Backend messages and web |
| 24 | Mobile app | None | n/a | Whole app |
| 25 | Deployment | API files for Coolify prepared, not run on a server | Not prepared | Web hosting, real Coolify test |
| 26 | Performance at 100,000 documents, security review, accessibility, backup/restore, CI run | Not done | Not done | Hardening sprints |
| 27 | User guides, deployment and test docs, release checklist | Partial | None | Final documentation |

## 2. Sprint plan

Each sprint ends with a narrated walkthrough video and waits for your approval before the next one starts.

| Sprint | Scope | Main deliverables | Video |
|---|---|---|---|
| W2a | Daily-use screens (areas 10-13, 15, 16, 17) | Share dialog, add/restore version, edit details, in-page preview, resubmit and comments, legal hold, deletion request and approval, due list, "My documents" | 02 |
| W2b | Administration (areas 5-8, 18, 19) | Users and invitations, role assignment, category and tag admin with approval steps, organization editing, audit viewer, index status | 03 |
| W2c | Account and first-contact pages (areas 1-4) | Accept invitation, reset password, self-registration, Google/Microsoft buttons, two-step setup, change password (with its small API addition) | 04 |
| 18 | Notifications | Events to in-app and email, daily digest, reminders from retention and review dates, preferences; web bell and settings | 05 |
| 19 | Dashboards and reports | Organization and personal dashboards, report exports (CSV/XLSX); web dashboard and report screens | 06 |
| 20 | Storage metering and billing ledger | Usage per organization, limits, ledger; web usage page | 07 |
| 21 | Localization | English, Hindi, Marathi for web and email text, date and number formats | 08 |
| M1-M2 | Mobile app (React Native / Expo) | Sign-in, search, view, upload with camera, approvals | 09-10 |
| H1 | Hardening: performance and security | 100,000-document load test, security review, live Backblaze tests for large files, copy and delete, shared rate limits, first CI run | none |
| H2 | Hardening: accessibility and recovery | Accessibility checks, backup and restore rehearsal, real Coolify deployment of API and web | 11 |
| R | Release | User guides, deployment and environment docs, test strategy, traceability matrix, release checklist | 12 (overview) |

## 3. Open items on the owner's side

| Item | Needed for |
|---|---|
| Rotate the exposed ERP Backblaze key | Security |
| Production Backblaze bucket and key | Deployment (the test bucket already passed the live test) |
| Google and Microsoft OAuth client ids | Sprint W2c |
| SMTP account | Sprint 18 and deployment |
| Hosting region and domain | Deployment |
| ClamAV container on the server | Deployment |
| Azure Speech key (optional) | Higher-quality narration for videos |

## 4. Revised remaining plan (owner decision, 2026-11-01)

| Step | Scope | Video |
|---|---|---|
| Dashboards (was Sprint 19) | Organization and personal dashboards; report export only if the owner asks | 06 |
| Coolify readiness | Web app container and hosting files, one stack for API, web and database, environment checklist, deployment guide, a rehearsal on a Linux-like local stack | 07 |
| Hardening and release docs | Security and recovery checks needed to deploy safely, user guides, release checklist | 08 |
