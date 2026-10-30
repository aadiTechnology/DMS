# PRD Requirements Traceability Matrix

**Date:** 2026-10-30 · **PRD:** v1.0 (header status: Draft) · **Repo state:** `DMS/` contains only `README.md`; ERP code (`../code`) is reference only.

Status key: **Not implemented** = no code exists in DMS repo (Verified). "Sprint" = proposed sprint in `DMS_IMPLEMENTATION_BASELINE.md` §10. Evidence for every row: `git ls-files` of DMS shows no source files.

## A. Identified requirements

| ID | Pri | Requirement | Sprint | Status / notes |
|---|---|---|---|---|
| ORG-001 | P0 | Create/edit/deactivate departments, branches, projects | S4 | Not implemented |
| ORG-002 | P0 | Assign employees to dept/branch/designation/project; auditable | S4,S5 | Not implemented |
| ORG-003 | P0 | Mandatory org dimensions per category | S7 | Not implemented |
| ORG-004 | P0 | Document associations (dept/branch/project/employee) | S11 | Not implemented |
| ORG-005 | P0 | Preserve historical associations | S11 | Not implemented |
| ORG-006 | P0 | Employees in multiple projects | S4 | Not implemented |
| ORG-007 | P0 | Dashboards filtered by dimensions, scope-limited | S19 | Not implemented |
| ORG-008 | P0 | Deactivate, never hard-delete referenced org entities | S4 | Not implemented |
| CAT-001 | P0 | Category/subcategory CRUD, audited | S7 | Not implemented |
| CAT-002 | P0 | Metadata schema per category | S7 | Not implemented |
| CAT-003 | P0 | Mandatory org dimensions per category enforced at upload | S7,S10 | Not implemented |
| CAT-004 | P0 | Category/metadata versioning, explicit migration | S7 | Not implemented |
| TAG-001 | P0 | Standard tags | S7 | Not implemented |
| TAG-002 | P0 | Employee tags per tenant policy | S7 | Not implemented |
| TAG-003 | P0 | System lifecycle tags | S7 | Not implemented |
| TAG-004 | P0 | Multiple tags, permission-aware tag search | S7,S14 | Not implemented |
| TAG-005 | P1 | Duplicate tag detection | - | Not implemented (P1, deferred) |
| WF-001 | P0 | Approval required per category | S12 | Not implemented |
| WF-002 | P0 | Reviewer assignment | S12 | Not implemented |
| WF-003 | P0 | Approve/reject/comment | S12 | Not implemented |
| WF-004 | P0 | Rejection reason, resubmission | S12 | Not implemented |
| WF-005 | P0 | Pending visibility restricted | S12,S5 | Not implemented |
| WF-006 | P0 | Notify submitter/reviewers, no duplicates | S16 | Not implemented |
| SRCH-001 | P0 | Title/filename search | S14 | Not implemented |
| SRCH-002 | P0 | Full-text search PDF/DOC(X)/XLS(X)/PPT(X)/TXT | S14 | Not implemented; extraction libs undecided |
| SRCH-003 | P0 | Metadata and tag search | S14 | Not implemented |
| SRCH-004 | P0 | Org filters, permitted facets | S14 | Not implemented |
| SRCH-005 | P0 | Owner/uploader/status/classification/date filters | S14 | Not implemented |
| SRCH-006 | P0 | Search all authorized documents | S14 | Not implemented |
| SRCH-007 | P1 | Highlighting, permission-safe snippets | S14 | Not implemented (P1, deferred) |
| SRCH-008 | P1 | Recent searches/autocomplete | - | Not implemented (P1, deferred) |
| SRCH-009 | P0 | Stable sort and pagination | S14 | Not implemented |
| SHR-001 | P0 | Share with employees in same tenant | S13 | Not implemented |
| SHR-002 | P0 | View and/or download grants | S13 | Not implemented |
| SHR-003 | P0 | Revoke share | S13 | Not implemented; needs D11 |
| SHR-004 | P0 | Shared with me / by me | S13,S18 | Not implemented |
| SHR-005 | P0 | Audit share events | S13 | Not implemented |
| SHR-006 | P0 | No share escalation | S13 | Not implemented |
| DASH-001 | P0 | Organization dashboard | S19 | Not implemented |
| DASH-002 | P0 | Department dashboard | S19 | Not implemented |
| DASH-003 | P0 | Project dashboard | S19 | Not implemented |
| DASH-004 | P0 | Employee dashboard | S19 | Not implemented |
| DASH-005 | P0 | Date and org filters | S19 | Not implemented |
| DASH-006 | P0 | CSV/XLSX export, filtered, audited | S19 | Not implemented |
| DASH-007 | P0 | Event tracking | S5,S19 | Not implemented |
| DASH-008 | P0 | Storage by tenant/dept/category, reconciled | S17,S19 | Not implemented |
| I18N-001 | P0 | en/hi/mr, externalized strings | S18,S21 | Not implemented; ERP has no i18n |
| I18N-002 | P0 | User language preference | S18,S21 | Not implemented |
| I18N-003 | P0 | Unicode filenames/tags/metadata/search | S21 | Not implemented |
| I18N-004 | P0 | Localized UI/validation/notifications/emails | S16,S21 | Not implemented |
| I18N-005 | P0 | Locale/timezone formatting, UTC storage | S1,S21 | Not implemented |
| I18N-006 | P1 | RTL readiness | - | Not implemented (P1, deferred) |
| NOT-001 | P0 | In-app notification center | S16 | Not implemented |
| NOT-002 | P0 | Email notifications, retryable | S16 | Not implemented; provider D9 |
| NOT-003 | P0 | Reminder intervals per category/event | S16 | Not implemented |
| NOT-004 | P0 | Daily summary | S16 | Not implemented |
| NOT-005 | P0 | Idempotent delivery | S16 | Not implemented |
| NOT-006 | P0 | Delivery status/history | S16 | Not implemented |
| STO-001 | P0 | Files up to 100 MB, tenant-configurable | S10 | Not implemented |
| STO-002 | P0 | Private S3-compatible storage | S8,S9 | Requires decision (D1) |
| STO-003 | P0 | Extension, MIME, signature validation | S10 | Not implemented |
| STO-004 | P0 | Malware scan before publication | S10 | Not implemented; scanner D7 |
| STO-005 | P0 | Checksum per version | S10,S11 | Not implemented |
| STO-006 | P0 | Metering per tenant/dept/category incl. versions | S17 | Not implemented |
| STO-007 | P0 | Billable usage and overage | S17 | Not implemented; commercial inputs |
| STO-008 | P0 | Short-lived URLs after authz | S9,S11 | Requires decision (D4) |
| STO-009 | P0 | Safe cleanup of abandoned uploads/orphans | S10,S22 | Not implemented |
| BILL-001 | P0 | Plan allowance/overage config (platform admin) | S17 | Not implemented; commercial inputs |
| BILL-002 | P0 | Usage and projected overage to org admin | S17,S19 | Not implemented |
| BILL-003 | P0 | No automatic deletion for billing | S17 | Not implemented |

