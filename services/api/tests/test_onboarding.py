# ruff: noqa: F811
import re

import pytest
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.security import verify_password
from app.db.tenant_session import tenant_session
from app.services import email as email_service
from app.services import rbac
from tests.test_rbac import PASSWORD, auth, env  # noqa: F401  (fixtures)

GOOD = "a-Brand-new-passphrase-42"


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    monkeypatch.setattr(get_settings(), "EMAIL_BACKEND", "outbox")
    email_service.OUTBOX.clear()
    return email_service.OUTBOX


@pytest.fixture
def admin(env):
    return auth(env, "admin-a@x.test")


@pytest.fixture
def employee(env):
    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    return auth(env, "emp-a@x.test")


def token_from(message) -> str:
    return re.search(r"token=([\w-]+)", message.body).group(1)


def invite(env, admin, email="new@example.com", name="New Person", **extra):
    return env.client.post(
        "/api/v1/invitations", json={"email": email, "full_name": name, **extra}, headers=admin
    )


def accept(env, token, password=GOOD):
    return env.client.post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": password}
    )


def test_invitation_end_to_end(env, admin, outbox):
    r = invite(env, admin)
    assert r.status_code == 201
    body = r.json()
    assert (body["membership_status"], body["full_name"]) == ("invited", "New Person")
    assert len(outbox) == 1 and outbox[0].to == "new@example.com"
    token = token_from(outbox[0])
    # not able to sign in until the invitation is accepted
    assert (
        env.client.post(
            "/api/v1/auth/login", json={"email": "new@example.com", "password": GOOD}
        ).status_code
        == 401
    )
    assert [
        e["membership_id"] for e in env.client.get("/api/v1/invitations", headers=admin).json()
    ] == [body["membership_id"]]
    assert accept(env, token, "short").status_code == 422  # weak password; link stays usable
    ok = accept(env, token)
    assert ok.status_code == 200
    me = env.client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}
    )
    assert me.json()["tenant_id"] == str(env.ta)
    perms = env.client.get(
        "/api/v1/me/permissions", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}
    ).json()
    assert (
        "document.upload" in perms["permissions"]
        and "admin.manage_users" not in perms["permissions"]
    )
    assert accept(env, token).status_code == 400  # single use
    login = env.client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": GOOD}
    )
    assert login.status_code == 200
    assert env.client.get("/api/v1/invitations", headers=admin).json() == []
    log = [
        e["action"]
        for e in env.client.get("/api/v1/audit-events", params={"limit": 200}, headers=admin).json()
    ]
    assert "invitation.created" in log and "invitation.accepted" in log


def test_email_is_sent_only_after_the_data_is_committed(env, admin, monkeypatch):
    seen = {}

    def fake_send(messages):
        with env.engine.connect() as c:  # a different connection sees only committed data
            seen["membership"] = c.execute(
                text("SELECT count(*) FROM tenant_memberships WHERE status='invited'")
            ).scalar()
            seen["token"] = c.execute(
                text("SELECT count(*) FROM auth_tokens WHERE purpose='invite'")
            ).scalar()

    monkeypatch.setattr(email_service, "send", fake_send)
    assert invite(env, admin).status_code == 201
    assert seen == {"membership": 1, "token": 1}


def test_invitation_permissions_and_validation(env, admin, employee):
    assert invite(env, employee).status_code == 403
    assert (
        env.client.post(
            "/api/v1/invitations", json={"email": "x@example.com", "full_name": "X"}
        ).status_code
        == 401
    )
    assert invite(env, admin, email="not-an-email").status_code == 422
    assert (
        invite(env, admin, role_id=str(env.roles_b["employee"])).status_code == 422
    )  # other tenant's role
    assert invite(env, admin, email="emp-a@example.com").status_code == 201


def test_existing_active_member_cannot_be_invited_again(env, admin):
    assert invite(env, admin).status_code == 201
    token = token_from(email_service.OUTBOX[0])
    accept(env, token)
    assert invite(env, admin).status_code == 409


def test_invitation_never_overwrites_an_existing_password(env, admin):
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE users SET email='b-admin@example.com' WHERE id=:i"), {"i": env.admin_b}
        )
        before = c.execute(
            text("SELECT password_hash FROM users WHERE id=:i"), {"i": env.admin_b}
        ).scalar()
    email_service.OUTBOX.clear()
    assert invite(env, admin, email="b-admin@example.com", name="B Admin").status_code == 201
    r = accept(env, token_from(email_service.OUTBOX[0]), "attacker-chosen-pass-99")
    assert r.status_code == 200
    with env.engine.connect() as c:
        after = c.execute(
            text("SELECT password_hash FROM users WHERE id=:i"), {"i": env.admin_b}
        ).scalar()
    assert after == before and verify_password(after, PASSWORD)
    # the person can pick which organization to enter
    login = env.client.post(
        "/api/v1/auth/login", json={"email": "b-admin@example.com", "password": PASSWORD}
    )
    assert login.status_code == 409


