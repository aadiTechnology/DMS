# ruff: noqa: F811
import uuid

import pytest
from sqlalchemy import text

from app.db.tenant_session import tenant_session
from app.services import rbac
from tests.test_rbac import _member, _user, auth, env  # noqa: F401  (fixtures)


@pytest.fixture
def admin(env):
    return auth(env, "admin-a@x.test")


@pytest.fixture
def employee(env):
    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    return auth(env, "emp-a@x.test")


def make(env, headers, kind, **body):
    r = env.client.post(f"/api/v1/org/{kind}", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def actions(env, headers, **params):
    r = env.client.get("/api/v1/audit-events", params={"limit": 200, **params}, headers=headers)
    return [e["action"] for e in r.json()]


def test_department_lifecycle_and_no_delete(env, admin):
    d = make(env, admin, "departments", name="Finance", code="FIN")
    assert d["status"] == "active" and d["code"] == "FIN"
    r = env.client.patch(
        f"/api/v1/org/departments/{d['id']}", json={"name": "Finance & Accounts"}, headers=admin
    )
    assert r.status_code == 200 and r.json()["name"] == "Finance & Accounts"
    r = env.client.patch(
        f"/api/v1/org/departments/{d['id']}", json={"status": "inactive"}, headers=admin
    )
    assert r.json()["status"] == "inactive"
    listed = env.client.get(
        "/api/v1/org/departments", params={"status": "inactive"}, headers=admin
    ).json()
    assert [x["id"] for x in listed] == [d["id"]]
    assert env.client.delete(f"/api/v1/org/departments/{d['id']}", headers=admin).status_code == 405
    r = env.client.patch(
        f"/api/v1/org/departments/{d['id']}", json={"status": "active"}, headers=admin
    )
    assert r.json()["status"] == "active"
    log = actions(env, admin)
    for a in (
        "org.department.created",
        "org.department.updated",
        "org.department.deactivated",
        "org.department.reactivated",
    ):
        assert a in log


def test_duplicates_and_validation(env, admin):
    make(env, admin, "branches", name="Pune", code="PUN")
    for body in ({"name": "Pune", "code": "X1"}, {"name": "Other", "code": "PUN"}):
        assert env.client.post("/api/v1/org/branches", json=body, headers=admin).status_code == 409
    assert (
        env.client.post("/api/v1/org/branches", json={"name": "NoCode"}, headers=admin).status_code
        == 422
    )
    assert (
        env.client.post(
            "/api/v1/org/branches", json={"name": " ", "code": "Z"}, headers=admin
        ).status_code
        == 422
    )
    assert (
        env.client.post(
            "/api/v1/org/branches", json={"name": "A", "code": "A", "bogus": 1}, headers=admin
        ).status_code
        == 422
    )
    # field not supported by this kind
    r = env.client.post(
        "/api/v1/org/branches",
        json={"name": "B", "code": "B", "parent_id": str(uuid.uuid4())},
        headers=admin,
    )
    assert r.status_code == 422
    assert env.client.get("/api/v1/org/nonsense", headers=admin).status_code == 422
    assert (
        env.client.get("/api/v1/org/branches", params={"limit": 500}, headers=admin).status_code
        == 422
    )


def test_designations_and_projects_create(env, admin):
    assert make(env, admin, "designations", name="Accountant")["code"] is None
    assert make(env, admin, "projects", name="Apollo", code="APO")["status"] == "active"


def test_employee_can_read_structure_but_not_change_it(env, admin, employee):
    make(env, admin, "departments", name="HR", code="HR")
    assert len(env.client.get("/api/v1/org/departments", headers=employee).json()) == 1
    assert (
        env.client.post(
            "/api/v1/org/departments", json={"name": "X", "code": "X"}, headers=employee
        ).status_code
        == 403
    )
    assert env.client.get("/api/v1/employees", headers=employee).status_code == 403
    assert env.client.get("/api/v1/org/departments").status_code == 401


def test_department_hierarchy_rules(env, admin):
    a = make(env, admin, "departments", name="A", code="A")
    b = make(env, admin, "departments", name="B", code="B", parent_id=a["id"])
    c = make(env, admin, "departments", name="C", code="C", parent_id=b["id"])
    patch = lambda i, body: env.client.patch(
        f"/api/v1/org/departments/{i}", json=body, headers=admin
    )
    assert patch(a["id"], {"parent_id": c["id"]}).status_code == 422  # cycle
    assert patch(a["id"], {"parent_id": a["id"]}).status_code == 422  # self
    patch(c["id"], {"status": "inactive"})
    r = env.client.post(
        "/api/v1/org/departments",
        json={"name": "D", "code": "D", "parent_id": c["id"]},
        headers=admin,
    )
    assert r.status_code == 422  # inactive parent
    assert patch(a["id"], {"parent_id": str(uuid.uuid4())}).status_code == 422


def test_manager_must_be_active_member_of_this_tenant(env, admin):
    ok = env.client.post(
        "/api/v1/org/projects",
        json={"name": "P", "code": "P", "manager_membership_id": str(env.mem_emp)},
        headers=admin,
    )
    assert ok.status_code == 201
    foreign = env.client.post(
        "/api/v1/org/projects",
        json={"name": "Q", "code": "Q", "manager_membership_id": str(env.mem_admin_b)},
        headers=admin,
    )
    assert foreign.status_code == 422
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE tenant_memberships SET status='inactive' WHERE id=:i"), {"i": env.mem_emp}
        )
    gone = env.client.post(
        "/api/v1/org/projects",
        json={"name": "R", "code": "R", "manager_membership_id": str(env.mem_emp)},
        headers=admin,
    )
    assert gone.status_code == 422


