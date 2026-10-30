# ruff: noqa: F811
import pytest
from sqlalchemy import text

from app.db.tenant_session import tenant_session
from app.services import rbac
from tests.test_rbac import auth, env  # noqa: F401  (fixtures)


@pytest.fixture
def admin(env):
    return auth(env, "admin-a@x.test")


@pytest.fixture
def employee(env):
    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    return auth(env, "emp-a@x.test")


def make(env, h, name, parent=None, **extra):
    body = {"name": name, **({"parent_id": parent} if parent else {}), **extra}
    r = env.client.post("/api/v1/categories", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def patch(env, h, cid, **body):
    return env.client.patch(f"/api/v1/categories/{cid}", json=body, headers=h)


# ---- categories -------------------------------------------------------------------------


def test_create_tree_with_paths_and_default_version(env, admin):
    hr = make(env, admin, "HR", default_classification="confidential")
    emp = make(env, admin, "Employee Records", hr["id"])
    con = make(env, admin, "Employment Contracts", emp["id"])
    assert (con["path"], con["depth"]) == ("HR > Employee Records > Employment Contracts", 3)
    assert hr["version"]["version_number"] == 1 and hr["default_classification"] == "confidential"
    assert hr["version"]["approval_required"] is False and hr["version"]["fields"] == []
    listed = env.client.get("/api/v1/categories", headers=admin).json()
    assert [c["path"] for c in listed] == [
        "HR", "HR > Employee Records", "HR > Employee Records > Employment Contracts"]  # fmt: skip


def test_names_unique_per_level_case_insensitive(env, admin):
    a = make(env, admin, "Finance")
    r = env.client.post("/api/v1/categories", json={"name": "FINANCE"}, headers=admin)
    assert r.status_code == 409
    make(env, admin, "Invoices", a["id"])
    make(env, admin, "Invoices")  # same name at a different level is fine
    r = env.client.post(
        "/api/v1/categories", json={"name": "invoices", "parent_id": a["id"]}, headers=admin
    )
    assert r.status_code == 409


def test_depth_cycle_and_inactive_parent_rules(env, admin, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "CATEGORY_MAX_DEPTH", 3)
    a = make(env, admin, "A")
    b = make(env, admin, "B", a["id"])
    c = make(env, admin, "C", b["id"])
    too_deep = env.client.post(
        "/api/v1/categories", json={"name": "D", "parent_id": c["id"]}, headers=admin
    )
    assert too_deep.status_code == 422 and "3 levels" in too_deep.json()["detail"]
    assert patch(env, admin, a["id"], parent_id=c["id"]).status_code == 422  # cycle
    assert patch(env, admin, a["id"], parent_id=a["id"]).status_code == 422
    other = make(env, admin, "Other")
    assert patch(env, admin, other["id"], parent_id=c["id"]).status_code == 422  # would be level 4
    assert patch(env, admin, c["id"], parent_id=other["id"]).status_code == 200  # move subtree
    assert patch(env, admin, c["id"], parent_id=None).json()["path"] == "C"  # to the top
    r = env.client.post(
        "/api/v1/categories",
        json={"name": "X", "parent_id": "00000000-0000-0000-0000-000000000001"},
        headers=admin,
    )
    assert r.status_code == 422


def test_deactivate_rules_and_no_delete(env, admin):
    parent = make(env, admin, "Legal")
    child = make(env, admin, "Contracts", parent["id"])
    assert patch(env, admin, parent["id"], status="inactive").status_code == 409  # has active child
    assert patch(env, admin, child["id"], status="inactive").json()["status"] == "inactive"
    assert patch(env, admin, parent["id"], status="inactive").status_code == 200
    assert patch(env, admin, child["id"], status="active").status_code == 409  # parent is off
    r = env.client.post(
        "/api/v1/categories", json={"name": "New", "parent_id": parent["id"]}, headers=admin
    )
    assert r.status_code == 422  # cannot add under an inactive category
    assert env.client.delete(f"/api/v1/categories/{parent['id']}", headers=admin).status_code == 405
    inactive = env.client.get(
        "/api/v1/categories", params={"status": "inactive"}, headers=admin
    ).json()
    assert {c["name"] for c in inactive} == {"Legal", "Contracts"}


def test_rename_and_classification_change_are_audited(env, admin):
    c = make(env, admin, "Sales")
    r = patch(env, admin, c["id"], name="Sales & Marketing", default_classification="public")
    assert (
        r.json()["name"] == "Sales & Marketing" and r.json()["default_classification"] == "public"
    )
    assert patch(env, admin, c["id"], default_classification="secret").status_code == 422
    assert patch(env, admin, c["id"], bogus=1).status_code == 422
    log = [
        e["action"]
        for e in env.client.get("/api/v1/audit-events", params={"limit": 100}, headers=admin).json()
    ]
    assert "taxonomy.category.created" in log and "taxonomy.category.updated" in log


# ---- versions: policy and metadata schema -----------------------------------------------

POLICY = {
    "approval_required": True,
    "required_dimensions": ["department", "project"],
    "allowed_extensions": ["PDF", ".docx"],
    "retention_days": 2555,
    "review_interval_days": 365,
    "reminder_days": [7, 30, 0, 7],
}
FIELDS = [
    {"key": "invoice_no", "label": "Invoice number", "field_type": "text", "required": True,
     "validation": {"pattern": r"INV-\d+"}, "display_order": 1},
    {"key": "amount", "label": "Amount", "field_type": "decimal", "validation": {"precision": 2}, "display_order": 2},
    {"key": "status", "label": "Status", "field_type": "single_select",
     "validation": {"options": ["open", "paid"]}, "default_value": "open", "display_order": 3},
]  # fmt: skip


def test_policy_and_fields_are_stored_normalized(env, admin):
    c = make(env, admin, "Invoices", policy=POLICY, fields=FIELDS)
    v = c["version"]
    assert v["approval_required"] is True
    assert v["required_dimensions"] == ["department", "project"]
    assert v["allowed_extensions"] == ["docx", "pdf"]
    assert v["reminder_days"] == [30, 7, 0]
    assert [f["key"] for f in v["fields"]] == ["invoice_no", "amount", "status"]
    assert v["fields"][0]["required"] is True and v["fields"][2]["default_value"] == "open"


@pytest.mark.parametrize(
    "policy",
    [
        {"required_dimensions": ["team"]},
        {"allowed_extensions": ["not an ext"]},
        {"retention_days": 0},
        {"reminder_days": [400]},
        {"expiry_action": "delete"},
    ],
)
def test_invalid_policies_are_rejected(env, admin, policy):
    r = env.client.post("/api/v1/categories", json={"name": "P", "policy": policy}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"]
    assert env.client.get("/api/v1/categories", headers=admin).json() == []  # nothing half-created


def test_invalid_fields_report_per_field_errors(env, admin):
    fields = [{"key": "Bad Key", "label": "x", "field_type": "text"}]
    r = env.client.post("/api/v1/categories", json={"name": "F", "fields": fields}, headers=admin)
    assert r.status_code == 422 and "key" in r.json()["detail"]["fields"]
    dup = [{"key": "a", "label": "A", "field_type": "text"}] * 2
    r = env.client.post("/api/v1/categories", json={"name": "F", "fields": dup}, headers=admin)
    assert "unique" in r.json()["detail"]["fields"]["_"]
    extra = [{"key": "a", "label": "A", "field_type": "text", "surprise": 1}]
    assert (
        env.client.post(
            "/api/v1/categories", json={"name": "F", "fields": extra}, headers=admin
        ).status_code
        == 422
    )


def test_new_version_keeps_history_immutable(env, admin):
    c = make(env, admin, "Contracts", policy={"retention_days": 100}, fields=FIELDS[:1])
    cid = c["id"]
    v2 = env.client.post(
        f"/api/v1/categories/{cid}/versions",
        json={"policy": {"approval_required": True, "retention_days": 200}, "fields": FIELDS},
        headers=admin,
    )
    assert (
        v2.status_code == 201 and v2.json()["version_number"] == 2 and len(v2.json()["fields"]) == 3
    )
    current = env.client.get(f"/api/v1/categories/{cid}", headers=admin).json()
    assert current["current_version_number"] == 2 and current["version"]["retention_days"] == 200
    old = env.client.get(f"/api/v1/categories/{cid}", params={"version": 1}, headers=admin).json()
    assert old["version"]["retention_days"] == 100 and len(old["version"]["fields"]) == 1
    versions = env.client.get(f"/api/v1/categories/{cid}/versions", headers=admin).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert (
        env.client.get(
            f"/api/v1/categories/{cid}", params={"version": 9}, headers=admin
        ).status_code
        == 404
    )
    log = [
        e
        for e in env.client.get("/api/v1/audit-events", params={"limit": 100}, headers=admin).json()
    ]
    assert any(
        e["action"] == "taxonomy.category.version_created" and e["details"]["version"] == 2
        for e in log
    )


def test_versions_cannot_be_altered_even_by_buggy_code(env, admin):
    c = make(env, admin, "Locked", fields=FIELDS[:1])
    with env.engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE dms_app"))
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(env.ta)})
        for sql in (
            "UPDATE category_versions SET retention_days = 1",
            "DELETE FROM category_versions",
            "UPDATE metadata_field_definitions SET label = 'x'",
            "DELETE FROM metadata_field_definitions",
        ):
            with pytest.raises(Exception, match="permission denied"), conn.begin_nested():
                conn.execute(text(sql))
    assert env.client.get(f"/api/v1/categories/{c['id']}", headers=admin).status_code == 200


