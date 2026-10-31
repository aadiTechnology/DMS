"""Development-only demo data: one fictional organization, role-based demo accounts and sample
documents, created through the real API (in process) so every rule applies as in production.

    DATABASE_URL=postgresql+psycopg://...@.../dms_demo uv run alembic upgrade head
    DATABASE_URL=... STORAGE_LOCAL_DIR=... uv run python scripts/seed_demo.py

Refuses to run for ENVIRONMENT=production or for a database whose name does not contain "demo".
Refuses a database that already holds the demo organization. The generated password is written
only to docs/demo/DMS_DEMO_ACCESS.md (git-ignored) and is never printed.
"""

import os
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import make_url, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Role
from app.db.session import get_engine
from app.db.tenant_session import tenant_session
from app.main import app
from app.platform_admin import grant as grant_platform_admin
from app.services import rbac
from app.services.tenants import provision_tenant
from app.ui.seed import seed_directory
from tests.samples import make_docx, make_pdf, make_xlsx

ORG = "Demo Industries"
DOMAIN = "demo.dms.test"
ACCESS_FILE = Path(
    os.environ.get("DEMO_ACCESS_FILE") or ROOT.parents[1] / "docs" / "demo" / "DMS_DEMO_ACCESS.md"
)
WEB_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

PEOPLE = {
    "admin": ("asha.kulkarni", "Asha Kulkarni", "org_admin", "Organization Administrator"),
    "dept": ("rohan.deshmukh", "Rohan Deshmukh", "department_manager", "Department Manager (Finance)"),
    "project": ("priya.nair", "Priya Nair", "project_manager", "Project Manager (Apollo ERP Rollout)"),
    "employee": ("sameer.patil", "Sameer Patil", "employee", "Employee (Finance)"),
    "reviewer": ("meera.joshi", "Meera Joshi", "reviewer", "Reviewer / Approver"),
    "colleague": ("neha.shah", "Neha Shah", "employee", "Employee (Human Resources)"),
}  # fmt: skip


def guard() -> None:
    settings = get_settings()
    name = make_url(settings.DATABASE_URL).database or ""
    if settings.ENVIRONMENT == "production" or "demo" not in name:
        sys.exit("Refusing: the demo seed only runs on a database whose name contains 'demo'.")
    if settings.EMAIL_BACKEND == "smtp":
        sys.exit("Refusing: demo data must not be able to send real email.")


def create_people(password: str) -> SimpleNamespace:
    engine = get_engine()
    hashed = hash_password(password)
    ids = {}
    with engine.begin() as c:
        if c.execute(text("SELECT 1 FROM tenants WHERE name = :n"), {"n": ORG}).first():
            sys.exit("The demo organization already exists; use a fresh demo database.")
        for key, (local, *_rest) in PEOPLE.items():
            ids[key] = c.execute(
                text("INSERT INTO users(email, password_hash) VALUES (:e, :p) RETURNING id"),
                {"e": f"{local}@{DOMAIN}", "p": hashed},
            ).scalar()
    with Session(engine) as s, s.begin():
        tenant = provision_tenant(s, ORG, ids["admin"], slug="demo-industries")
    mids = {}
    with engine.begin() as c:
        for key, uid in ids.items():
            if key != "admin":
                c.execute(
                    text(
                        "INSERT INTO tenant_memberships(tenant_id,user_id,status) VALUES (:t,:u,'active')"
                    ),
                    {"t": tenant, "u": uid},
                )
            mids[key] = c.execute(
                text("SELECT id FROM tenant_memberships WHERE user_id = :u"), {"u": uid}
            ).scalar()
    with tenant_session(tenant, engine) as s:
        roles = {r.name: r.id for r in s.scalars(select(Role))}
        for key, (_l, _n, role, _d) in PEOPLE.items():
            if key != "admin":  # the administrator already holds org_admin
                rbac.assign_role(s, tenant, ids["admin"], mids[key], roles[role])
    return SimpleNamespace(tenant=tenant, uids=ids, mids=mids)


class Api:
    def __init__(self, client: TestClient, password: str):
        self.c, self.password, self.h = client, password, {}

    def login(self, key: str) -> dict:
        r = self.c.post(
            "/api/v1/auth/login",
            json={"email": f"{PEOPLE[key][0]}@{DOMAIN}", "password": self.password},
        )
        assert r.status_code == 200, f"login failed for {key}: {r.status_code}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def ok(self, method: str, path: str, h: dict, expect=(200, 201), **kw):
        r = self.c.request(method, f"/api/v1{path}", headers=h, **kw)
        assert r.status_code in expect, f"{method} {path} -> {r.status_code} {r.text[:200]}"
        return r.json() if r.content else None