def test_tenants_cannot_see_or_touch_each_other(env, admin):
    d = make(env, admin, "departments", name="Secret", code="SEC")
    b_admin = auth(env, "admin-b@x.test")
    assert env.client.get("/api/v1/org/departments", headers=b_admin).json() == []
    assert (
        env.client.patch(
            f"/api/v1/org/departments/{d['id']}", json={"name": "hack"}, headers=b_admin
        ).status_code
        == 404
    )
    same_name = env.client.post(
        "/api/v1/org/departments", json={"name": "Secret", "code": "SEC"}, headers=b_admin
    )
    assert same_name.status_code == 201  # uniqueness is per tenant
    r = env.client.put(
        f"/api/v1/employees/{env.mem_emp}/profile", json={"full_name": "x"}, headers=b_admin
    )
    assert r.status_code == 404
    assert env.client.get(f"/api/v1/employees/{env.mem_emp}", headers=b_admin).status_code == 404
    r = env.client.put(
        f"/api/v1/employees/{env.mem_admin_a}/profile",
        json={"full_name": "A", "department_id": d["id"]},
        headers=auth(env, "admin-a@x.test"),
    )
    assert r.status_code == 200
    b_member = env.client.put(
        f"/api/v1/employees/{env.mem_admin_b}/profile",
        json={"full_name": "B", "department_id": d["id"]},
        headers=b_admin,
    )
    assert (
        b_member.status_code == 422
    )  # B has its own "Secret", but A's department id is not valid in B