def test_inactive_category_cannot_get_new_versions(env, admin):
    c = make(env, admin, "Old")
    patch(env, admin, c["id"], status="inactive")
    r = env.client.post(f"/api/v1/categories/{c['id']}/versions", json={}, headers=admin)
    assert r.status_code == 409


# ---- permissions and isolation ----------------------------------------------------------


def test_employees_read_but_cannot_change_taxonomy(env, admin, employee):
    c = make(env, admin, "Public Policies")
    assert len(env.client.get("/api/v1/categories", headers=employee).json()) == 1
    assert env.client.get(f"/api/v1/categories/{c['id']}", headers=employee).status_code == 200
    assert (
        env.client.post("/api/v1/categories", json={"name": "X"}, headers=employee).status_code
        == 403
    )
    assert patch(env, employee, c["id"], name="Y").status_code == 403
    assert (
        env.client.post(
            f"/api/v1/categories/{c['id']}/versions", json={}, headers=employee
        ).status_code
        == 403
    )
    assert env.client.get("/api/v1/categories").status_code == 401
    assert "date" in env.client.get("/api/v1/metadata/field-types", headers=employee).json()


def test_tenants_cannot_see_or_touch_each_others_categories(env, admin):
    c = make(env, admin, "Secret Plans", fields=FIELDS)
    b_admin = auth(env, "admin-b@x.test")
    assert env.client.get("/api/v1/categories", headers=b_admin).json() == []
    assert env.client.get(f"/api/v1/categories/{c['id']}", headers=b_admin).status_code == 404
    assert patch(env, b_admin, c["id"], name="hack").status_code == 404
    assert (
        env.client.get(f"/api/v1/categories/{c['id']}/versions", headers=b_admin).status_code == 404
    )
    assert (
        env.client.post(
            f"/api/v1/categories/{c['id']}/versions", json={}, headers=b_admin
        ).status_code
        == 404
    )
    mine = env.client.post("/api/v1/categories", json={"name": "Secret Plans"}, headers=b_admin)
    assert mine.status_code == 201  # same name is fine in another tenant
    foreign_parent = env.client.post(
        "/api/v1/categories", json={"name": "Child", "parent_id": c["id"]}, headers=b_admin
    )
    assert foreign_parent.status_code == 422