def upload(api: Api, h, category, filename, content_type, data, **over):
    r = api.ok(
        "POST", "/documents/uploads", h,
        json={"category_id": category["id"], "filename": filename, "content_type": content_type,
              "size_bytes": len(data), **over},
    )  # fmt: skip
    done = api.c.put(
        f"/api/v1/documents/uploads/{r['version_id']}/content", content=data, headers=h
    )
    assert done.status_code == 200, f"upload {filename}: {done.status_code} {done.text[:200]}"
    return r["document_id"]


def seed(api: Api, world: SimpleNamespace) -> dict:
    H = {k: api.login(k) for k in PEOPLE}
    mids = {k: str(v) for k, v in world.mids.items()}
    for key, (_l, name, *_r) in PEOPLE.items():
        api.ok("PUT", f"/employees/{mids[key]}/profile", H["admin"], json={"full_name": name})

    org = lambda kind, body: api.ok("POST", f"/org/{kind}", H["admin"], json=body)
    fin = org(
        "departments", {"name": "Finance", "code": "FIN", "manager_membership_id": mids["dept"]}
    )
    hr = org("departments", {"name": "Human Resources", "code": "HR"})
    ops = org("departments", {"name": "Operations", "code": "OPS"})
    pune = org("branches", {"name": "Pune Head Office", "code": "PUN"})
    mumbai = org("branches", {"name": "Mumbai Branch", "code": "MUM"})
    apollo = org(
        "projects",
        {"name": "Apollo ERP Rollout", "code": "APO", "manager_membership_id": mids["project"]},
    )
    org("designations", {"name": "Finance Manager"})
    org("designations", {"name": "Accounts Executive"})
    for key, dept, branch in (
        ("admin", ops, pune), ("dept", fin, pune), ("project", ops, mumbai),
        ("employee", fin, pune), ("reviewer", ops, pune), ("colleague", hr, mumbai),
    ):  # fmt: skip
        api.ok(
            "PUT", f"/employees/{mids[key]}/profile", H["admin"],
            json={"department_id": dept["id"], "branch_id": branch["id"], "employment_status": "active"},
        )  # fmt: skip
    for key in ("project", "employee"):
        api.ok("PUT", f"/projects/{apollo['id']}/members/{mids[key]}", H["admin"], json={})

    cat = lambda body: api.ok("POST", "/categories", H["admin"], json=body)
    policies = cat({"name": "Policies", "default_classification": "internal",
                    "policy": {"retention_days": 1095, "review_interval_days": 365}})  # fmt: skip
    invoices = cat({
        "name": "Invoices", "default_classification": "confidential",
        "policy": {"required_dimensions": ["department"], "retention_days": 2555},
        "fields": [
            {"key": "invoice_no", "label": "Invoice number", "field_type": "text", "required": True},
            {"key": "vendor", "label": "Vendor", "field_type": "text"},
        ],
    })  # fmt: skip
    contracts = cat({
        "name": "Contracts", "default_classification": "confidential",
        "policy": {"approval_required": True, "required_dimensions": ["department"],
                   "allowed_extensions": ["pdf", "docx"], "retention_days": 1825},
        "fields": [{"key": "ref", "label": "Contract reference", "field_type": "text", "required": True}],
    })  # fmt: skip
    records = cat({"name": "Employee Records", "default_classification": "highly_confidential",
                   "policy": {"required_dimensions": ["department"]}})  # fmt: skip

    pdf, docx = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    dept = {"department": [fin["id"]]}
    docs = {}
    docs["leave"] = upload(api, H["admin"], policies, "Leave Policy 2026.pdf", pdf,
                           make_pdf("Leave policy: annual leave, sick leave and carry forward rules."),
                           title="Leave Policy 2026", classification="internal")  # fmt: skip
    docs["travel"] = upload(api, H["colleague"], policies, "Travel and Expense Policy.docx", docx,
                            make_docx("Travel and expense policy", "Claims must be filed within thirty days."),
                            title="Travel and Expense Policy", classification="internal")  # fmt: skip
    docs["old"] = upload(api, H["admin"], policies, "Remote Work Guidelines 2023.pdf", pdf,
                         make_pdf("Remote work guidelines from 2023, superseded."),
                         title="Remote Work Guidelines 2023", classification="internal")  # fmt: skip
    docs["inv1"] = upload(api, H["employee"], invoices, "INV-1001 Acme Supplies.pdf", pdf,
                          make_pdf("Invoice INV-1001 from Acme Supplies for office stationery."),
                          title="Invoice INV-1001 Acme Supplies", associations=dept,
                          metadata={"invoice_no": "INV-1001", "vendor": "Acme Supplies"})  # fmt: skip
    docs["inv2"] = upload(api, H["employee"], invoices, "INV-1002 Northwind Logistics.xlsx", xlsx,
                          make_xlsx("Invoice INV-1002", "Northwind Logistics freight charges"),
                          title="Invoice INV-1002 Northwind Logistics", associations=dept,
                          metadata={"invoice_no": "INV-1002", "vendor": "Northwind Logistics"})  # fmt: skip
    docs["record"] = upload(api, H["admin"], records, "Salary Revision Letters FY26.pdf", pdf,
                            make_pdf("Salary revision letters for the financial year."),
                            title="Salary Revision Letters FY26", associations={"department": [hr["id"]]})  # fmt: skip
    docs["nda"] = upload(api, H["employee"], contracts, "Mutual NDA Template.pdf", pdf,
                         make_pdf("Mutual non-disclosure agreement template."),
                         title="Mutual NDA Template", associations=dept, metadata={"ref": "CT-0007"})  # fmt: skip
    docs["agreement"] = upload(api, H["employee"], contracts, "Vendor Agreement - Acme Supplies.pdf", pdf,
                               make_pdf("Vendor agreement with Acme Supplies for stationery."),
                               title="Vendor Agreement - Acme Supplies", associations={**dept, "project": [apollo["id"]]},
                               metadata={"ref": "CT-0012"})  # fmt: skip

    # approvals: one approved, one left waiting for a reviewer
    nda_request = api.ok("GET", f"/documents/{docs['nda']}/approvals", H["employee"])[0]["id"]
    api.ok(
        "POST",
        f"/approvals/{nda_request}/approve",
        H["reviewer"],
        json={"comment": "Standard clauses, approved."},
    )

    # a second version of an approved policy, a share and an archived document
    detail = api.ok("GET", f"/documents/{docs['leave']}", H["admin"])
    newer = make_pdf("Leave policy 2026 revision two: adds parental leave.")
    reserve = api.ok(
        "POST", f"/documents/{docs['leave']}/versions/uploads", H["admin"],
        json={"filename": "Leave Policy 2026 v2.pdf", "content_type": pdf, "size_bytes": len(newer),
              "based_on_version": detail["current_version_number"], "comment": "Added parental leave"},
    )  # fmt: skip
    assert api.c.put(f"/api/v1/documents/uploads/{reserve['version_id']}/content", content=newer, headers=H["admin"]).status_code == 200  # fmt: skip
    api.ok("POST", f"/documents/{docs['inv1']}/shares", H["employee"],
           json={"grantee_membership_id": mids["project"], "can_download": True})  # fmt: skip
    api.ok("POST", f"/documents/{docs['old']}/archive", H["admin"])
    api.ok("POST", "/search/index/run", H["admin"])
    return {"docs": docs, "tenant_id": str(world.tenant)}