def test_resend_revoke_and_expiry(env, admin, outbox):
    m = invite(env, admin).json()["membership_id"]
    first = token_from(outbox[0])
    assert env.client.post(f"/api/v1/invitations/{m}/resend", headers=admin).status_code == 202
    second = token_from(outbox[1])
    assert accept(env, first).status_code == 400  # older link replaced
    assert env.client.delete(f"/api/v1/invitations/{m}", headers=admin).status_code == 204
    assert accept(env, second).status_code == 400  # revoked
    assert env.client.delete(f"/api/v1/invitations/{m}", headers=admin).status_code == 404
    m2 = invite(env, admin, email="late@example.com").json()["membership_id"]
    with env.engine.begin() as c:
        c.execute(
            text(
                "UPDATE auth_tokens SET expires_at = now() - interval '1 minute' WHERE used_at IS NULL"
            )
        )
    assert accept(env, token_from(outbox[-1])).status_code == 400  # expired
    assert m2  # second invitation created fine


def test_invitations_are_tenant_isolated(env, admin):
    m = invite(env, admin).json()["membership_id"]
    b_admin = auth(env, "admin-b@x.test")
    assert env.client.get("/api/v1/invitations", headers=b_admin).json() == []
    assert env.client.post(f"/api/v1/invitations/{m}/resend", headers=b_admin).status_code == 404
    assert env.client.delete(f"/api/v1/invitations/{m}", headers=b_admin).status_code == 404


def test_tokens_are_stored_hashed_and_hidden_from_tenant_role(env, admin, outbox):
    invite(env, admin)
    raw = token_from(outbox[0])
    with env.engine.connect() as c:
        stored = c.execute(text("SELECT token_hash FROM auth_tokens")).scalar()
    assert raw not in stored and len(stored) == 64
    with env.engine.begin() as c:
        c.execute(text("SET LOCAL ROLE dms_app"))
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("SELECT 1 FROM auth_tokens"))