## B. Cross-cutting and unnumbered requirements

| Requirement | Pri | Sprint | Status / notes |
|---|---|---|---|
| Identity: email/password, Google, Microsoft SSO, optional MFA, invitations, self-registration approval (PRD §5, App.A #13) | P0 | S3,S6 | Partially: ERP has email/password+JWT pattern only (Postgres rewrite needed). SSO/MFA/invites NI; D12 |
| Data-driven RBAC + resource/org/explicit-share checks (PRD §7) | P0 | S5 | NI. ERP model is menu-permission based, not reusable |
| Classification levels incl. org-admin access to Highly Confidential with audit (PRD §7.1, 7.4) | P0 | S5,S11 | NI |
| Deny-by-default, tenant isolation, revocation invalidates sessions (PRD §7.4) | P0 | S2,S3,S5 | NI; ERP has revoked_token pattern |
| Upload workflow with quarantine (PRD §8.1); all employees may upload anywhere | P0 | S10 | NI |
| Versioning: immutable, restore as new current, optimistic concurrency (PRD §8.3) | P0 | S11 | NI |
| Retention, expiry auto-archive, legal hold, approval-controlled disposal (PRD §8.4) | P0 | S15 | NI |
| Audit events for all listed actions, 1-year default retention (PRD §15.1, App.A #21) | P0 | S5 (base) + each sprint | NI; retention semantics undecided |
| API /api/v1 with OpenAPI, idempotency keys, rate limits, non-enumerating errors (PRD §17) | P0 | S0,S2+ | NI |
| Responsive web, WCAG 2.2 AA (PRD §11.1, §14) | P0 | S18,S19,S22 | NI |
| React Native mobile MVP (PRD §11.2) | P0 | S20 | NI; ERP mobile is skeleton |
| Shared TS packages (PRD §18.1) | P0 | S0,S18,S20 | NI |
| Background workers: scan, extract, index, notify, expiry, metering, cleanup (PRD §18) | P0 | S10+ | NI; D8 |
| Backup/restore RPO 24h, RTO 8h; 99.5% availability (PRD §14) | Gate | S22 | NI; hosting D5 |
| Performance targets (PRD §14) | Gate | S22 | NI; no baseline exists |
| Release gates (PRD §19.2) and 14 acceptance scenarios (PRD §19.1) | Gate | S22 | NI |
| Data residency India default (PRD §15.2) | P0 | - | Requires decision (D5) |
| Excluded from MVP: external sharing, co-editing, offline, AI, mandatory OCR, e-sign, SMS/push | - | - | Not applicable to MVP |

## C. Summary

- Numbered requirements: 70. Existing and reusable: 0. Partially implemented: 0. Not implemented: 68. Requires product decision: 2 (STO-002, STO-008).
- P1 deferred: TAG-005, SRCH-007, SRCH-008, I18N-006.
- Blocked by dependency (to be resolved by decisions): STO-004 (D7), NOT-002 (D9), SHR-003 (D11), STO-007/BILL-001 (commercial inputs).
- Not applicable to MVP: PRD §2.2 non-goals.
