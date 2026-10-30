import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.permissions import DEFAULT_ROLES, PERMISSIONS
from app.core.security import hash_password
from app.db.models import Role
from app.db.tenant_session import tenant_session
from app.main import app
from app.services import rbac
from app.services.tenants import provision_tenant

PASSWORD = "correct-horse-battery"


def _user(c, email):
    q = text("INSERT INTO users(email,password_hash) VALUES (:e,:p) RETURNING id")
    return c.execute(q, {"e": email, "p": hash_password(PASSWORD)}).scalar()


def _member(c, tenant, user, status="active"):
    q = text(
        "INSERT INTO tenant_memberships(tenant_id,user_id,status) VALUES (:t,:u,:s) RETURNING id"
    )
    return c.execute(q, {"t": tenant, "u": user, "s": status}).scalar()


@pytest.fixture
def env(migrated_engine, monkeypatch):
    monkeypatch.setattr("app.db.tenant_session.get_engine", lambda: migrated_engine)
    ratelimit.auth_limiter._hits.clear()
    e = SimpleNamespace(engine=migrated_engine, client=TestClient(app))
    with migrated_engine.begin() as c:
        e.admin_a = _user(c, "admin-a@x.test")
        e.emp_a = _user(c, "emp-a@x.test")
        e.admin_b = _user(c, "admin-b@x.test")
    with Session(migrated_engine) as s, s.begin():
        e.ta = provision_tenant(s, "Alpha", e.admin_a)
        e.tb = provision_tenant(s, "Beta", e.admin_b)
    with migrated_engine.begin() as c:
        e.mem_emp = _member(c, e.ta, e.emp_a)
        e.mem_admin_a = c.execute(
            text("SELECT id FROM tenant_memberships WHERE user_id=:u"), {"u": e.admin_a}
        ).scalar()
        e.mem_admin_b = c.execute(
            text("SELECT id FROM tenant_memberships WHERE user_id=:u"), {"u": e.admin_b}
        ).scalar()
    with tenant_session(e.ta, migrated_engine) as s:
        e.roles_a = {r.name: r.id for r in s.scalars(select(Role))}
    with tenant_session(e.tb, migrated_engine) as s:
        e.roles_b = {r.name: r.id for r in s.scalars(select(Role))}
    return e


def auth(env, email):
    r = env.client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_provisioning_seeds_system_roles(env):
    with tenant_session(env.ta, env.engine) as s:
        roles = {r.name: sorted(p) for r, p in rbac.list_roles(s, env.ta)}
    assert set(roles) == set(DEFAULT_ROLES)
    assert roles["org_admin"] == sorted(PERMISSIONS)
    assert "admin.manage_users" not in roles["employee"]


def test_seed_is_idempotent(env):
    with tenant_session(env.ta, env.engine) as s:
        rbac.seed_default_roles(s, env.ta)
        assert len(rbac.list_roles(s, env.ta)) == len(DEFAULT_ROLES)


def test_effective_permissions_union_and_revocation(env):
    with tenant_session(env.ta, env.engine) as s:
        assert rbac.effective_permissions(s, env.ta, env.emp_a) == set()  # no role yet
        a1 = rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["reviewer"])
        perms = rbac.effective_permissions(s, env.ta, env.emp_a)
        assert {"document.download", "document.approve"} <= perms
        rbac.revoke_assignment(s, env.ta, env.admin_a, a1.id)
        perms = rbac.effective_permissions(s, env.ta, env.emp_a)
        assert "document.download" not in perms and "document.approve" in perms


def test_inactive_membership_or_role_grants_nothing(env):
    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE tenant_memberships SET status='inactive' WHERE id=:i"), {"i": env.mem_emp}
        )
    with tenant_session(env.ta, env.engine) as s:
        assert rbac.effective_permissions(s, env.ta, env.emp_a) == set()
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE tenant_memberships SET status='active' WHERE id=:i"), {"i": env.mem_emp}
        )
        c.execute(
            text("UPDATE roles SET status='inactive' WHERE id=:i"), {"i": env.roles_a["employee"]}
        )
    with tenant_session(env.ta, env.engine) as s:
        assert rbac.effective_permissions(s, env.ta, env.emp_a) == set()


def test_cannot_assign_role_or_member_from_another_tenant(env):
    with tenant_session(env.ta, env.engine) as s:
        with pytest.raises(rbac.NotFound):
            rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_b["employee"])
        with pytest.raises(rbac.NotFound):
            rbac.assign_role(s, env.ta, env.admin_a, env.mem_admin_b, env.roles_a["employee"])


def test_api_employee_forbidden_and_denial_audited(env):
    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    emp = auth(env, "emp-a@x.test")
    assert env.client.get("/api/v1/roles", headers=emp).status_code == 403
    assert env.client.get("/api/v1/audit-events", headers=emp).status_code == 403
    admin = auth(env, "admin-a@x.test")
    events = env.client.get(
        "/api/v1/audit-events", params={"action": "authz.denied"}, headers=admin
    )
    assert events.status_code == 200
    denied = events.json()
    assert len(denied) == 2 and {e["resource_id"] for e in denied} == {
        "admin.manage_users",
        "admin.view_audit",
    }
    assert all(e["outcome"] == "denied" for e in denied)


