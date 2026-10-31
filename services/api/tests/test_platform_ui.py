# ruff: noqa: F811
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import platform_admin
from app.db.tenant_session import auth_session, platform_session, tenant_session
from app.ui import service
from app.ui.seed import seed_directory
from tests.test_rbac import auth, env  # noqa: F401  (fixtures)

TEMPLATES = Path(__file__).resolve().parents[3] / "design-showcase" / "templates"
BASE = "/api/v1/platform/ui-templates"


def sample(base="modern-enterprise", **over):
    t = json.loads((TEMPLATES / f"{base}.json").read_text("utf-8"))
    t.update(over)
    return t


def post(env, h, path, body, **params):
    data = body if isinstance(body, (str, bytes)) else json.dumps(body)
    return env.client.post(
        f"{BASE}{path}",
        content=data,
        headers={**h, "Content-Type": "application/json"},
        params=params,
    )


@pytest.fixture
def world(env):
    """Alpha administrator is a platform administrator; Alpha employee and Beta administrator are not."""
    with Session(env.engine) as s, s.begin():
        assert platform_admin.grant(s, "admin-a@x.test") == "granted"
    env.pa = auth(env, "admin-a@x.test")
    env.emp = auth(env, "emp-a@x.test")
    env.other_admin = auth(env, "admin-b@x.test")
    return env


# ---- who may use it ---------------------------------------------------------------------


def test_only_platform_administrators_can_manage_templates(world):
    env = world
    for h in (
        env.emp,
        env.other_admin,
    ):  # an organization administrator is not a platform administrator
        assert env.client.get(BASE, headers=h).status_code == 403
        assert post(env, h, "/import", sample()).status_code == 403
        assert post(env, h, "/validate", sample()).status_code == 403
    assert env.client.get(BASE).status_code == 401
    assert post(env, {}, "/import", sample()).status_code == 401
    assert env.client.get(BASE, headers=env.pa).status_code == 200


def test_me_endpoint_tells_the_web_app_whether_to_show_the_screen(world):
    env = world

    def got(h):
        return env.client.get("/api/v1/me/platform-admin", headers=h).json()

    assert got(env.pa) == {"is_platform_admin": True}
    assert got(env.emp) == {"is_platform_admin": False}


def test_a_revoked_or_disabled_administrator_loses_access_at_once(world):
    env = world
    with Session(env.engine) as s, s.begin():
        platform_admin.grant(s, "emp-a@x.test")
    other = auth(env, "emp-a@x.test")
    assert env.client.get(BASE, headers=other).status_code == 200
    with Session(env.engine) as s, s.begin():
        assert platform_admin.revoke(s, "emp-a@x.test") == "revoked"
    assert env.client.get(BASE, headers=other).status_code == 403  # same token, no new sign-in
    with Session(env.engine) as s, s.begin():
        platform_admin.grant(s, "emp-a@x.test")
    with env.engine.begin() as c:
        c.execute(text("UPDATE users SET status = 'disabled' WHERE email = 'emp-a@x.test'"))
    assert env.client.get(BASE, headers=other).status_code in (401, 403)


def test_two_step_verification_is_required_when_configured(world, monkeypatch):
    env = world
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "PLATFORM_ADMIN_REQUIRE_MFA", True)
    r = env.client.get(BASE, headers=env.pa)
    assert r.status_code == 403 and "two-step" in r.json()["detail"]
    with env.engine.begin() as c:
        c.execute(text("UPDATE users SET mfa_enabled = true WHERE email = 'admin-a@x.test'"))
    assert env.client.get(BASE, headers=env.pa).status_code == 200


# ---- the operator command ---------------------------------------------------------------


def test_command_rules(env):
    with Session(env.engine) as s, s.begin():
        assert platform_admin.listing(s) == []
        assert platform_admin.grant(s, "Admin-A@x.test") == "granted"  # case-insensitive
        assert platform_admin.grant(s, "admin-a@x.test") == "already an administrator"
        with pytest.raises(LookupError):
            platform_admin.grant(s, "nobody@x.test")
        with pytest.raises(ValueError):
            platform_admin.revoke(s, "admin-a@x.test")  # the last one is protected
        platform_admin.grant(s, "emp-a@x.test")
        assert platform_admin.revoke(s, "admin-a@x.test") == "revoked"
        assert platform_admin.revoke(s, "admin-a@x.test") == "not an administrator"
        assert platform_admin.grant(s, "admin-a@x.test") == "granted again"
        assert platform_admin.listing(s) == ["admin-a@x.test", "emp-a@x.test"]


def test_application_roles_cannot_change_the_administrator_list(world):
    env = world
    sessions = (
        tenant_session(env.ta, env.engine),
        auth_session(env.engine),
        platform_session(env.engine),
    )
    for session in sessions:
        with pytest.raises(DBAPIError), session as db:
            db.execute(
                text(
                    "INSERT INTO platform_admins(user_id) SELECT id FROM users LIMIT 1 ON CONFLICT DO NOTHING"
                )
            )


# ---- import, publish, archive -----------------------------------------------------------


