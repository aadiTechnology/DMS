# ruff: noqa: F811
import time

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import text

from app.core.config import get_settings
from app.services import mfa
from tests.test_rbac import PASSWORD, auth, env  # noqa: F401  (fixtures)

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"


def test_totp_matches_rfc6238_vectors():
    # RFC 6238 appendix B (SHA-1) values, truncated to 6 digits
    assert mfa.totp_at(RFC_SECRET, 59) == "287082"
    assert mfa.totp_at(RFC_SECRET, 1111111109) == "081804"
    assert mfa.totp_at(RFC_SECRET, 1234567890) == "005924"


def test_window_and_replay_protection():
    now = 1111111109.0
    code = mfa.totp_at(RFC_SECRET, now)
    step = mfa.match_step(RFC_SECRET, code, 0, now)
    assert step == int(now // 30)
    assert mfa.match_step(RFC_SECRET, code, step, now) is None  # same code cannot be reused
    assert mfa.match_step(RFC_SECRET, code, 0, now + 30) == step  # one step of clock drift
    assert mfa.match_step(RFC_SECRET, code, 0, now + 120) is None  # too old
    assert mfa.match_step(RFC_SECRET, "000000", 0, now) is None


def login(env, email="admin-a@x.test", password=PASSWORD, **extra):
    return env.client.post(
        "/api/v1/auth/login", json={"email": email, "password": password, **extra}
    )


def enable(env, headers):
    secret = env.client.post("/api/v1/auth/mfa/setup", headers=headers).json()["secret"]
    r = env.client.post(
        "/api/v1/auth/mfa/enable", json={"code": mfa.totp_at(secret, time.time())}, headers=headers
    )
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def next_code(secret):  # a code for the following time step (newer than the one used to enable)
    return mfa.totp_at(secret, time.time() + 30)


def test_setup_enable_and_login_flow(env):
    h = auth(env, "admin-a@x.test")
    assert env.client.get("/api/v1/auth/mfa", headers=h).json() == {"enabled": False}
    setup = env.client.post("/api/v1/auth/mfa/setup", headers=h).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/DMS:admin-a@x.test?secret=")
    with env.engine.connect() as c:
        stored = c.execute(
            text("SELECT mfa_secret_encrypted, mfa_enabled FROM users WHERE id=:i"),
            {"i": env.admin_a},
        ).one()
    assert setup["secret"] not in stored[0] and stored[1] is False  # encrypted, not yet active
    bad = env.client.post("/api/v1/auth/mfa/enable", json={"code": "000000"}, headers=h)
    assert bad.status_code == 422
    secret = setup["secret"]
    done = env.client.post(
        "/api/v1/auth/mfa/enable", json={"code": mfa.totp_at(secret, time.time())}, headers=h
    )
    assert done.status_code == 200 and len(done.json()["recovery_codes"]) == 8
    assert env.client.get("/api/v1/auth/mfa", headers=h).json() == {"enabled": True}
    assert env.client.post("/api/v1/auth/mfa/setup", headers=h).status_code == 409

    no_code = login(env)
    assert no_code.status_code == 401 and no_code.json()["detail"] == {"code": "mfa_required"}
    code = next_code(secret)
    ok = login(env, mfa_code=code)
    assert ok.status_code == 200
    assert login(env, mfa_code=code).status_code == 401  # a code works once


def test_wrong_codes_count_toward_lockout(env):
    h = auth(env, "admin-a@x.test")
    secret, _ = enable(env, h)
    for _ in range(get_settings().LOGIN_MAX_FAILURES):
        assert login(env, mfa_code="000000").status_code == 401
    assert login(env, mfa_code=next_code(secret)).status_code == 401  # locked despite right code


def test_recovery_codes_are_single_use(env):
    h = auth(env, "admin-a@x.test")
    _, codes = enable(env, h)
    assert login(env, mfa_code=codes[0]).status_code == 200
    assert login(env, mfa_code=codes[0]).status_code == 401
    assert login(env, mfa_code=codes[1].upper()).status_code == 200
    with env.engine.connect() as c:
        stored = c.execute(text("SELECT code_hash FROM mfa_recovery_codes")).scalars().all()
    assert len(stored) == 8 and codes[2] not in stored  # only hashes are kept


def test_disable_needs_password_and_second_factor(env):
    h = auth(env, "admin-a@x.test")
    _, codes = enable(env, h)
    url = "/api/v1/auth/mfa/disable"
    assert (
        env.client.post(
            url, json={"password": "wrong-wrong-wrong", "code": codes[0]}, headers=h
        ).status_code
        == 422
    )
    assert (
        env.client.post(url, json={"password": PASSWORD, "code": "000000"}, headers=h).status_code
        == 422
    )
    assert (
        env.client.post(url, json={"password": PASSWORD, "code": codes[1]}, headers=h).status_code
        == 204
    )
    assert login(env).status_code == 200  # plain password login again
    assert (
        env.client.post(url, json={"password": PASSWORD, "code": codes[2]}, headers=h).status_code
        == 409
    )
    log = [
        e["action"]
        for e in env.client.get("/api/v1/audit-events", params={"limit": 100}, headers=h).json()
    ]
    assert "auth.mfa_enabled" in log and "auth.mfa_disabled" in log


def test_enable_without_setup_and_unauthenticated(env):
    h = auth(env, "admin-a@x.test")
    assert (
        env.client.post("/api/v1/auth/mfa/enable", json={"code": "123456"}, headers=h).status_code
        == 422
    )
    assert env.client.post("/api/v1/auth/mfa/setup").status_code == 401
    assert env.client.get("/api/v1/auth/mfa").status_code == 401


def test_admin_can_reset_lost_device_and_it_is_audited(env):
    from app.db.tenant_session import tenant_session
    from app.services import rbac

    with tenant_session(env.ta, env.engine) as s:
        rbac.assign_role(s, env.ta, env.admin_a, env.mem_emp, env.roles_a["employee"])
    emp = auth(env, "emp-a@x.test")
    enable(env, emp)
    assert login(env, "emp-a@x.test").status_code == 401  # locked behind MFA
    url = f"/api/v1/employees/{env.mem_emp}/mfa/reset"
    assert env.client.post(url, headers=emp).status_code == 403  # employees cannot reset anyone
    admin = auth(env, "admin-a@x.test")
    assert (
        env.client.post(url, headers=auth(env, "admin-b@x.test")).status_code == 404
    )  # other tenant
    assert env.client.post(url, headers=admin).status_code == 204
    assert login(env, "emp-a@x.test").status_code == 200
    events = env.client.get(
        "/api/v1/audit-events", params={"action": "auth.mfa_reset_by_admin"}, headers=admin
    ).json()
    assert len(events) == 1 and events[0]["privileged"] is True


def test_secret_encryption_roundtrip_and_key_override():
    s = get_settings()
    token = mfa._encrypt(s, RFC_SECRET)
    assert RFC_SECRET not in token and mfa._decrypt(s, token) == RFC_SECRET
    other = s.model_copy(update={"MFA_ENCRYPTION_KEY": "x" * 43 + "="})
    with pytest.raises(InvalidToken):
        mfa._decrypt(other, token)
    user = type("U", (), {"id": 1, "mfa_secret_encrypted": token})()
    assert (
        mfa._user_secret(other, user) is None
    )  # rotated key degrades to a failed check, not a 500