def test_api_unauthenticated_gets_401_not_403(env):
    assert env.client.get("/api/v1/roles").status_code == 401


def test_api_my_permissions(env):
    admin = auth(env, "admin-a@x.test")
    r = env.client.get("/api/v1/me/permissions", headers=admin)
    assert r.json()["permissions"] == sorted(PERMISSIONS)


def test_api_assign_and_revoke_are_audited(env):
    admin = auth(env, "admin-a@x.test")
    body = {"membership_id": str(env.mem_emp), "role_id": str(env.roles_a["employee"])}
    r = env.client.post("/api/v1/role-assignments", json=body, headers=admin)
    assert r.status_code == 201
    again = env.client.post("/api/v1/role-assignments", json=body, headers=admin)
    assert again.json()["id"] == r.json()["id"]  # idempotent
    emp = auth(env, "emp-a@x.test")
    assert (
        "document.upload"
        in env.client.get("/api/v1/me/permissions", headers=emp).json()["permissions"]
    )
    assert (
        env.client.delete(f"/api/v1/role-assignments/{r.json()['id']}", headers=admin).status_code
        == 204
    )
    # permission loss is immediate for the already-issued token
    assert env.client.get("/api/v1/me/permissions", headers=emp).json()["permissions"] == []
    actions = [e["action"] for e in env.client.get("/api/v1/audit-events", headers=admin).json()]
    assert "rbac.role_assigned" in actions and "rbac.role_revoked" in actions


def test_api_cross_tenant_ids_are_not_found(env):
    admin = auth(env, "admin-a@x.test")
    foreign_role = {"membership_id": str(env.mem_emp), "role_id": str(env.roles_b["employee"])}
    assert (
        env.client.post("/api/v1/role-assignments", json=foreign_role, headers=admin).status_code
        == 404
    )
    foreign_member = {
        "membership_id": str(env.mem_admin_b),
        "role_id": str(env.roles_a["employee"]),
    }
    assert (
        env.client.post("/api/v1/role-assignments", json=foreign_member, headers=admin).status_code
        == 404
    )
    # tenant B's admin assignment cannot be revoked or even seen from tenant A
    with tenant_session(env.tb, env.engine) as s:
        b_assignment = rbac.list_assignments(s, env.tb)[0].id
    assert (
        env.client.delete(f"/api/v1/role-assignments/{b_assignment}", headers=admin).status_code
        == 404
    )
    names = {r["name"] for r in env.client.get("/api/v1/roles", headers=admin).json()}
    assert names == set(DEFAULT_ROLES)


def test_last_administrator_cannot_be_removed(env):
    admin = auth(env, "admin-a@x.test")
    assignment = env.client.get("/api/v1/role-assignments", headers=admin).json()[0]["id"]
    r = env.client.delete(f"/api/v1/role-assignments/{assignment}", headers=admin)
    assert r.status_code == 409


def test_audit_is_tenant_scoped_paginated_and_validated(env):
    admin = auth(env, "admin-a@x.test")
    events = env.client.get("/api/v1/audit-events", params={"limit": 1}, headers=admin).json()
    assert len(events) == 1
    all_events = env.client.get("/api/v1/audit-events", headers=admin).json()
    assert "tenant.provisioned" in {e["action"] for e in all_events}
    assert all(e["details"].get("first_admin_user_id") != str(env.admin_b) for e in all_events)
    assert (
        env.client.get("/api/v1/audit-events", params={"limit": 500}, headers=admin).status_code
        == 422
    )


def test_authentication_events_are_audited(env):
    admin = auth(env, "admin-a@x.test")
    env.client.post("/api/v1/auth/logout", headers=admin)
    admin2 = auth(env, "admin-a@x.test")
    actions = [e["action"] for e in env.client.get("/api/v1/audit-events", headers=admin2).json()]
    assert actions.count("auth.login") == 2 and "auth.logout" in actions


def test_audit_log_is_append_only_for_app_role(env):
    with env.engine.begin() as c:
        c.execute(text("SET LOCAL ROLE dms_app"))
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(env.ta)})
        for sql in ("UPDATE audit_events SET action='x'", "DELETE FROM audit_events"):
            with pytest.raises(Exception, match="permission denied"), c.begin_nested():
                c.execute(text(sql))


def test_audit_rows_invisible_across_tenants(env):
    with tenant_session(env.tb, env.engine) as s:
        n = s.execute(
            text("SELECT count(*) FROM audit_events WHERE tenant_id = :t"), {"t": env.ta}
        ).scalar()
    assert n == 0


def test_permission_catalog_matches_typescript_contract():
    ts = (
        Path(__file__)
        .parents[3]
        .joinpath("packages/domain/src/permissions.ts")
        .read_text(encoding="utf-8")
    )
    assert tuple(re.findall(r'"([a-z_]+\.[a-z_]+)"', ts)) == PERMISSIONS