def test_password_reset_flow(env, outbox):
    old = auth(env, "admin-a@x.test")
    known = env.client.post("/api/v1/auth/forgot-password", json={"email": "admin-a@x.test"})
    unknown = env.client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert len(outbox) == 1 and outbox[0].to == "admin-a@x.test"
    env.client.post("/api/v1/auth/forgot-password", json={"email": "admin-a@x.test"})
    assert len(outbox) == 1  # throttled: no second email within a minute
    token = token_from(outbox[0])
    reset = lambda pw, t=token: env.client.post(
        "/api/v1/auth/reset-password", json={"token": t, "password": pw}
    )
    assert reset("short").status_code == 422
    assert reset("admin-a-password-1").status_code == 422  # contains the email name
    assert reset(GOOD).status_code == 204
    assert reset(GOOD).status_code == 400  # single use
    assert (
        env.client.get("/api/v1/auth/me", headers=old).status_code == 401
    )  # signed out everywhere
    assert (
        env.client.post(
            "/api/v1/auth/login", json={"email": "admin-a@x.test", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        env.client.post(
            "/api/v1/auth/login", json={"email": "admin-a@x.test", "password": GOOD}
        ).status_code
        == 200
    )


def test_reset_clears_lockout(env, outbox):
    for _ in range(get_settings().LOGIN_MAX_FAILURES):
        env.client.post(
            "/api/v1/auth/login", json={"email": "admin-a@x.test", "password": "wrong-wrong-wrong"}
        )
    env.client.post("/api/v1/auth/forgot-password", json={"email": "admin-a@x.test"})
    env.client.post(
        "/api/v1/auth/reset-password", json={"token": token_from(outbox[0]), "password": GOOD}
    )
    assert (
        env.client.post(
            "/api/v1/auth/login", json={"email": "admin-a@x.test", "password": GOOD}
        ).status_code
        == 200
    )


def test_reset_is_audited_and_bad_tokens_rejected(env, admin, outbox):
    assert (
        env.client.post(
            "/api/v1/auth/reset-password", json={"token": "x" * 30, "password": GOOD}
        ).status_code
        == 400
    )
    env.client.post("/api/v1/auth/forgot-password", json={"email": "admin-a@x.test"})
    env.client.post(
        "/api/v1/auth/reset-password", json={"token": token_from(outbox[0]), "password": GOOD}
    )
    new_admin = env.client.post(
        "/api/v1/auth/login", json={"email": "admin-a@x.test", "password": GOOD}
    ).json()
    h = {"Authorization": f"Bearer {new_admin['access_token']}"}
    assert "auth.password_reset" in [
        e["action"] for e in env.client.get("/api/v1/audit-events", headers=h).json()
    ]


def test_self_registration_flow(env, admin, employee, outbox):
    reg = lambda slug="alpha", email="joiner@example.com": env.client.post(
        "/api/v1/auth/register", json={"tenant_slug": slug, "email": email, "full_name": "Joiner"}
    )
    first = reg()
    assert first.status_code == 202
    assert (
        env.client.get("/api/v1/registration-requests", headers=admin).json() == []
    )  # disabled by default
    assert (
        env.client.patch(
            "/api/v1/tenant/settings", json={"self_registration_enabled": True}, headers=employee
        ).status_code
        == 403
    )
    s = env.client.patch(
        "/api/v1/tenant/settings", json={"self_registration_enabled": True}, headers=admin
    )
    assert s.json() == {"slug": "alpha", "self_registration_enabled": True}
    unknown = reg(slug="no-such-org")
    assert unknown.json() == first.json() and unknown.status_code == 202  # uniform answer
    reg()
    reg(email="JOINER@example.com")  # duplicate while pending
    pending = env.client.get("/api/v1/registration-requests", headers=admin).json()
    assert len(pending) == 1 and pending[0]["email"] == "joiner@example.com"
    assert env.client.get("/api/v1/registration-requests", headers=employee).status_code == 403
    assert (
        env.client.get("/api/v1/registration-requests", headers=auth(env, "admin-b@x.test")).json()
        == []
    )
    rid = pending[0]["id"]
    assert (
        env.client.post(
            f"/api/v1/registration-requests/{rid}/approve", headers=auth(env, "admin-b@x.test")
        ).status_code
        == 404
    )
    assert (
        env.client.post(
            f"/api/v1/registration-requests/{rid}/approve", json={"note": "welcome"}, headers=admin
        ).status_code
        == 204
    )
    assert (
        env.client.post(f"/api/v1/registration-requests/{rid}/reject", headers=admin).status_code
        == 409
    )
    assert len(outbox) == 1 and outbox[0].to == "joiner@example.com"
    assert accept(env, token_from(outbox[0])).status_code == 200
    assert reg().status_code == 202  # already a member: silently ignored
    assert env.client.get("/api/v1/registration-requests", headers=admin).json() == []
    log = [
        e["action"]
        for e in env.client.get("/api/v1/audit-events", params={"limit": 200}, headers=admin).json()
    ]
    assert {"registration.requested", "registration.approved", "tenant.settings.updated"} <= set(
        log
    )


def test_registration_rejection_sends_nothing(env, admin, outbox):
    env.client.patch(
        "/api/v1/tenant/settings", json={"self_registration_enabled": True}, headers=admin
    )
    env.client.post(
        "/api/v1/auth/register",
        json={"tenant_slug": "alpha", "email": "no@example.com", "full_name": "No"},
    )
    rid = env.client.get("/api/v1/registration-requests", headers=admin).json()[0]["id"]
    assert (
        env.client.post(f"/api/v1/registration-requests/{rid}/reject", headers=admin).status_code
        == 204
    )
    assert outbox == []
    done = env.client.get(
        "/api/v1/registration-requests", params={"status": "rejected"}, headers=admin
    ).json()
    assert [d["status"] for d in done] == ["rejected"]


def test_email_builder_and_production_guard():
    s = Settings(_env_file=None, EMAIL_FROM="dms@example.com")
    mime = email_service.build_mime(s, email_service.EmailMessage("a@example.com", "Hi", "Body"))
    assert (mime["From"], mime["To"], mime["Subject"]) == ("dms@example.com", "a@example.com", "Hi")
    with pytest.raises(ValueError):
        Settings(
            _env_file=None, ENVIRONMENT="production", SECRET_KEY="x" * 40
        )  # console email not allowed


def test_change_password_keeps_this_session_and_signs_out_others(env):
    login = lambda pw: env.client.post(
        "/api/v1/auth/login", json={"email": "admin-a@x.test", "password": pw}
    )
    here = auth(env, "admin-a@x.test")
    other = {"Authorization": f"Bearer {login(PASSWORD).json()['access_token']}"}
    change = lambda cur, new: env.client.post(
        "/api/v1/auth/change-password",
        json={"current_password": cur, "new_password": new},
        headers=here,
    )
    assert change("wrong-password", GOOD).status_code == 422
    assert change(PASSWORD, PASSWORD).status_code == 422
    assert change(PASSWORD, "short").status_code == 422
    assert change(PASSWORD, "admin-a-password-1").status_code == 422  # contains the email name
    assert (
        env.client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": GOOD},
        ).status_code
        == 401
    )
    assert change(PASSWORD, GOOD).status_code == 204
    assert env.client.get("/api/v1/auth/me", headers=here).status_code == 200
    assert env.client.get("/api/v1/auth/me", headers=other).status_code == 401
    assert login(PASSWORD).status_code == 401
    assert login(GOOD).status_code == 200