def test_employee_profiles(env, admin):
    dep = make(env, admin, "departments", name="Sales", code="SAL")
    br = make(env, admin, "branches", name="Mumbai", code="MUM")
    des = make(env, admin, "designations", name="Manager")
    put = lambda mid, body: env.client.put(
        f"/api/v1/employees/{mid}/profile", json=body, headers=admin
    )
    assert (
        put(env.mem_emp, {"department_id": dep["id"]}).status_code == 422
    )  # full_name required first time
    r = put(
        env.mem_emp,
        {
            "full_name": "Asha Patil",
            "department_id": dep["id"],
            "branch_id": br["id"],
            "designation_id": des["id"],
            "work_email": "asha@example.com",
            "reporting_manager_membership_id": str(env.mem_admin_a),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["full_name"], body["department_id"], body["employment_status"]) == (
        "Asha Patil",
        dep["id"],
        "active",
    )
    r = put(env.mem_emp, {"employment_status": "on_leave"})  # partial update keeps the rest
    assert r.json()["employment_status"] == "on_leave" and r.json()["branch_id"] == br["id"]
    assert (
        put(env.mem_emp, {"reporting_manager_membership_id": str(env.mem_emp)}).status_code == 422
    )
    assert put(env.mem_emp, {"work_email": "not-an-email"}).status_code == 422
    assert put(env.mem_emp, {"department_id": str(uuid.uuid4())}).status_code == 422
    listed = env.client.get("/api/v1/employees", headers=admin).json()
    assert len(listed) == 2
    assert (
        next(e for e in listed if e["membership_id"] == str(env.mem_admin_a))["full_name"] is None
    )  # no profile yet
    only = env.client.get(
        "/api/v1/employees", params={"department_id": dep["id"]}, headers=admin
    ).json()
    assert [e["membership_id"] for e in only] == [str(env.mem_emp)]
    assert "org.employee_profile.updated" in actions(env, admin)


def test_deactivation_preserves_history_and_blocks_new_use(env, admin):
    dep = make(env, admin, "departments", name="Legacy", code="LEG")
    env.client.put(
        f"/api/v1/employees/{env.mem_emp}/profile",
        json={"full_name": "E", "department_id": dep["id"]},
        headers=admin,
    )
    env.client.patch(
        f"/api/v1/org/departments/{dep['id']}", json={"status": "inactive"}, headers=admin
    )
    kept = env.client.get(f"/api/v1/employees/{env.mem_emp}", headers=admin).json()
    assert kept["department_id"] == dep["id"]  # existing association untouched (ORG-005/008)
    ok = env.client.put(
        f"/api/v1/employees/{env.mem_emp}/profile", json={"full_name": "E2"}, headers=admin
    )
    assert ok.status_code == 200 and ok.json()["department_id"] == dep["id"]
    again = env.client.put(
        f"/api/v1/employees/{env.mem_admin_a}/profile",
        json={"full_name": "A", "department_id": dep["id"]},
        headers=admin,
    )
    assert again.status_code == 422  # cannot newly assign to an inactive department
    assert env.client.get("/api/v1/org/departments", headers=admin).json()[0]["id"] == dep["id"]


def test_project_membership_many_to_many_with_history(env, admin):
    p1 = make(env, admin, "projects", name="One", code="ONE")
    p2 = make(env, admin, "projects", name="Two", code="TWO")
    put = lambda p, m, body=None: env.client.put(
        f"/api/v1/projects/{p}/members/{m}", json=body or {}, headers=admin
    )
    assert put(p1["id"], env.mem_emp, {"project_role": "lead"}).status_code == 200
    assert put(p2["id"], env.mem_emp).status_code == 200  # same employee, second project
    assert put(p1["id"], env.mem_admin_b).status_code == 422  # not an employee of this tenant
    members = env.client.get(f"/api/v1/projects/{p1['id']}/members", headers=admin).json()
    assert [(m["membership_id"], m["project_role"]) for m in members] == [
        (str(env.mem_emp), "lead")
    ]
    assert (
        env.client.delete(
            f"/api/v1/projects/{p1['id']}/members/{env.mem_emp}", headers=admin
        ).status_code
        == 204
    )
    # ended today stays listed through today, so end it in the past via re-put to prove filtering
    put(p1["id"], env.mem_emp, {"starts_on": "2020-01-01", "ends_on": "2020-12-31"})
    assert env.client.get(f"/api/v1/projects/{p1['id']}/members", headers=admin).json() == []
    put(p1["id"], env.mem_emp, {"project_role": "member"})  # re-adding clears the end date
    assert len(env.client.get(f"/api/v1/projects/{p1['id']}/members", headers=admin).json()) == 1
    env.client.patch(f"/api/v1/org/projects/{p2['id']}", json={"status": "inactive"}, headers=admin)
    assert put(p2["id"], env.mem_admin_a).status_code == 422  # inactive project
    bad = put(p1["id"], env.mem_emp, {"starts_on": "2025-02-01", "ends_on": "2025-01-01"})
    assert bad.status_code == 422
    log = actions(env, admin)
    assert "org.project_member.set" in log and "org.project_member.ended" in log


def test_project_member_endpoints_deny_cross_tenant_and_unpermitted(env, admin, employee):
    p = make(env, admin, "projects", name="Priv", code="PRV")
    url = f"/api/v1/projects/{p['id']}/members"
    assert env.client.get(url, headers=employee).status_code == 403
    b_admin = auth(env, "admin-b@x.test")
    assert env.client.get(url, headers=b_admin).status_code == 404
    assert env.client.put(f"{url}/{env.mem_admin_b}", json={}, headers=b_admin).status_code == 404
    assert (
        env.client.delete(f"{url}/{env.mem_emp}", headers=admin).status_code == 404
    )  # never a member