# ---- tags -------------------------------------------------------------------------------


def test_system_tags_are_seeded_and_immutable(env, admin):
    tags = env.client.get("/api/v1/tags", params={"kind": "system"}, headers=admin).json()
    assert {t["name"] for t in tags} == {"Pending", "Approved", "Archived"}
    tid = tags[0]["id"]
    assert (
        env.client.patch(f"/api/v1/tags/{tid}", json={"name": "Renamed"}, headers=admin).status_code
        == 422
    )
    assert (
        env.client.patch(
            f"/api/v1/tags/{tid}", json={"status": "inactive"}, headers=admin
        ).status_code
        == 422
    )
    r = env.client.post(
        "/api/v1/tags", json={"name": "approved", "kind": "standard"}, headers=admin
    )
    assert (
        r.status_code == 200 and r.json()["kind"] == "system"
    )  # reuses the existing tag, never a duplicate


def test_standard_and_employee_tag_rules(env, admin, employee):
    std = env.client.post(
        "/api/v1/tags", json={"name": "Quarterly", "kind": "standard"}, headers=admin
    )
    assert std.status_code == 201
    assert (
        env.client.post(
            "/api/v1/tags", json={"name": "Mine", "kind": "standard"}, headers=employee
        ).status_code
        == 403
    )
    mine = env.client.post(
        "/api/v1/tags", json={"name": "  Budget   2026 ", "kind": "employee"}, headers=employee
    )
    assert mine.status_code == 201 and mine.json()["name"] == "Budget 2026"
    again = env.client.post(
        "/api/v1/tags", json={"name": "BUDGET 2026", "kind": "employee"}, headers=employee
    )
    assert (
        again.status_code == 200 and again.json()["id"] == mine.json()["id"]
    )  # converge on one label
    for bad in ("", "x" * 81, "bad\x07name"):
        assert (
            env.client.post(
                "/api/v1/tags", json={"name": bad, "kind": "employee"}, headers=employee
            ).status_code
            == 422
        )
    unicode_tag = env.client.post(
        "/api/v1/tags", json={"name": "करार २०२६", "kind": "employee"}, headers=employee
    )
    assert unicode_tag.status_code == 201
    assert (
        env.client.patch(
            f"/api/v1/tags/{mine.json()['id']}", json={"name": "x"}, headers=employee
        ).status_code
        == 403
    )