def test_import_validate_publish_and_archive_flow_without_redeploy(world):
    env = world
    mid = sample("premium-dark", key="midnight", name="Midnight")
    check = post(env, env.pa, "/validate", mid).json()
    assert (
        check["valid"]
        and check["outcome"] == "new_template"
        and check["name"] == "Midnight"
        and check["description"]
    )
    saved = post(env, env.pa, "/import", mid)
    assert saved.status_code == 201 and saved.json()["status"] == "draft"
    tid = saved.json()["id"]

    def emp_cards():
        return {
            c["key"]
            for c in env.client.get("/api/v1/ui-templates/available", headers=env.emp).json()
        }

    assert "midnight" not in emp_cards()  # not visible until published
    pub = env.client.post(f"{BASE}/{tid}/publish", headers=env.pa)
    assert pub.status_code == 200 and pub.json()["status"] == "published"
    assert "midnight" in emp_cards()  # a sixth design, no rebuild, no deployment
    chosen = env.client.put("/api/v1/me/ui-preferences", json={"template_id": tid}, headers=env.emp)
    assert chosen.json()["effective"]["template"]["key"] == "midnight"
    arch = env.client.post(f"{BASE}/{tid}/archive", headers=env.pa)
    assert arch.json()["status"] == "archived" and "midnight" not in emp_cards()
    assert env.client.post(f"{BASE}/{tid}/publish", headers=env.pa).status_code == 409
    after = env.client.get("/api/v1/me/ui-preferences", headers=env.emp).json()["effective"]
    assert after["source"] in ("product", "system")  # the withdrawn design is no longer applied


def test_sixth_template_import_with_publish_flag(world):
    env = world
    seed_directory(TEMPLATES, engine=env.engine)
    r = post(
        env,
        env.pa,
        "/import",
        sample("modern-saas", key="sixth-design", name="Sixth Design"),
        publish="true",
    )
    assert r.status_code == 201 and r.json()["status"] == "published"
    assert len(env.client.get("/api/v1/ui-templates/available", headers=env.emp).json()) == 6


def test_versions_are_preserved_and_unique_keys_enforced(world):
    env = world
    first = post(env, env.pa, "/import", sample(), publish="true").json()
    assert post(env, env.pa, "/import", sample()).status_code == 409
    check = post(env, env.pa, "/validate", sample()).json()
    assert (
        not check["valid"]
        and check["outcome"] == "conflict"
        and check["current_version"] == "1.0.0"
    )
    newer = post(env, env.pa, "/import", sample(version="1.1.0", name="Modern Enterprise Plus"))
    assert (
        newer.status_code == 201
        and newer.json()["id"] == first["id"]
        and newer.json()["status"] == "draft"
    )
    env.client.post(f"{BASE}/{first['id']}/publish", headers=env.pa)
    versions = env.client.get(f"{BASE}/{first['id']}/versions", headers=env.pa).json()
    assert [v["version"] for v in versions] == ["1.1.0", "1.0.0"] and all(
        v["published_at"] for v in versions
    )
    detail = env.client.get(f"{BASE}/{first['id']}", headers=env.pa).json()
    assert detail["version"] == "1.1.0" and detail["config"]["name"] == "Modern Enterprise Plus"
    published = env.client.get(BASE, headers=env.pa, params={"status": "published"}).json()
    assert [t["key"] for t in published] == ["modern-enterprise"]


def test_invalid_uploads_are_rejected_safely(world):
    env = world
    bad = sample()
    bad["theme"]["colors"]["primary"] = "url(https://evil.example/x)"
    bad["name"] = "<script>alert(1)</script>"
    r = post(env, env.pa, "/import", bad)
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) >= 2
    assert post(env, env.pa, "/validate", bad).json()["valid"] is False
    assert post(env, env.pa, "/import", "{ not json").status_code == 422
    assert post(env, env.pa, "/import", "[]").status_code == 422
    assert post(env, env.pa, "/import", b"\xff\xfe").status_code == 422
    assert post(env, env.pa, "/import", " " * (64 * 1024 + 1)).status_code == 413
    assert env.client.get(BASE, headers=env.pa).json() == []  # nothing was saved


def test_unknown_and_tenant_owned_ids_are_not_found(world):
    env = world
    zero = "00000000-0000-0000-0000-000000000000"
    assert env.client.get(f"{BASE}/{zero}", headers=env.pa).status_code == 404
    assert env.client.post(f"{BASE}/{zero}/publish", headers=env.pa).status_code == 404
    with platform_session(env.engine) as db:
        t = service.import_platform_template(db, sample("modern-saas"), publish=True)
        db.execute(
            text("UPDATE ui_templates SET scope='tenant', tenant_id=:t WHERE id=:i"),
            {"t": env.ta, "i": t.id},
        )
        tenant_template = str(t.id)
    assert env.client.get(f"{BASE}/{tenant_template}", headers=env.pa).status_code == 404
    assert env.client.get(f"{BASE}/{tenant_template}/versions", headers=env.pa).status_code == 404


def test_every_platform_action_is_audited_as_privileged(world):
    env = world
    saved = post(env, env.pa, "/import", sample(), publish="true").json()
    env.client.post(f"{BASE}/{saved['id']}/archive", headers=env.pa)
    log = env.client.get("/api/v1/audit-events", params={"limit": 100}, headers=env.pa).json()
    actions = {e["action"]: e for e in log if e["action"].startswith("platform.ui_template.")}
    assert {"platform.ui_template.imported", "platform.ui_template.archived"} <= set(actions)
    assert all(e["privileged"] for e in actions.values())
    assert actions["platform.ui_template.imported"]["details"]["key"] == "modern-enterprise"