def write_access_file(password: str, tenant_id: str) -> None:
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"| {desc} | `{local}@{DOMAIN}` | {name} |"
        for _k, (local, name, _r, desc) in PEOPLE.items()
    )
    ACCESS_FILE.write_text(
        f"""# DMS demo access (local only, do not commit or share)

Development-only demo accounts for the fictional organization **{ORG}**. They exist only in the
local demo database. Never reuse this password anywhere else.

- Web application: {WEB_URL}
- To start everything after a restart: run `start_demo.bat` from the repository root (Docker Desktop must be running).
- API (for reference): {API_URL}/docs
- Temporary password for every account below: `{password}`

| Role | Sign-in email | Person |
|---|---|---|
{rows}

## What each role can do
- **Organization Administrator**: everything, including users, roles, categories, organization, audit, hold and deletion approval. Also a *platform administrator*: sees the **Design catalogue** screen.
- **Department Manager (Finance)**: sees Finance documents (including confidential ones), reviews and archives.
- **Project Manager (Apollo ERP Rollout)**: sees Apollo project documents, reviews and archives; has a shared invoice.
- **Employee**: uploads, edits own documents, shares, requests deletion.
- **Reviewer**: decides items in the approval queue (a vendor agreement is waiting).

## Changing passwords
These are real sign-in accounts of a local database. The web application has no change-password screen yet. To set
your own password use **Forgot password** on the sign-in page: in development the reset link is printed in the API
console instead of being emailed. To rebuild the demo data from scratch, create a new database whose name contains `demo`, run the
migrations and run `scripts/seed_demo.py`.

Tenant id: `{tenant_id}`
""",
        encoding="utf-8",
    )


def seed_designs() -> None:
    """Publish the five designs and make the demo administrator a platform administrator."""
    report = seed_directory(ROOT.parents[1] / "design-showcase" / "templates")
    assert not report["failed"], report["failed"]
    with Session(get_engine()) as db, db.begin():
        grant_platform_admin(db, f"{PEOPLE['admin'][0]}@{DOMAIN}")


def main() -> None:
    guard()
    password = "Demo-" + secrets.token_urlsafe(12) + "9!"
    world = create_people(password)
    with TestClient(app) as client:
        result = seed(Api(client, password), world)
    seed_designs()
    write_access_file(password, result["tenant_id"])
    print(
        f"Seeded {ORG}: {len(result['docs'])} documents, {len(PEOPLE)} accounts. Access file written."
    )


if __name__ == "__main__":
    main()