def test_employee_tag_policy_can_be_switched_off(env, admin, employee):
    assert env.client.get("/api/v1/tags/policy", headers=admin).json() == {
        "allow_employee_tags": True
    }
    assert env.client.get("/api/v1/tags/policy", headers=employee).status_code == 403
    assert (
        env.client.put(
            "/api/v1/tags/policy", json={"allow_employee_tags": False}, headers=employee
        ).status_code
        == 403
    )
    assert (
        env.client.put(
            "/api/v1/tags/policy", json={"allow_employee_tags": False}, headers=admin
        ).status_code
        == 200
    )
    r = env.client.post("/api/v1/tags", json={"name": "Nope", "kind": "employee"}, headers=employee)
    assert r.status_code == 409
    assert (
        env.client.post(
            "/api/v1/tags", json={"name": "Still ok", "kind": "standard"}, headers=admin
        ).status_code
        == 201
    )


def test_tag_lifecycle_isolation_and_audit(env, admin):
    t = env.client.post(
        "/api/v1/tags", json={"name": "Legal Hold Review", "kind": "standard"}, headers=admin
    ).json()
    assert (
        env.client.patch(
            f"/api/v1/tags/{t['id']}", json={"name": "Legal Review"}, headers=admin
        ).json()["name"]
        == "Legal Review"
    )
    off = env.client.patch(f"/api/v1/tags/{t['id']}", json={"status": "inactive"}, headers=admin)
    assert off.json()["status"] == "inactive"
    revived = env.client.post(
        "/api/v1/tags", json={"name": "legal review", "kind": "standard"}, headers=admin
    )
    assert revived.status_code == 409  # switched off: administrator must reactivate
    b_admin = auth(env, "admin-b@x.test")
    assert (
        env.client.patch(
            f"/api/v1/tags/{t['id']}", json={"status": "active"}, headers=b_admin
        ).status_code
        == 404
    )
    names_b = {x["name"] for x in env.client.get("/api/v1/tags", headers=b_admin).json()}
    assert "Legal Review" not in names_b and {"Pending", "Approved", "Archived"} <= names_b
    log = [
        e["action"]
        for e in env.client.get("/api/v1/audit-events", params={"limit": 100}, headers=admin).json()
    ]
    assert {"taxonomy.tag.created", "taxonomy.tag.updated", "taxonomy.tag.deactivated"} <= set(log)
